#!/usr/bin/env python3
"""lb_shellread.py — is this shell command a pure read? Conservative: unsure means NO.

WHY THIS EXISTS. The gate's READ_ONLY allowlist matches tool NAMES, and `bash` is not on it,
so every shell call counted as acting — `ls`, `grep`, `wc -l`, `git status` included. A
checker on 2026-10-16 saw three read-only shell calls refused while the refusal text said
"reads are still passing". The words were true for the Read tool and false for the shell,
which is where most agents on this machine actually read.

WHERE IT IS USED. Only by the nudge-mode step count in lb_gate (the default since
2026-10-16), which never refuses anything. It does NOT exempt a call from the drift gate and
it is never consulted in hard, watch or signal mode. A wrong answer here therefore costs at
most one misplaced reminder or log row; it can never let a refused call through.

THE RULE. A command is a read only if EVERY segment (split on | |& || && ; and newlines) is a
command on the allow-list below, used without any of its writing options, and the whole line
has no output redirection except to /dev/null (or /dev/stdout, /dev/stderr), and none of:
parameter, command, arithmetic or process expansion ($ or a backquote anywhere outside single
quotes), brace expansion ({ or } unquoted), a comment (# unquoted, anywhere — shells also
treat `a#b` as a word, but one wrong guess would swallow every later line), a subshell, a
here-document, a background job, or a VAR=value prefix. Unquoted globs are allowed only for
commands that no argument can turn into a writer (a file called `-delete` in the directory
would otherwise make `find . *` delete). Anything this module cannot parse, or has not heard
of, is acting. A wrong "read" lets an unchecked write go unnoticed by the step count; a wrong
"acting" only costs a nudge, so every doubt resolves to acting.

The tokenizer is written out here rather than taken from shlex, because shlex treats `#`
inside a word as a comment and cannot say which characters were quoted (checker,
2026-10-17: 47 of 83 adversarial commands were writes classed as reads).

Pure function, no I/O, never raises: is_read_only_command() returns False on any error.
"""
import re

# Commands that only read whatever arguments they are given — including arguments that
# come from a glob or from xargs's stdin, which this module cannot see.
SAFE_ANY_ARGS = frozenset({
    'ls', 'cat', 'head', 'tail', 'wc', 'stat', 'grep', 'egrep', 'fgrep', 'du', 'df', 'pwd',
    'which', 'whoami', 'uname', 'basename', 'dirname', 'realpath', 'readlink', 'cut', 'tr',
    'nl', 'comm', 'diff', 'cmp', 'md5', 'md5sum', 'shasum', 'sha256sum', 'sha1sum', 'jq',
    'echo', 'printf', 'true', 'column', 'ps', 'cd',
})
# Commands that read unless an option makes them write or run something; each has a rule in
# _segment_is_read, and none of them accepts an unquoted glob.
RULED = frozenset({'find', 'sed', 'sort', 'tree', 'rg', 'date', 'git', 'xargs', 'file', 'ffprobe'})
READ_COMMANDS = SAFE_ANY_ARGS | RULED

# git subcommands that never change the repository or the working tree (with the option
# rules below: branch/tag only list, remote only shows, stash only list/show, reflog only
# shows).
GIT_READ = frozenset({
    'status', 'log', 'diff', 'show', 'rev-parse', 'ls-files', 'blame', 'describe',
    'shortlog', 'grep', 'ls-tree', 'cat-file', 'reflog', 'branch', 'tag', 'remote', 'stash',
})
_GIT_GLOBAL_FLAGS = ('--no-pager', '-P', '--no-optional-locks', '--literal-pathspecs',
                     '--no-replace-objects')
_BRANCH_OK = frozenset({'-a', '--all', '-r', '--remotes', '-v', '-vv', '--verbose', '-l',
                        '--list', '--show-current', '--no-color', '--color', '--column',
                        '--no-column', '-q', '--quiet', '-i', '--ignore-case', '--omit-empty'})
_TAG_OK = frozenset({'-l', '--list', '-n', '--column', '--no-column', '--no-color', '--color',
                     '-i', '--ignore-case', '--omit-empty'})
