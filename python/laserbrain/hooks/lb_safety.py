#!/usr/bin/env python3
"""lb_safety.py — PreToolUse deny for irreversible shell actions under always-approve.

permission_mode=always-approve is intentional for speed, but force-push, production
deploys, and rm -rf must still stop for human confirmation. This hook denies the tool
call with a clear reason; the agent must ask Diego and only reissue after explicit OK.

Fail OPEN on any parse/error path — same rule as lb_gate.
"""
import sys, json, os, re

# Patterns against the shell command string (case-insensitive).
# Keep this list short and high-confidence — false positives halt real work.
DENY_PATTERNS = [
    (re.compile(r'\bgit\s+push\s+[^\n]*--force\b', re.I),
     'git push --force (force-push to remote)'),
    (re.compile(r'\bgit\s+push\b[^\n]*\s-f\b', re.I),
     'git push -f (force-push to remote)'),
    (re.compile(r'\bgit\s+push\s+[^\n]*--force-with-lease\b', re.I),
     'git push --force-with-lease (rewrites remote history)'),
    (re.compile(r'\bgit\s+reset\s+--hard\b', re.I),
     'git reset --hard (discards uncommitted work)'),
    (re.compile(r'\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-rf|-fr)\b', re.I),
     'rm -rf (recursive force delete)'),
    # Two carve-outs, both narrow on purpose.
    #
    # 1. --dry-run builds and validates without publishing anything, so blocking it stops a
    #    syntax check rather than a deploy. Caught on 2026-07-25 trying to validate a new
    #    Durable Object binding. A guard that blocks the safe rehearsal of a risky action
    #    pushes people toward doing the risky one untested.
    #
    # 2. workers/laserbrain-mcp-remote, authorized by Diego on 2026-07-27: "u should be
    #    able to bypass that". Recorded here rather than re-asked every time — the same
    #    treatment `pages deploy` got below.
    #
    #    Scoped to that ONE directory, not to wrangler generally. Keying on the path is
    #    sound because shell state does not persist between tool calls: a deploy has to
    #    carry its own `cd` or --config in the same command, so there is no way to be
    #    "already in" the directory. Every other Worker still stops here.
    #
    #    The day it was granted is the day it earned itself. The laserbrain Worker sat on a
    #    stale cycle detector for hours because the fix could be staged but not shipped,
    #    and the hosted endpoint answered `stalled` where the package answered
    #    `oscillating` on identical input. A guard that makes the correct version wait is
    #    not protecting anything.
    #
    # NOTE for whoever edits this next: this file cannot be patched from a shell heredoc,
    # because the patch text contains the very patterns below and the hook scans the whole
    # command string. Two attempts on 2026-07-27 were denied by the rule being edited.
    # Use a file-editing tool. Same false-positive class as the `git commit` whose MESSAGE
    # mentioned a blocked command, noted further down.
    (re.compile(r'\bwrangler\s+deploy\b(?![^\n|;&]*--dry-run)', re.I),
     'wrangler deploy (production Workers deploy)'),
    # `wrangler pages deploy` was here until 2026-07-25, when Diego gave standing
    # authorization: "i want u to deploy things as soon as they are built, unless it is
    # something i'm building with you. when i just tell you things, i want u to upload them
    # automatically."
    #
    # That is the explicit OK this hook was written to wait for, so it is recorded here
    # rather than asked for again every time. It is deliberately the ONLY rule removed —
    # force-push, reset --hard, rm -rf, npm publish and registry uploads all still stop,
    # because none of those were authorized and they destroy or publish rather than
    # republish. A Pages deploy is reversible: every deployment is retained and the
    # previous one can be promoted back.
    #
    # The standing OK covers deploys of work Diego ASKED for. While a thing is being
    # iterated on together, hold — that is his carve-out, and it is a judgement the hook
    # cannot make, so it stays with the agent.
    (re.compile(r'\bnpm\s+publish\b', re.I),
     'npm publish (public package publish)'),
    # Alternation binds looser than it reads: `\bpypi|twine\s+upload\b` is
    # `(\bpypi)|(twine\s+upload\b)`, so the bare word "pypi" anywhere in a command matched.
    # On 2026-07-25 it blocked a `git commit` whose MESSAGE said "the published PyPI
    # package" — no upload, no network, just the word. A guard that fires on prose teaches
    # people to route around it, which is the opposite of what it is for.
    # Now: actual publish commands only, each anchored as a whole.
    (re.compile(r'\b(twine\s+upload|flit\s+publish|poetry\s+publish|uv\s+publish|'
                r'python\d?\s+-m\s+twine\s+upload)\b', re.I),
     'package registry upload'),
]

