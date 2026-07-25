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
    (re.compile(r'\bwrangler\s+deploy\b', re.I),
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
    (re.compile(r'\bpypi|twine\s+upload\b', re.I),
     'package registry upload'),
]

BASH_TOOLS = (
    'bash', 'run_terminal_command', 'shell', 'terminal',
    'run_command', 'execute', 'local_shell',
)


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


def main():
    # Escape hatch for intentional automation (CI, Diego's override)
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
    for pat, label in DENY_PATTERNS:
        if pat.search(cmd):
            deny(
                f'laserbrain safety: blocked {label}.\n'
                f'THIS CALL DID NOT RUN.\n'
                f'permission_mode may be always-approve, but irreversible shared-remote / '
                f'destructive actions still need Diego\'s explicit OK in chat.\n'
                f'Ask, then reissue only after confirmation. '
                f'Emergency bypass: LASERBRAIN_SAFETY_OFF=1 (do not use casually).\n'
                f'command was: {cmd[:240]}'
            )


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass
    sys.exit(0)