_LIST_VALUED = ('--sort=', '--format=', '--color=', '--column=')

# find primaries that write, delete or run something.
_FIND_WRITES = frozenset({'-delete', '-exec', '-execdir', '-ok', '-okdir', '-fprint',
                          '-fprint0', '-fprintf', '-fls'})
# sed: a read only as `sed -n <print-range>...`, with every script a print range.
_SED_PRINT = re.compile(r"^(?:\d+|\$)?(?:,(?:\d+|\$))?p$")
_SED_LONG = ('quiet', 'silent', 'debug', 'expression', 'file', 'follow-symlinks', 'in-place',
             'line-length', 'null-data', 'zero-terminated', 'posix', 'regexp-extended',
             'separate', 'sandbox', 'unbuffered', 'help', 'version')
_SED_LONG_OK = frozenset({'debug', 'null-data', 'zero-terminated', 'posix', 'regexp-extended',
                          'separate', 'sandbox', 'unbuffered', 'help', 'version'})
_DATE_OK = re.compile(r'^(?:\+.*|-u|--utc|--universal|-R|--rfc-email|'
                      r'-I(?:date|hours|minutes|seconds|ns)?|--iso-8601(?:=\w+)?)$', re.S)
_ASSIGN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')

_OPS = ('&>>', '<<<', '&&', '||', ';;', '|&', '>>', '>|', '&>', '>&', '<<', '<>', '<&',
        '(', ')', '|', '&', ';', '<', '>')
_SEPARATORS = {'|', '||', '&&', ';', '|&'}
_SINKS = {'/dev/null', '/dev/stdout', '/dev/stderr'}
_MAX_LEN = 8000


def _tokens(cmd):
    """[(text, 'w', glob) | (op, 'op', fd)], or None for a shape this module does not model.

    POSIX-shell quoting: '...' is literal; "..." is literal except that $ and ` expand
    (refused here) and backslash escapes $ ` " \\ and newline; outside quotes a backslash
    makes the next character literal and backslash-newline joins lines. A digit run written
    straight before < or > is that redirection's file descriptor, as in `2>/dev/null`.
    """
    toks = []
    buf, inword, quoted, glob = [], False, False, False
    i, n = 0, len(cmd)

    def end():
        nonlocal buf, inword, quoted, glob
        if inword:
            toks.append((''.join(buf), 'w', glob))
        buf, inword, quoted, glob = [], False, False, False

    while i < n:
        c = cmd[i]
        if c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                return None
            buf.append(cmd[i + 1:j])
            inword = quoted = True
            i = j + 1
            continue
        if c == '"':
            i += 1
            while True:
                if i >= n:
                    return None
                d = cmd[i]
                if d == '"':
                    i += 1
                    break
                if d in '$`':
                    return None
                if d == '\\' and i + 1 < n and cmd[i + 1] in '$`"\\\n':
                    if cmd[i + 1] != '\n':
                        buf.append(cmd[i + 1])
                    i += 2
                    continue
                buf.append(d)
                i += 1
            inword = quoted = True
            continue
        if c == '\\':
            if i + 1 >= n:
                return None
            if cmd[i + 1] != '\n':
                buf.append(cmd[i + 1])
                inword = quoted = True
            i += 2
            continue
        if c in '$`{}#':
            return None
        if c in ' \t':
            end()
            i += 1
            continue
        if c == '\n':
            end()
            toks.append((';', 'op', None))
            i += 1
            continue
        if c in '|&;<>()':
            fd = None
            if c in '<>' and inword and not quoted and buf and ''.join(buf).isdigit():
                fd = ''.join(buf)
                buf, inword, quoted, glob = [], False, False, False
            end()
            for op in _OPS:
                if cmd.startswith(op, i):
                    toks.append((op, 'op', fd))
                    i += len(op)
                    break
            continue
        if c in '*?[':
            glob = True
        buf.append(c)
        inword = True
        i += 1
    end()
    return toks


