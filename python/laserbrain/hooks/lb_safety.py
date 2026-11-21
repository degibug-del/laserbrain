#!/usr/bin/env python3
"""lb_safety.py — PreToolUse deny for irreversible shell actions under always-approve.

permission_mode=always-approve is intentional for speed, but force-push, hard reset,
recursive force delete, production deploys and package publishing must still stop for a
person's confirmation. This hook denies the tool call with a clear reason: the command
needs the explicit OK of the person running the session, and that person runs it.

Fail OPEN on any parse/error path — same rule as lb_gate. The one optional input, the
allowance file (ALLOWANCES below), fails the other way: a file that is missing, unreadable
or malformed allows nothing, so an error there can only leave a command blocked.
"""
import sys, json, os, re, stat

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
    # One carve-out in the pattern itself, narrow on purpose: --dry-run builds and validates
    # without publishing anything, so blocking it stops a syntax check rather than a
    # deploy. Caught on 2026-07-25 trying to validate a new Durable Object binding. A guard
    # that blocks the safe rehearsal of a risky action pushes people toward doing the risky
    # one untested.
    #
    # A deploy of a Worker the user has named can also run, from the user's own config file
    # and from nowhere else: see ALLOWANCES below. Until 0.58.0 one such Worker was named
    # here in the code, so every install carried one machine's standing permission.
    #
    # NOTE for whoever edits this next: this file cannot be patched from a shell heredoc,
    # because the patch text contains the very patterns below and the hook scans the whole
    # command string. Two attempts on 2026-07-27 were denied by the rule being edited.
    # Use a file-editing tool. Same false-positive class as the `git commit` whose MESSAGE
    # mentioned a blocked command, noted further down.
    (re.compile(r'\bwrangler\s+deploy\b(?![^\n|;&]*--dry-run)', re.I),
     'wrangler deploy (production Workers deploy)'),
    # `wrangler pages deploy` was here until 2026-07-25, when the owner of the machine this
    # hook was written on gave a standing authorization for deploying finished work.
    #
    # That is the explicit OK this hook was written to wait for, so it was recorded rather
    # than asked for again every time. It is deliberately the ONLY rule removed —
    # force-push, reset --hard, rm -rf, npm publish and registry uploads all still stop,
    # because none of those were authorized and they destroy or publish rather than
    # republish. A Pages deploy is reversible: every deployment is retained and the
    # previous one can be promoted back.
    #
    # The standing OK covered deploys of work that was ASKED for. While a thing is still
    # being iterated on with the person, hold: that is a judgement the hook cannot make, so
    # it stays with the agent.
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


# ── ALLOWANCES: standing permissions, from the user's own config only (since 0.58.0) ──────
#
# A standing permission is a statement by the person who owns the machine, so it lives in a
# file under their own config directory and never in this code. Until 0.58.0 one entry was
# hardcoded here (one Worker deploy, authorized on the machine this hook was written on),
# which shipped that one person's permission to every install.
#
#     ~/.config/laserbrain/safety.json     ($LASERBRAIN_HOME/config/safety.json when set)
#
#     {"allow_worker_deploys": ["my-worker"]}
#
# Each name lets a `wrangler deploy` run when the same command also contains that name,
# before or after the verb: `cd workers/my-worker && npx wrangler deploy`, or
# `wrangler deploy --config workers/my-worker/wrangler.toml`. Keying on the path is sound
# because shell state does not persist between tool calls: a deploy has to carry its own
# `cd` or --config in the same command, so there is no way to be "already in" the directory.
# Every other Worker still stops. The name is matched as plain text (re.escape, so a `.` in it
# is a dot), case-insensitively, ANYWHERE in the command, so a name contained in a longer one
# (my-worker in my-worker-2) allows that one too, and a short or common name (x, npx,
# workers, toml) matches nearly every deploy. As before 0.58.0, an allowance covers the WHOLE
# command it matches: a command holding an allowed name and `wrangler deploy` skips every
# rule, a force push or a recursive delete in the same command included. Allow only a
# distinctive name, for a Worker you would let an agent deploy unattended.
#
# Why allow one at all: a verified fix to a hosted Worker once sat staged for hours because
# its deploy could be prepared but not shipped, and the hosted answer stayed wrong where the
# package's was right. A guard that makes the correct version wait is not protecting
# anything. Why per name: that authorization covered one Worker, not wrangler.
#
# FAILS CLOSED. No file, an unreadable file, a file over 64 KiB, text that is not JSON, a
# top-level value that is not an object, or an `allow_worker_deploys` that is not a list:
# no allowance, and so does anything at that path that is not a regular file: it is opened
# non-blocking and checked with fstat before it is read, so a FIFO there cannot hang the
# hook (a hook killed at its timeout would let the refused command run). A name that is not
# a plain path fragment (letters, digits, . _ / -, starting with a letter or digit, at most
# 200 characters) is skipped, so "" or ".*" is never read as a pattern; that is all the
# check does, and it does not stop a short name (see above). The file is read only after a
# deny pattern has matched, so a call that names
# nothing guarded never touches the disk. The refusal text does not mention this file: an
# agent that was refused should ask, not grant itself the permission. An agent with file
# tools could still write it; this is a guard rail, not a sandbox.
ALLOW_FILE = 'safety.json'
_ALLOW_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}')
_ALLOW_MAX_BYTES = 65536


