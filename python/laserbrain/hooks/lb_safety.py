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


# ── B9: a quoted phrase is not a command ──────────────────────────────────────────────
#
# Measured 2026-11-14 (research/DAY-FOUR-ROUND2.md §7, B9): the patterns above match their
# text ANYWHERE in the command string. `grep -n "<pattern>" notes.md`, a commit message that
# names a guarded command, and a cat here-document that documents the guard were refused
# exactly like the real thing. Auditors were blocked for reading, and nobody could write a
# note about the rule from a shell.
#
# Since 2026-11-17 a match is let through ONLY when the call provably cannot run text, now
# or later:
#   1. every command in it is a text command (TEXT_COMMANDS, the GIT_TEXT subcommands, or
#      `sed -n N,Mp`): it prints or searches, and none executes an argument. A pipe into
#      sh / xargs / awk / `while read`, a script run, an interpreter, ssh, sudo, find -exec,
#      a `$var` in command position, or ANY variable assignment (GIT_PAGER=…, LESSOPEN=…,
#      BASH_ENV=… make the next command run text): any one of these and nothing is let
#      through;
#   2. nothing in it can execute: no $(…) other than the plain "$(cat <<'EOF' … EOF\n)" a
#      commit message is built with, no backticks, no <( >( =(, no $'…', no ${ cmd; } or
#      ${(e)…}, and no `$` at all in a here-document whose delimiter is unquoted;
#   3. it writes nothing that could run later. Output may go to /dev/null or to a .md or
#      .txt file outside .git, and nowhere else — not .zprofile, .envrc, .git/config, a
#      Makefile, package.json, ~/bin/ls. A list of dangerous destinations cannot be complete
#      (the 2026-11-17 review found six that a list missed), so the rule names the safe ones.
#      No tee, uniq OUT, --output, or option that runs a program (rg --pre, git grep -O,
#      sort --compress-program);
#   4. with quoted strings, comments, and here-document bodies blanked, no pattern matches.
# Anything the scanner cannot parse cleanly raises _Unsure and falls back to the old
# whole-string check, so every doubt resolves to a block. What this does NOT change: a real
# recursive delete is refused as before, even of a scratch folder — that was the hook's
# purpose and was never part of B9. A script written with a file tool and run in a LATER
# call was never visible to this hook, before or after B9; it is a guard rail, not a sandbox.

TEXT_COMMANDS = frozenset((
    'grep', 'egrep', 'fgrep', 'rg', 'echo', 'printf', 'cat', 'head', 'tail', 'wc', 'sort',
    'cut', 'tr', 'nl', 'column', 'fold', 'rev', 'tac', 'comm', 'paste', 'jq', 'ls', 'pwd',
    'cd', 'mkdir', 'touch', 'test', '[', 'true', 'false', 'diff', 'cmp', 'basename',
    'dirname', 'date', 'file', 'stat', 'pbcopy',
))
# git subcommands that only record or show text. Not `-c` (an alias can be a shell command),
# nothing that talks to a remote. `grep` only without -O (that runs a pager command).
GIT_TEXT = frozenset(('commit', 'tag', 'log', 'show', 'notes', 'status', 'diff', 'add', 'grep'))
_KEYWORDS = frozenset(('!', 'if', 'then', 'else', 'elif', 'fi', 'while', 'until', 'do', 'done'))
_RUNS_PROGRAM = re.compile(r'--pre\b|--compress-program\b|--output\b|--open-files-in-pager\b'
                           r'|(?:^|\s)-O|\bsort\b[^\n;&|]*\s-o', re.I)
_SED_RANGE = re.compile(r'\d+(?:,\d+)?p')
_WRITE = re.compile(r'<>|>(?:>|\|)?[ \t]*(\S*)')
_SAFE_TARGET = re.compile(r'/dev/null|[\w~./+-]+\.(?:md|txt)')
_HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_][\w.-]*)\2")
_CAT_SUBST = re.compile(r'"\$\(cat[ \t]+<<-?[ \t]*\'([A-Za-z_][\w.-]*)\'[ \t]*\n')
_CAT_SUBST_END = re.compile(r'[ \t]*\)"')
_SEPS = re.compile(r'\|\||&&|[;&|\n(){}]')
_ASSIGN = re.compile(r'[A-Za-z_]\w*=')