def _segments(toks):
    """Split on separators, dropping redirects to a sink. None = an unsafe shape."""
    segs, cur, i = [], [], 0
    while i < len(toks):
        text, kind, extra = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if kind == 'w':
            cur.append((text, extra))
        elif text in _SEPARATORS:
            segs.append(cur)
            cur = []
        elif text in ('>', '>>', '&>', '&>>', '>|'):
            if not nxt or nxt[1] != 'w' or nxt[2] or nxt[0] not in _SINKS:
                return None                      # writes a file
            i += 1
        elif text == '>&':
            if not nxt or nxt[1] != 'w' or nxt[0] not in ('1', '2', '-'):
                return None
            i += 1
        elif text == '<':
            if not nxt or nxt[1] != 'w' or nxt[2]:
                return None
            i += 1                               # input from a file is a read
        else:
            return None                          # subshell, here-doc, background, <>, ;;
        i += 1
    segs.append(cur)
    return segs


def _long_name(a):
    return a[2:].split('=', 1)[0] if a.startswith('--') else None


def _long_hits(args, names):
    """True if any --option names one of `names`, abbreviated (GNU and git both accept
    unambiguous prefixes, so `--out=f` is `--output=f`) or extended."""
    for a in args:
        nm = _long_name(a)
        if nm and any(n.startswith(nm) or nm.startswith(n) for n in names):
            return True
    return False


def _short_has(args, letters):
    """True if any short-option cluster (`-uo`, `-Ei`) contains one of `letters`."""
    return any(a.startswith('-') and not a.startswith('--') and len(a) > 1
               and any(ch in a[1:] for ch in letters) for a in args)


def _sed_is_read(args):
    scripts, positional, quiet, i = [], [], False, 0
    while i < len(args):
        a = args[i]
        if a == '--':
            positional += args[i + 1:]
            break
        if a.startswith('--'):
            nm, eq, val = a[2:].partition('=')
            hits = [o for o in _SED_LONG if o == nm] or [o for o in _SED_LONG if o.startswith(nm)]
            if len(hits) != 1:
                return False                     # unknown or ambiguous
            o = hits[0]
            if o in ('quiet', 'silent'):
                quiet = True
            elif o == 'expression':
                if eq:
                    scripts.append(val)
                elif i + 1 < len(args):
                    scripts.append(args[i + 1])
                    i += 1
                else:
                    return False
            elif o not in _SED_LONG_OK:
                return False                     # file, in-place, line-length, symlinks
        elif a.startswith('-') and len(a) > 1:
            body = a[1:]
            for k, ch in enumerate(body):
                if ch == 'n':
                    quiet = True
                elif ch in 'Ersuz':
                    pass
                elif ch == 'e':
                    rest = body[k + 1:]
                    if rest:
                        scripts.append(rest)
                    elif i + 1 < len(args):
                        scripts.append(args[i + 1])
                        i += 1
                    else:
                        return False
                    break
                else:
                    return False                 # -i, -f, -l, -a, anything unknown
        else:
            positional.append(a)
        i += 1
    if not scripts:
        if not positional:
            return False
        scripts = [positional[0]]
    return quiet and all(_SED_PRINT.match(s) for s in scripts)


def _git_is_read(args):
    rest = list(args)
    while rest and rest[0].startswith('-'):
        g = rest[0]
        if g == '-C' and len(rest) > 1:
            rest = rest[2:]
        elif g in _GIT_GLOBAL_FLAGS or g.startswith(('--git-dir=', '--work-tree=')):
            rest = rest[1:]
        else:
            return False                         # -c (config can run programs), -p, --exec-path ...
    if not rest or rest[0] not in GIT_READ:
        return False
    sub, sargs = rest[0], rest[1:]
    positional = [a for a in sargs if not a.startswith('-')]
    if _long_hits(sargs, ('output', 'ext-diff')):
        return False
    if sub == 'grep':
        # -O<cmd> / --open-files-in-pager=<cmd> run a program on the matches.
        return not (_short_has(sargs, 'O') or _long_hits(sargs, ('open-files-in-pager',)))
    if '-o' in sargs:
        return False
    if sub == 'branch':
        return not positional and all(
            a in _BRANCH_OK or a.startswith(_LIST_VALUED)
            or (a.startswith('-') and not a.startswith('--') and set(a[1:]) <= set('arvlqi'))
            for a in sargs)
    if sub == 'tag':
        return not positional and all(
            a in _TAG_OK or a.startswith(_LIST_VALUED) or re.fullmatch(r'-n\d+', a)
            for a in sargs)
    if sub == 'remote':
        if not positional:
            return all(a in ('-v', '--verbose') for a in sargs)
        return positional[0] in ('show', 'get-url')
    if sub == 'stash':
        return bool(sargs) and sargs[0] in ('list', 'show')
    if sub == 'reflog':
        # `git reflog` and `git reflog show` read; expire, delete and exists do not belong.
        return not positional or (bool(sargs) and sargs[0] == 'show')
    return True