BASH_TOOLS = (
    'bash', 'run_terminal_command', 'shell', 'terminal',
    'run_command', 'execute', 'local_shell',
)


# Explicitly authorized, checked before anything is denied. Each entry records WHO
# authorized it and WHEN — a standing permission with no provenance is indistinguishable
# from one somebody added quietly.
ALLOW_PATTERNS = [
    # Diego, 2026-07-27: "u should be able to bypass that" — asked three times across one
    # session while a verified fix sat staged and unshippable. Scoped to this ONE Worker;
    # every other deploy still stops. Matching either order because the path can appear
    # before the command (`cd X && npx ...`) or after it (`--config X`), and the first
    # attempt only handled the second case.
    (re.compile(r'\bwrangler\s+deploy\b[\s\S]*laserbrain-mcp-remote'
                r'|laserbrain-mcp-remote[\s\S]*\bwrangler\s+deploy\b', re.I),
     'laserbrain MCP Worker deploy, authorized 2026-07-27'),
]


def deny(reason):
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
    }}))
    sys.stderr.write(reason + '\n')
    sys.exit(2)


def tool_name(ev):
    return str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '').lower()


def command_of(ev):
    ti = ev.get('tool_input') or ev.get('toolInput') or ev.get('arguments') or {}
    if not isinstance(ti, dict):
        return str(ti or '')
    return str(ti.get('command') or ti.get('cmd') or ti.get('script') or '')


def blocked_reason(cmd):
    """The label of the rule that stops this command, or None if it may run.

    THE decision, in one function, so it can be tested without a subprocess. It was inline
    in main(), which meant a test had to walk DENY_PATTERNS by hand — and therefore could
    not see the allow-list at all, and reported two authorized commands as blocked. A rule
    reachable only through stdin is a rule nothing checks.

    Allow before deny: an authorization is a statement about the WHOLE command and cannot
    be written as a lookaround inside a deny pattern, because the path may sit on either
    side of the verb and Python has no variable-length lookbehind.
    """
    for pat, _why in ALLOW_PATTERNS:
        if pat.search(cmd):
            return None
    for pat, label in DENY_PATTERNS:
        if pat.search(cmd):
            return label
    return None


def main():
    # ESCAPE HATCH, and it is deliberately NOT reachable from inside a command.
    #
    # This reads the HOOK's environment. A hook runs as its own process, so setting the
    # variable as a prefix on the blocked command hands it to that command and never to
    # this one. That is correct and must stay: a guard an agent can switch off by typing
    # eleven characters in front of the thing being guarded is not a guard, it is a speed
    # bump with instructions attached.
    #
    # The message below used to advertise it as though the prefix worked. On 2026-08-05 an
    # agent (me) confirmed a destructive remote action with Diego in chat, was blocked,
    # reissued, was blocked again, then tried the advertised bypass and was blocked a third
    # time — three round trips spent discovering that the documented escape hatch does not
    # open the way it is written. An instruction that cannot be followed is worse than
    # none: it turns a correct refusal into a puzzle, and the moment to find that out is
    # not whatever made someone reach for the override.
    #
    # To actually disable this: export it in the environment that LAUNCHES the harness, or
    # set it under `env` in settings.json. Both put it where this process can see it.
    if os.environ.get('LASERBRAIN_SAFETY_OFF', '').strip() in ('1', 'true', 'yes'):
        return
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        return
    t = tool_name(ev)
    if not any(b in t for b in BASH_TOOLS):
        return
    cmd = command_of(ev)
    if not cmd.strip():
        return
    label = blocked_reason(cmd)
    if label:
            deny(
                f'laserbrain safety: blocked {label}.\n'
                f'THIS CALL DID NOT RUN.\n'
                f'permission_mode may be always-approve, but irreversible shared-remote / '
                f'destructive actions still need Diego\'s explicit OK in chat.\n'
                f'Ask, then have DIEGO run it — reissuing will be blocked again, and '
                f'that is intended.\n'
                f'There is no bypass from here: LASERBRAIN_SAFETY_OFF is read from this '
                f'hook\'s own environment, so a prefix on the command does nothing. It '
                f'has to be exported where the harness is launched, or set under `env` in '
                f'settings.json.\n'
                f'command was: {cmd[:240]}'
                + (
                    '\n\nNOTE: this command contains a here-document, so the match may be a '
                    'LITERAL inside your script rather than a command you are running — '
                    'writing a file that documents the guarded phrase trips it. The block '
                    'still stands, deliberately: a heredoc body can be piped to a shell, and '
                    'stripping it before matching would blind this guard to exactly that. '
                    'Rephrase the literal, or write the file with a tool instead of a shell '
                    'heredoc.'
                    if '<<' in cmd else ''
                )
            )


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass
    sys.exit(0)