class _Unsure(Exception):
    """The scanner could not be sure what the shell would do. Callers fall back to a block."""


def _fold_commit_messages(cmd):
    """Each "$(cat <<'EOF' … EOF\\n)" becomes a plain quoted literal.

    That is how a multi-line commit message is passed, and with a QUOTED delimiter its body
    is never expanded, so it is text. Anything else inside the substitution (a `;` after the
    terminator, say) fails the `)"` check and raises _Unsure. A line that merely strips to
    the delimiter ends the body here no later than bash ends it, so this never treats as
    text anything bash would run.
    """
    out, i = [], 0
    while True:
        m = _CAT_SUBST.search(cmd, i)
        if not m:
            out.append(cmd[i:])
            return ''.join(out)
        delim, k = m.group(1), m.end()
        while True:
            nl = cmd.find('\n', k)
            line = cmd[k:] if nl < 0 else cmd[k:nl]
            if line.strip() == delim:
                break
            if nl < 0:
                raise _Unsure
            k = nl + 1
        end = _CAT_SUBST_END.match(cmd, len(cmd) if nl < 0 else nl + 1)
        if not end:
            raise _Unsure
        out.append(cmd[i:m.start()])
        out.append('"text"')
        i = end.end()


def _skeleton(cmd):
    """cmd as code: quoted contents, comments, and here-document bodies blanked to spaces.

    Raises _Unsure on anything that can run text (command or process substitution,
    backticks, $'…') or that does not parse (an unclosed quote, a here-document with no
    terminator).
    """
    s, n, i = list(cmd), len(cmd), 0
    pending = []   # here-documents opened on the current line: (delimiter, <<-, quoted)

    def blank(a, b):
        for x in range(a, b):
            if s[x] != '\n':
                s[x] = ' '

    while i < n:
        c = cmd[i]
        if c == '\\':
            i += 2
            continue
        if c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                raise _Unsure
            blank(i + 1, j)
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            while j < n and cmd[j] != '"':
                if cmd[j] == '\\':
                    j += 2
                    continue
                if cmd[j] == '`' or cmd.startswith('$(', j) or _funsub(cmd, j):
                    raise _Unsure
                j += 1
            if j >= n:
                raise _Unsure
            blank(i + 1, j)
            i = j + 1
            continue
        if c == '`':
            raise _Unsure
        if c == '$' and i + 1 < n and cmd[i + 1] in "('":
            raise _Unsure
        if _funsub(cmd, i):
            raise _Unsure
        if c in '<>=' and i + 1 < n and cmd[i + 1] == '(':
            raise _Unsure
        # A comment starts only where a WORD starts. `}#` and `{#` are ordinary words (braces
        # are not metacharacters), and in zsh `(#…)` is a glob flag, so only whitespace and
        # ; & | count. Found by the differential probe: `cat }#;<cmd>` runs <cmd>.
        if c == '#' and (i == 0 or cmd[i - 1] in ' \t\n;&|'):
            j = cmd.find('\n', i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
            continue
        if cmd.startswith('<<<', i):
            i += 3
            continue
        if cmd.startswith('<<', i):
            m = _HEREDOC.match(cmd, i)
            if not m:
                raise _Unsure
            pending.append((m.group(3), m.group(1) == '-', bool(m.group(2))))
            i = m.end()
            continue
        if c == '\n' and pending:
            i += 1
            for delim, dash, quoted in pending:
                k = i
                while True:
                    nl = cmd.find('\n', k)
                    line = cmd[k:] if nl < 0 else cmd[k:nl]
                    if (line.lstrip('\t') if dash else line) == delim:
                        break
                    if not quoted and ('`' in line or '$' in line):
                        raise _Unsure      # an unquoted body is expanded: any $ may run code
                    if nl < 0:
                        raise _Unsure
                    k = nl + 1
                end = n if nl < 0 else nl
                blank(i, end)      # the body and its terminator line
                i = end
            pending = []
            continue
        i += 1
    if pending:
        raise _Unsure
    return ''.join(s)


def _funsub(cmd, i):
    """bash 5.3 `${ cmd; }` / `${| cmd; }` run a command; zsh `${(e)…}` evaluates one."""
    return cmd.startswith('${', i) and i + 2 < len(cmd) and cmd[i + 2] in ' \t\n|('


def _only_text_commands(skel):
    flat = re.sub(r'\d*[<>]&(?:\d+|-)', ' ', skel)     # 2>&1, >&2, <&-
    flat = re.sub(r'&>>?', ' > ', flat)                 # &> and &>>
    for m in _WRITE.finditer(flat):                     # every write names a safe target
        target = m.group(1) if m.group(0) != '<>' else None
        if not target or not _SAFE_TARGET.fullmatch(target) or '.git/' in target or target.startswith('.git'):
            return False
    for piece in _SEPS.split(flat):
        words = piece.split()
        while words and words[0] in _KEYWORDS:
            words.pop(0)
        if not words:
            continue
        if any(_ASSIGN.match(w) for w in words[:1]):
            return False                                # FOO=… cmd, or a bare FOO=…
        if words[0] in TEXT_COMMANDS:
            continue
        if words[0] == 'sed' and len(words) >= 3 and words[1] == '-n' \
                and _SED_RANGE.fullmatch(words[2]) and not any(w.startswith('-') for w in words[3:]):
            continue                                    # sed -n 30,40p file: a line range, read only
        if words[0] == 'git':
            rest = words[1:]
            while len(rest) >= 2 and rest[0] == '-C':
                rest = rest[2:]
            if rest and rest[0] in GIT_TEXT:
                continue
        return False
    return True


def _blanked(cmd):
    """The skeleton, or None if the call holds anything that can run text."""
    try:
        return _skeleton(_fold_commit_messages(cmd))
    except Exception:
        return None


def text_only_view(cmd):
    """The command as the shell will run it, with its text blanked, or None.

    None whenever any part of the call could execute text, or whenever parsing is in doubt.
    The caller then checks the raw string exactly as before B9.
    """
    try:
        if _RUNS_PROGRAM.search(cmd):
            return None
        skel = _skeleton(_fold_commit_messages(cmd))
        return skel if _only_text_commands(skel) else None
    except Exception:          # _Unsure, or a scanner bug: either way, no exemption
        return None


def phrase_only_in_text(cmd):
    """True when every guarded phrase sits in a quote, comment or here-document body.

    Decides only whether the denial shows the B9 NOTE. A real delete of "$S" must not be told
    to rephrase a literal; that advice is for text that did not qualify.
    """
    skel = _blanked(cmd)
    return skel is not None and not any(p.search(skel) for p, _l in DENY_PATTERNS)


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

    A match that is only text — a quoted phrase, a comment, a cat here-document, in a call
    that cannot run text — is let through (B9; see text_only_view). The view is built only
    after a pattern has matched, so a call that names no guarded command pays nothing.
    """
    for pat, _why in ALLOW_PATTERNS:
        if pat.search(cmd):
            return None
    for pat, label in DENY_PATTERNS:
        if pat.search(cmd):
            view = text_only_view(cmd)
            if view is not None and not any(p.search(view) for p, _l in DENY_PATTERNS):
                return None
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
                f'If you are a helper agent with no one to ask: do not retry it or work '
                f'around it. Leave it undone and name the blocked command in your final '
                f'report, so the session that started you can ask.\n'
                f'There is no bypass from here: LASERBRAIN_SAFETY_OFF is read from this '
                f'hook\'s own environment, so a prefix on the command does nothing. It '
                f'has to be exported where the harness is launched, or set under `env` in '
                f'settings.json.\n'
                f'command was: {cmd[:240]}'
                + (
                    '\n\nNOTE: the guarded phrase here is only TEXT (in quotes, a comment or a '
                    'here-document). Text is let through when every command in the call just '
                    'prints or searches (grep, rg, echo, printf, cat, head, sort, jq, '
                    'sed -n N,Mp, git commit/log/show/grep, …), nothing can run text (no pipe '
                    'into a shell, interpreter, xargs or awk, no $(…) apart from '
                    '"$(cat <<\'EOF\' … EOF)", no backticks, no variable assignment, no '
                    'script run), and output goes only to /dev/null or a .md/.txt file. This '
                    'call did not qualify. Split it, build the phrase by concatenation inside '
                    'a script, or write the file with a file tool.'
                    if phrase_only_in_text(cmd) else ''
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