def _xargs_is_read(seg):
    rest = list(seg)
    while rest and rest[0][0].startswith('-'):
        f = rest[0][0]
        if f in ('-0', '-r', '--null', '--no-run-if-empty', '-t', '--verbose'):
            rest = rest[1:]
        elif f in ('-n', '-P', '-L') and len(rest) > 1 and rest[1][0].isdigit():
            rest = rest[2:]
        elif re.fullmatch(r'-[nPL]\d+', f):
            rest = rest[1:]
        else:
            return False                         # -a, -I, -J, -R, -S, -E, -d, -o, -p ...
    if not rest:
        return True                              # bare xargs runs echo
    # stdin supplies arguments nobody here can see, so the command must be one that no
    # argument can turn into a writer.
    return rest[0][0] in SAFE_ANY_ARGS and rest[0][0] != 'cd' and not rest[0][1]


def _segment_is_read(seg):
    if not seg:
        return True                              # empty segment, e.g. a trailing ';'
    name, name_glob = seg[0]
    args = [t for t, _ in seg[1:]]
    if name_glob or _ASSIGN.match(name):
        return False                             # VAR=x cmd: PATH=... can make ls anything
    if '/' in name or name not in READ_COMMANDS:
        return False
    if name in SAFE_ANY_ARGS:
        return True
    if any(g for _, g in seg[1:]):
        return False                             # a glob could expand to an option
    if name == 'find':
        return not any(a in _FIND_WRITES for a in args)
    if name == 'sed':
        return _sed_is_read(args)
    if name == 'sort':
        return not (_short_has(args, 'o') or _long_hits(args, ('output', 'compress-program')))
    if name == 'tree':
        return not (_short_has(args, 'oR') or _long_hits(args, ('output',)))
    if name == 'rg':
        return not any(a.startswith(('--pre', '--hostname-bin')) for a in args)
    if name == 'date':
        return all(_DATE_OK.match(a) for a in args)
    if name == 'file':
        return not (_short_has(args, 'C') or _long_hits(args, ('compile',)))
    if name == 'ffprobe':
        return not any(a in ('-o', '-report') or a.startswith(('-dump', '-progress'))
                       or 'lavfi' in a.lower() for a in args)
    if name == 'git':
        return _git_is_read(args)
    if name == 'xargs':
        return _xargs_is_read(seg[1:])
    return False


def is_read_only_command(cmd):
    """True only when every part of `cmd` is a known read. Never raises."""
    try:
        if not isinstance(cmd, str) or not cmd.strip() or len(cmd) > _MAX_LEN:
            return False
        toks = _tokens(cmd)
        if toks is None:
            return False
        segs = _segments(toks)
        if segs is None or not any(segs):
            return False
        return all(_segment_is_read(s) for s in segs)
    except Exception:
        return False


SHELL_TOOLS = ('bash', 'shell', 'run_terminal_command', 'run_shell_command')


def shell_command_of(ev):
    """The command string of a shell tool call, or None for anything else."""
    try:
        tool = str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '').lower()
        if tool not in SHELL_TOOLS:
            return None
        ti = ev.get('tool_input') if ev.get('tool_input') is not None else ev.get('toolInput')
        if isinstance(ti, dict):
            c = ti.get('command') or ti.get('cmd')
            return c if isinstance(c, str) else None
        return None
    except Exception:
        return None