def allowance_path():
    """The allowance file: the lb_paths config root (LASERBRAIN_HOME moves it), safety.json."""
    h = os.environ.get('LASERBRAIN_HOME')
    if h:
        return os.path.join(os.path.expanduser(h), 'config', ALLOW_FILE)
    return os.path.join(os.path.expanduser('~'), '.config', 'laserbrain', ALLOW_FILE)


def allowed_worker_deploys():
    """The Worker names the user's config allows to deploy. [] on any doubt; never raises."""
    try:
        fd = os.open(allowance_path(), os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return []
            fh, fd = os.fdopen(fd, 'rb'), None          # the file object owns it now
        finally:
            if fd is not None:
                os.close(fd)
        with fh:
            raw = fh.read(_ALLOW_MAX_BYTES + 1)
        if len(raw) > _ALLOW_MAX_BYTES:
            return []
        cfg = json.loads(raw.decode('utf-8-sig'))
        names = cfg.get('allow_worker_deploys') if isinstance(cfg, dict) else None
        if not isinstance(names, list):
            return []
        return [n for n in names if isinstance(n, str) and _ALLOW_NAME.fullmatch(n)]
    except Exception:
        return []


def allow_patterns():
    """One compiled pattern per allowed Worker, the shape the built-in entry had before 0.58.0.

    Either order, because the path can appear before the command (`cd X && npx ...`) or after
    it (`--config X`); the first version of the built-in entry only handled the second case.
    """
    pats = []
    for name in allowed_worker_deploys():
        n = re.escape(name)
        pats.append(re.compile(r'\bwrangler\s+deploy\b[\s\S]*' + n
                               + r'|' + n + r'[\s\S]*\bwrangler\s+deploy\b', re.I))
    return pats


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

    An allowance is a statement about the WHOLE command and cannot be written as a
    lookaround inside a deny pattern, because the path may sit on either side of the verb
    and Python has no variable-length lookbehind. It is consulted once a deny pattern has
    matched, which decides exactly what consulting it first did (an allowed command is never
    blocked, and a command no pattern matches runs either way), and it means an ordinary
    call never reads the allowance file.

    A match that is only text — a quoted phrase, a comment, a cat here-document, in a call
    that cannot run text — is let through (B9; see text_only_view). The view is built only
    after a pattern has matched, so a call that names no guarded command pays nothing.
    """
    for pat, label in DENY_PATTERNS:
        if pat.search(cmd):
            if any(p.search(cmd) for p in allow_patterns()):
                return None
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
    # agent confirmed a destructive remote action with the person running the session, was
    # blocked, reissued, was blocked again, then tried the advertised bypass and was blocked
    # a third time — three round trips spent discovering that the documented escape hatch does not
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
                f'permission_mode may be always-approve, but this command is irreversible or '
                f'destructive, so it needs the explicit OK of the person running this session.\n'
                f'Ask them, then have them run it themselves — reissuing will be blocked '
                f'again, and that is intended.\n'
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
