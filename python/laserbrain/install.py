"""`laserbrain install` wires the harness into an agent host; `laserbrain uninstall` takes
out what install wrote, and nothing else.

The MCP server is the instrument; the hooks are the harness. Installing only the server
gives you a detector your agent calls when it remembers to, and an agent that has drifted
is exactly the one that will not remember. This wires both.

WHAT IS WIRED (0.58.0), the shape the package was measured under:

    SessionStart         a self-test. It feeds lb_safety one guarded command and says so,
                         once, when the command is not refused. Healthy, it prints nothing.
    PreToolUse           lb_safety, alone. It refuses a short list of irreversible shell
                         commands (force push, hard reset, recursive delete, deploy,
                         publish) and lets everything else through.
    PostToolUse          lb_coverage, through hooks/fast.py: what the harness watched.
    PostToolUseFailure   the same. Claude Code skips PostToolUse when a call fails, so
                         without it a failed call was never counted (round 2 B3, 2026-11-14).
    UserPromptSubmit     the same.

lb_gate is NOT wired unless --with-gate. Its every-step check is the part that was
measured to cost the most and catch the least, and quiet-by-default lb_coverage already
says what the gate used to. An earlier install's gate entry is removed when install runs
again without --with-gate, and the line saying so names the flag that keeps it.

HOW EACH COMMAND RUNS. Each hook runs a FILE from this install with the interpreter that ran
`laserbrain install` (sys.executable), under `-I -S`:

  - lb_safety.py needs only the standard library. Run as a plain file under -I -S, nothing
    in the package (its __init__, an editable-install finder, a laserbrain copy in the
    agent's working directory, a stray json.py on PYTHONPATH) can stop it refusing. Until
    0.57.0 it ran as `python3 -P -m laserbrain.hooks.lb_safety`, which imports the whole
    package first; on 2026-10-29 a copy that failed to import made lb_safety exit 1, and
    the host let the call through unguarded.
  - The command checks the file first and exits 1 when it is missing, never 2. On
    PreToolUse exit 2 refuses the call, and a Python that cannot find its script exits 2,
    so a moved file would otherwise refuse every tool call.
  - When the interpreter is gone (a version manager moved it), it falls back to python3 on
    PATH, so the guard keeps refusing.
  - fast.py starts lb_coverage without the package __init__ (see that file) and fails open.

A file path bakes this install's location into settings.json. The interpreter path already
did that in the `-m` form, and both move only when the environment does; running
`laserbrain install` again afterwards rewrites the entries it owns in place.

WHAT COUNTS AS OURS. install and uninstall only touch a hook entry whose command is exactly
one this module writes, on the event it writes it on: the shapes below, with any interpreter
and any .../laserbrain/hooks/ path, or the `<python> [-P] -m laserbrain.hooks.<hook>` shape
earlier versions wrote (with any interpreter path, spaces included: those versions did not
quote it). An entry the user wrote that runs the same hook another way is left exactly as it
is, and install does not add a second one beside it. uninstall reports such entries and
leaves them. For lb_safety that deference needs an entry that really runs it (not one that
only mentions the name) in a group whose matcher covers Bash; install says it did not verify
that entry, rather than claiming the guard works.

THE MCP SERVER IS REGISTERED WITH CLAUDE CODE ITSELF (0.58.0). Claude Code reads MCP servers
from its own list (~/.claude.json, or $CLAUDE_CONFIG_DIR/.claude.json), not from
settings.json, and it rewrites that file constantly. Until 0.58.0 install wrote mcpServers
into settings.json, where Claude Code never looked: the hooks were wired and the server was
not. install now runs `claude mcp add --scope user laserbrain -- <python> -P -m laserbrain
mcp` when `claude` is on PATH, and prints that line when it is not. It reads the list (never
writes it) to see what is already there. uninstall runs `claude mcp remove --scope user
laserbrain` only when the entry is one install registers. An earlier install's
settings.json entry is removed, because nothing reads it.

WINDOWS. The hook commands keep the 0.57.0 `<python> -P -m laserbrain.hooks.<hook>` form,
each interpreter path in double quotes. With no POSIX shell to check that a file exists, a
plain file form would exit 2 when the file is gone (after a pip uninstall, say), and exit 2
refuses every tool call on PreToolUse and every prompt on UserPromptSubmit. A module that
cannot be found exits 1, which lets the call through. Nothing here has run on Windows.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

HOOKS_DIR = Path(os.path.abspath(__file__)).parent / 'hooks'
POSIX = os.name != 'nt'
FALLBACK_PY = 'python3'      # on PATH; lb_safety under -I -S runs on any Python 3
SAFE_FLAG = ' -P' if sys.version_info >= (3, 11) else ''      # for the -m form (the gate)

# (event, hook, matcher). The self-test is lb_safety's SessionStart entry. Ordered as the
# events fire. The merge is keyed per event and per hook, so an older install gains only
# what it lacks.
HOOKS = [
    ('SessionStart',       'lb_safety',   None),
    ('PreToolUse',         'lb_safety',   '*'),
    ('PostToolUse',        'lb_coverage', '*'),
    ('PostToolUseFailure', 'lb_coverage', '*'),
    ('UserPromptSubmit',   'lb_coverage', None),
]
GATE = ('PreToolUse', 'lb_gate', '*')            # only with --with-gate

# ── the commands ────────────────────────────────────────────────────────────────────────
# Each template holds slots for the quoted interpreter and the quoted hook file. They are
# plain concatenation, never format strings: the shell text is full of braces.
_PY, _FILE, _FLAG = 'LBSLOTPY', 'LBSLOTFILE', 'LBSLOTFLAG'
_SLOT = re.compile('LBSLOT(?:PY|FILE|FLAG)')

_SELFTEST_PROBE = (
    # The guarded command is assembled by printf, so this text never holds it whole.
    "O=$(printf '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git reset --ha%s HEAD\"}}' rd"
    ' | "$P" -I -S "$F" 2>/dev/null; echo " rc=$?"); '
    "case \"$O\" in *'\"deny\"'*' rc=2') exit 0;; esac; "
    "printf '%s\\n' '{\"systemMessage\":\"laserbrain: the safety hook did not refuse its test "
    "command, so force pushes, hard resets, recursive deletes, deploys and publishes are NOT "
    "guarded in this session.\",\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\","
    "\"additionalContext\":\"laserbrain: the safety hook is not working in this session. Ask "
    "the user before any force push, hard reset, recursive delete, deploy or publish.\"}}'; exit 0"
)

_POSIX_FORMS = {
    'safety': ('P=' + _PY + '; [ -x "$P" ] || P=' + FALLBACK_PY + '; F=' + _FILE + '; '
               '[ -r "$F" ] || { echo "laserbrain: safety hook file missing: $F" >&2; exit 1; }; '
               'exec "$P" -I -S "$F"'),
    'selftest': ('P=' + _PY + '; [ -x "$P" ] || P=' + FALLBACK_PY + '; F=' + _FILE + '; '
                 + _SELFTEST_PROBE),
    'coverage': ('P=' + _PY + '; F=' + _FILE + '; [ -x "$P" ] && [ -r "$F" ] && '
                 'LASERBRAIN_AGENT=claude "$P" -I -S "$F" lb_coverage; exit 0'),
    'gate': ('P=' + _PY + '; [ -x "$P" ] || exit 0; export LASERBRAIN_AGENT=claude; '
             'exec "$P"' + _FLAG + ' -m laserbrain.hooks.lb_gate'),
}
# Windows: no POSIX shell to rely on, so no self-test and no shell text that might not parse
# there. The module form, as 0.57.0 wrote it, with the interpreter in double quotes: a
# module that is gone exits 1 (the call goes through), where a missing script file would
# exit 2 and refuse every call (see the top of this file).
_NT_FORMS = {
    'safety': _PY + _FLAG + ' -m laserbrain.hooks.lb_safety',
    'coverage': _PY + _FLAG + ' -m laserbrain.hooks.lb_coverage',
    'gate': _PY + _FLAG + ' -m laserbrain.hooks.lb_gate',
}

_EVENTS = {
    'selftest': ('SessionStart',),
    'safety':   ('PreToolUse',),
    'coverage': ('PostToolUse', 'PostToolUseFailure', 'UserPromptSubmit'),
    'gate':     ('PreToolUse',),
}
_HOOK_OF = {'selftest': 'lb_safety', 'safety': 'lb_safety', 'coverage': 'lb_coverage',
            'gate': 'lb_gate'}
_FILE_OF = {'selftest': 'lb_safety.py', 'safety': 'lb_safety.py', 'coverage': 'fast.py',
            'gate': None}


def _kind(event: str, hook: str) -> str:
    if hook == 'lb_safety':
        return 'selftest' if event == 'SessionStart' else 'safety'
    return {'lb_coverage': 'coverage', 'lb_gate': 'gate'}[hook]


def _nt_quote(s: str) -> str:
    return '"' + s + '"'


def command(kind: str, py=None, hooks_dir=None, posix: bool = POSIX):
    """The exact command install writes for `kind`, or None where it writes none."""
    tmpl = (_POSIX_FORMS if posix else _NT_FORMS).get(kind)
    if tmpl is None:
        return None
    q = shlex.quote if posix else _nt_quote
    sep = '/' if posix else '\\'
    py = str(sys.executable if py is None else py)
    hooks = str(HOOKS_DIR if hooks_dir is None else hooks_dir).rstrip('/\\')
    fill = {_PY: q(py), _FLAG: SAFE_FLAG}
    if _FILE in tmpl:
        fill[_FILE] = q(hooks + sep + _FILE_OF[kind])
    return _SLOT.sub(lambda m: fill[m.group(0)], tmpl)


# ── recognising our own entries ─────────────────────────────────────────────────────────
_POSIX_TOKEN = r"(?:'(?:[^']|'\"'\"')*'|[A-Za-z0-9_@%+=:,./-]+)"    # what shlex.quote emits
_NT_TOKEN = r'"[^"]*"'


def _form_rx(tmpl: str, posix: bool):
    tok = _POSIX_TOKEN if posix else _NT_TOKEN
    rx = re.escape(tmpl)
    rx = rx.replace(_PY, f'(?P<py>{tok})').replace(_FILE, f'(?P<file>{tok})')
    rx = rx.replace(_FLAG, '(?: -P)?')
    return re.compile('^' + rx + '$')


_RX = {(k, True): _form_rx(t, True) for k, t in _POSIX_FORMS.items()}
_RX.update({(k, False): _form_rx(t, False) for k, t in _NT_FORMS.items()})
# What install wrote until 0.57.0: `f'{sys.executable} -P -m laserbrain.hooks.<hook>'`, the
# interpreter NOT quoted. So it is one bare token, or an absolute path that may hold spaces
# (a home folder named 'First Last'). Such an entry never ran: sh split the path and exited
# 127, and the call went through unguarded. It must still read as ours, so that install
# rewrites it instead of deferring to it as the user's own. No shell metacharacters and no
# `=` (an env prefix is the user's own wiring) either way, and the last path part has no space.
_LEGACY = re.compile(r'^(?P<py>[^\s;&|<>()$`\'"=]+'
                     r'|(?:/|[A-Za-z]:[\\/])[^;&|<>()$`\'"=\n]*[\\/][^\s;&|<>()$`\'"=\\/]+)'
                     r'(?: -P)? -m laserbrain\.hooks\.(?P<hook>lb_gate|lb_safety|lb_coverage)$')
_LEGACY_EVENTS = {'lb_safety': ('PreToolUse',), 'lb_gate': ('PreToolUse',),
                  'lb_coverage': _EVENTS['coverage']}


def _unquote(tok: str, posix: bool):
    if not posix:
        return tok[1:-1]
    try:
        parts = shlex.split(tok)
    except ValueError:
        return None
    return parts[0] if len(parts) == 1 else None


def _slots_ok(kind: str, m, posix: bool) -> bool:
    py = _unquote(m.group('py'), posix)
    if not py:
        return False
    want = _FILE_OF[kind]
    if not want or m.groupdict().get('file') is None:
        return True
    f = _unquote(m.group('file'), posix)
    if not f:
        return False
    parts = (PurePosixPath if posix else PureWindowsPath)(f).parts
    return tuple(parts[-3:]) == ('laserbrain', 'hooks', want)


def _ours(event: str, h) -> str | None:
    """The kind of hook entry install wrote here, or None for anything else."""
    if not isinstance(h, dict) or h.get('type') != 'command':
        return None
    cmd = h.get('command')
    if not isinstance(cmd, str):
        return None
    for (kind, posix), rx in _RX.items():
        if event in _EVENTS[kind]:
            m = rx.match(cmd)
            if m and _slots_ok(kind, m, posix):
                return kind
    m = _LEGACY.match(cmd)
    if m and event in _LEGACY_EVENTS[m.group('hook')]:
        return _kind(event, m.group('hook'))
    return None


def _mentions(h) -> str | None:
    """Which laserbrain hook an entry names, judged loosely: any mention of its name. For
    reporting only ("kept: ..."); whether install defers to an entry is _runs()."""
    cmd = str(h.get('command', '')) if isinstance(h, dict) else ''
    for name in ('lb_safety', 'lb_coverage', 'lb_gate'):
        if name in cmd:
            return name
    return 'laserbrain' if 'laserbrain' in cmd else None


_COMMENT = re.compile(r'(?:^|\s)#.*$', re.S)
_RUNS = {
    'lb_safety': re.compile(r'lb_safety\.py\b|laserbrain\.hooks\.lb_safety\b'),
    'lb_gate': re.compile(r'lb_gate\.py\b|laserbrain\.hooks\.lb_gate\b'),
    'lb_coverage': re.compile(r'lb_coverage\.py\b|laserbrain\.hooks\.lb_coverage\b'
                              r'|fast\.py\b.*\blb_coverage\b', re.S),
}


def _runs(h, hook: str) -> bool:
    """Does a hook entry the user wrote run `hook`: its file or its module, outside a shell
    comment? A name in a comment or an echo of the word is not wiring."""
    if not isinstance(h, dict) or h.get('type') != 'command':
        return False
    cmd = _COMMENT.sub('', str(h.get('command', '')))
    return bool(_RUNS[hook].search(cmd))


def _covers_bash(matcher) -> bool:
    """Does a PreToolUse group's matcher send Bash calls to its hooks? Claude Code reads an
    absent, empty or '*' matcher as every tool, and otherwise as a tool-name pattern."""
    if matcher is None or matcher in ('', '*'):
        return True
    if not isinstance(matcher, str):
        return False
    try:
        return re.fullmatch(matcher, 'Bash') is not None
    except re.error:
        return matcher == 'Bash'


def _ours_mcp(entry) -> bool:
    """The mcpServers.laserbrain entry install writes, either server."""
    if entry == {'type': 'stdio', 'command': 'laserbrain', 'args': ['mcp']}:
        return True
    if isinstance(entry, dict) and set(entry) == {'type', 'command', 'args'} \
            and entry.get('type') == 'stdio' and entry.get('command') == 'node' \
            and isinstance(entry.get('args'), list) and len(entry['args']) == 1 \
            and isinstance(entry['args'][0], str):
        a = entry['args'][0]
        parts = (PureWindowsPath(a) if '\\' in a else PurePosixPath(a)).parts
        return tuple(parts[-2:]) == ('laserbrain', 'mcp-server.mjs')
    return False


# ── the MCP server, in Claude Code's own list ───────────────────────────────────────────
# See the top of this file. Read here, never written: `claude mcp add|remove` writes it.

ADD = ('mcp', 'add', '--scope', 'user', 'laserbrain', '--')
REMOVE = ('mcp', 'remove', '--scope', 'user', 'laserbrain')
_PY_SERVER_ARGS = (['-P'] if SAFE_FLAG else []) + ['-m', 'laserbrain', 'mcp']


def _claude_json() -> Path:
    d = os.environ.get('CLAUDE_CONFIG_DIR')
    return (Path(d).expanduser() if d else Path.home()) / '.claude.json'


def server_argv(server: str = 'python', py=None) -> list[str]:
    """The command install registers. The offline server runs with the interpreter that ran
    install, like the hooks, so it does not depend on the PATH the agent host starts with."""
    if server == 'node':
        return ['node', str(Path(__file__).with_name('mcp-server.mjs'))]
    return [str(sys.executable if py is None else py)] + _PY_SERVER_ARGS


def _line(args, argv=()) -> str:
    q = shlex.quote if POSIX else (lambda s: _nt_quote(s) if ' ' in s else s)
    return ' '.join(['claude', *args, *(q(x) for x in argv)])


def _registered():
    """('absent' | 'present' | 'unreadable', entry): the laserbrain server in Claude Code's
    user-scope list."""
    p = _claude_json()
    try:
        if not p.exists():
            return 'absent', None
        d = json.loads(p.read_text(encoding='utf-8'))
    except Exception:                                             # noqa: BLE001
        return 'unreadable', None
    m = d.get('mcpServers') if isinstance(d, dict) else None
    if isinstance(m, dict) and 'laserbrain' in m:
        return 'present', m['laserbrain']
    return 'absent', None


def _abs(p: str) -> bool:
    return PurePosixPath(p).is_absolute() or PureWindowsPath(p).is_absolute()


def _ours_registered(entry) -> bool:
    """A Claude Code entry install registers (any interpreter, either server), as `claude
    mcp add` writes it: type stdio, an empty env, nothing else. An entry with an env of its
    own, or any other command, is the user's."""
    if not isinstance(entry, dict) or not set(entry) <= {'type', 'command', 'args', 'env'}:
        return False
    if entry.get('type', 'stdio') != 'stdio' or entry.get('env') not in (None, {}):
        return False
    cmd, args = entry.get('command'), entry.get('args', [])
    if not isinstance(cmd, str) or not isinstance(args, list):
        return False
    if cmd == 'laserbrain' and args == ['mcp']:
        return True
    if args in (['-P', '-m', 'laserbrain', 'mcp'], ['-m', 'laserbrain', 'mcp']):
        return _abs(cmd)
    return _ours_mcp({'type': 'stdio', 'command': cmd, 'args': args})


def _claude(args, argv=()):
    """Run Claude Code's own command: (exit code, output), or None when it is not on PATH."""
    exe = shutil.which('claude')
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *args, *argv], capture_output=True, text=True, timeout=120)
    except Exception as e:                                        # noqa: BLE001
        return 1, f'{type(e).__name__}: {e}'
    return r.returncode, (r.stdout + r.stderr).strip()


def _register(argv, dry_run: bool, done: list, todo: list, notes: list) -> None:
    """Register the server at user scope, or say exactly how to."""
    state, entry = _registered()
    replace = False
    if state == 'unreadable':
        todo.append(f'{_claude_json()} could not be read, so the MCP server was not '
                    f'registered. Register it with:\n    {_line(ADD, argv)}')
        return
    if state == 'present':
        if isinstance(entry, dict) and entry.get('command') == argv[0] \
                and entry.get('args', []) == argv[1:] and _ours_registered(entry):
            return                                                # already as install would
        if not _ours_registered(entry):
            notes.append('Claude Code already lists an MCP server named laserbrain that '
                         'install did not register; kept as it is')
            return
        replace = True                                            # an earlier or moved install
    label = 'Claude Code MCP server laserbrain' + (' updated' if replace else '')
    if not shutil.which('claude'):
        todo.append('`claude` is not on PATH, so the MCP server is not registered yet. '
                    f'Register it with:\n    {_line(ADD, argv)}'
                    + (f'\n  (after `{_line(REMOVE)}`)' if replace else ''))
        return
    if dry_run:
        done.append(label)
        return
    if replace:
        rc, out = _claude(REMOVE)
        if rc != 0:
            todo.append(f'`{_line(REMOVE)}` failed: {out[-200:]}')
            return
    rc, out = _claude(ADD, argv)
    if rc == 0:
        done.append(label)
    else:
        todo.append(f'`claude mcp add` failed: {out[-200:]}\n  Register it with:\n    '
                    f'{_line(ADD, argv)}')


# ── settings.json ───────────────────────────────────────────────────────────────────────

class _Malformed(Exception):
    pass


def _settings_path(host: str) -> Path:
    return Path.home() / '.claude' / 'settings.json'


def _load(path: Path):
    if not path.exists():
        return {}, None
    try:
        cfg = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None, f'  {path} is not valid JSON. Fix or move it first; refusing to overwrite.'
    if not isinstance(cfg, dict):
        return None, f'  {path} is not a JSON object. Fix or move it first; refusing to overwrite.'
    return cfg, None


def _save(path: Path, cfg: dict, backup_suffix: str):
    """Back up, then replace in one step: a crash mid-write cannot leave half a file. A
    symlinked settings.json (a dotfiles repo) is written through, not replaced."""
    backup = None
    newline = True                   # a new file ends with one; an existing one keeps its own
    if path.exists():
        backup = Path(str(path) + backup_suffix)
        shutil.copy2(path, backup)
        newline = path.read_bytes().endswith(b'\n')
    real = path.resolve() if path.is_symlink() else path
    real.parent.mkdir(parents=True, exist_ok=True)
    tmp = real.with_name(f'.{real.name}.laserbrain-{os.getpid()}.tmp')
    try:
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + ('\n' if newline else ''),
                       encoding='utf-8')
        if real.exists():
            shutil.copymode(real, tmp)
        os.replace(tmp, real)
    finally:
        if tmp.exists():
            tmp.unlink()
    return backup


def _groups(hooks: dict, event: str, create: bool = False):
    groups = hooks.setdefault(event, []) if create else hooks.get(event)
    if groups is not None and not isinstance(groups, list):
        raise _Malformed(f'hooks.{event} is not a list')
    return groups


def _remove(hooks: dict, event: str, pred) -> list:
    """Drop every hook entry under `event` for which pred(entry) holds. A group this empties
    goes, and so does an event this empties; nothing else moves."""
    groups = _groups(hooks, event)
    if not groups:
        return []
    gone, kept_groups = [], []
    for g in groups:
        hs = g.get('hooks') if isinstance(g, dict) else None
        if not isinstance(hs, list):
            kept_groups.append(g)
            continue
        flags = [bool(pred(h)) for h in hs]
        if not any(flags):
            kept_groups.append(g)
            continue
        gone += [h for h, f in zip(hs, flags) if f]
        left = [h for h, f in zip(hs, flags) if not f]
        if left:
            g['hooks'] = left
            kept_groups.append(g)
    if gone:
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    return gone


def _wire(hooks: dict, event: str, hook: str, matcher, kind: str, want: str,
          changed: list, notes: list) -> bool:
    """Wire `kind` on `event`. False when an entry the user wrote already runs the hook, so
    install deferred to it and wrote nothing (and so verified nothing) for it."""
    groups = _groups(hooks, event, create=True)
    ours, theirs = [], False
    for g in groups:
        hs = g.get('hooks') if isinstance(g, dict) else None
        for h in hs if isinstance(hs, list) else []:
            k = _ours(event, h)
            if k == kind:
                ours.append(h)
            elif k is None and _runs(h, hook):
                # The guard only counts as wired when its group really sends Bash to it.
                if kind != 'safety' or _covers_bash(g.get('matcher')):
                    theirs = True
    if not ours:
        if theirs:
            notes.append(f'{event}/{hook}: already wired by an entry install did not write; '
                         'kept as it is, not doubled')
            return False
        entry = {'matcher': matcher} if matcher else {}
        entry['hooks'] = [{'type': 'command', 'command': want}]
        groups.append(entry)
        changed.append(f'{event}/{hook}')
        return True
    first = ours[0]
    if first.get('command') != want:        # an earlier version's shape, or a moved install
        first['command'] = want
        changed.append(f'{event}/{hook} updated')
    extra = ours[1:]
    if extra:
        _remove(hooks, event, lambda h: any(h is x for x in extra))
        changed.append(f'{event}/{hook} duplicate removed')
    return True


def _verify(with_gate: bool = False, py=None, skip=()) -> list[str]:
    """Prove the wired commands do their jobs. Correct wiring and broken hooks look
    identical from outside, which is how they were shipped broken once already.

    These are the commands install writes, so a kind in `skip` (install deferred to the
    user's own entry and wrote none) is not tested: install does not run the user's own
    commands, and the caller says those are unverified instead."""
    py = str(py or sys.executable)
    env = {k: v for k, v in os.environ.items() if k != 'LASERBRAIN_SAFETY_OFF'}

    def run(kind, stdin):
        c = command(kind, py)
        args = ['/bin/sh', '-c', c] if POSIX else c
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=60,
                              env=env, shell=not POSIX)

    def probe(cmd):
        return json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd},
                           'session_id': 'install-check'})

    bad = []
    try:
        if 'safety' not in skip:
            r = run('safety', probe('git reset --ha' + 'rd HEAD'))      # never spelled whole
            if not (r.returncode == 2 and '"deny"' in r.stdout):
                bad.append(f'lb_safety: did not refuse its test command (exit {r.returncode}) '
                           f'{(r.stdout + r.stderr).strip()[:100]}')
            r = run('safety', probe('echo hi'))
            if r.returncode != 0 or r.stdout.strip():
                bad.append(f'lb_safety: refused an ordinary command (exit {r.returncode})')
        if POSIX and 'selftest' not in skip:
            r = run('selftest', '')
            if r.returncode != 0 or r.stdout.strip():
                bad.append('SessionStart self-test: it printed its warning')
        code = ('import importlib, importlib.util, sys\n'
                "spec = importlib.util.spec_from_file_location('lb_fast_check', sys.argv[1])\n"
                'm = importlib.util.module_from_spec(spec)\n'
                'spec.loader.exec_module(m)\n'
                'm._bare_package()\n'
                "importlib.import_module('laserbrain.hooks.lb_coverage')\n"
                "print('ok')\n")
        if 'coverage' not in skip:
            r = subprocess.run([py, '-I', '-S', '-c', code, str(HOOKS_DIR / 'fast.py')],
                               capture_output=True, text=True, timeout=60, env=env)
            if r.returncode != 0 or r.stdout.strip() != 'ok':
                bad.append(f'lb_coverage: does not load through fast.py '
                           f'{(r.stdout + r.stderr).strip()[-100:]}')
        if with_gate and 'gate' not in skip:
            r = run('gate', probe('echo hi'))
            noise = (r.stdout + r.stderr).lower()
            if 'traceback' in noise or 'unavailable' in noise:
                bad.append(f'lb_gate: {(r.stdout + r.stderr).strip()[:100]}')
    except Exception as e:                                        # noqa: BLE001
        bad.append(f'{type(e).__name__}: {e}')
    return bad


# ── install ─────────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog='laserbrain install',
        description='Wire laserbrain into Claude Code: lb_safety and lb_coverage as hooks in '
                    '~/.claude/settings.json, and the MCP server in Claude Code\'s own list '
                    '(through `claude mcp add --scope user`, or the line to run when `claude` '
                    'is not on PATH). Safe to run again; `laserbrain uninstall` undoes it.')
    ap.add_argument('--host', default='claude', choices=['claude'],
                    help='agent host to wire (only Claude Code today)')
    ap.add_argument('--dry-run', action='store_true', help='print what would change; write nothing')
    ap.add_argument('--server', choices=['python', 'node'], default='python',
                    help="which stdio server to register. Both list the 3-tool core "
                         "(check_state, reset_task, get_history) by default, and "
                         "LASERBRAIN_TOOLS=all lists the rest. 'python' (default) is "
                         "offline: no network, no key. 'node' holds six more tools that reach "
                         "a hosted service, and needs node on PATH.")
    ap.add_argument('--no-hooks', action='store_true',
                    help='MCP server only: the detector without the enforcement')
    ap.add_argument('--with-gate', action='store_true',
                    help='also wire lb_gate on PreToolUse (off by default since 0.58.0)')
    a = ap.parse_args(argv)

    path = _settings_path(a.host)
    cfg, err = _load(path)
    if err:
        print(err)
        return 1

    changed, notes = [], []            # changed: settings.json
    mcp_done, mcp_todo = [], []        # the MCP server, in Claude Code's own list
    mcp = cfg.get('mcpServers')
    if mcp is not None and not isinstance(mcp, dict):
        print(f'  {path}: mcpServers is not an object. Fix it first; refusing to overwrite.')
        return 1
    # An earlier install wrote the server here, where Claude Code never reads it. It goes,
    # so the file does not claim a server that is not wired.
    if isinstance(mcp, dict) and _ours_mcp(mcp.get('laserbrain')):
        del mcp['laserbrain']
        if not mcp:
            del cfg['mcpServers']
        changed.append('mcpServers.laserbrain removed (Claude Code does not read servers here)')

    # THE OFFLINE SERVER IS THE DEFAULT, AND STAYS THE DEFAULT.
    #
    # The wheel also ships mcp-server.mjs. Since 0.58.0 it lists the 3-tool core by default,
    # as `laserbrain mcp` does, but it holds six tools that reach a hosted service
    # (ask_alice, analyze_language, compare_phrasings, remember_self, resume_self,
    # forget_self), and with LASERBRAIN_TOOLS=all it lists them. SECURITY.md says the hosted
    # endpoint is "opt-in and separate", and an installer that silently wired the server
    # that carries them would make that false for everyone who ran it without reading this.
    #
    # So: --server node opts in, and the line printed afterwards says the option exists.
    # A default that quietly widens what leaves the machine is not a default anyone chose.
    argv_server = server_argv(a.server)
    if a.server == 'node' and not shutil.which('node'):
        print('  --server node needs node on PATH; not registering a server')
        argv_server = None
    elif a.server == 'node' and not Path(argv_server[1]).exists():
        print('  --server node: mcp-server.mjs is not in this install; not registering')
        argv_server = None
    if argv_server:
        _register(argv_server, a.dry_run, mcp_done, mcp_todo, notes)

    deferred = set()
    if not a.no_hooks:
        missing = [f for f in ('lb_safety.py', 'fast.py') if not (HOOKS_DIR / f).is_file()]
        if missing:
            print(f'  this install has no {", ".join(missing)} under {HOOKS_DIR}; '
                  'not wiring hooks. Tell us rather than working around it.')
            return 1
        try:
            had_hooks = 'hooks' in cfg
            hooks = cfg.setdefault('hooks', {})
            if not isinstance(hooks, dict):
                raise _Malformed('hooks is not an object')
            events_before = set(hooks)
            for event, hook, matcher in HOOKS + ([GATE] if a.with_gate else []):
                kind = _kind(event, hook)
                want = command(kind)
                if want is not None and not _wire(hooks, event, hook, matcher, kind, want,
                                                  changed, notes):
                    deferred.add(kind)
            if not a.with_gate:
                for _ in _remove(hooks, 'PreToolUse', lambda h: _ours('PreToolUse', h) == 'gate'):
                    changed.append('PreToolUse/lb_gate removed')
                    notes.append('lb_gate is no longer wired by default; '
                                 '`laserbrain install --with-gate` puts it back')
                for g in _groups(hooks, 'PreToolUse') or []:
                    for h in (g.get('hooks') if isinstance(g, dict) else None) or []:
                        if _ours('PreToolUse', h) is None and _mentions(h) == 'lb_gate':
                            notes.append('PreToolUse/lb_gate: wired by an entry install did '
                                         'not write; kept as it is')
            for event in [e for e, gs in hooks.items() if gs == [] and e not in events_before]:
                del hooks[event]          # created here, then nothing went in
            if not hooks and not had_hooks:
                del cfg['hooks']
        except _Malformed as e:
            print(f'  {path}: {e}. Fix it first; refusing to overwrite.')
            return 1

    if a.dry_run:
        print('  would change: ' + (', '.join(changed + mcp_done) if changed + mcp_done
                                    else 'nothing'))
        for n in dict.fromkeys(notes):
            print(f'  note: {n}')
        for t in mcp_todo:
            print(f'  {t}')
        return 0

    if changed:
        backup = _save(path, cfg, '.before-laserbrain')
        print(f'  wired: {", ".join(changed)}')
        if backup:
            print(f'  previous settings saved as {backup.name}')
    if mcp_done:
        print(f'  registered with `claude mcp add --scope user`: {", ".join(mcp_done)}')
    if not changed and not mcp_done:
        print('  already wired — nothing changed')
    for n in dict.fromkeys(notes):
        print(f'  note: {n}')
    for t in mcp_todo:
        print(f'  {t}')

    if not a.no_hooks:
        bad = _verify(with_gate=a.with_gate, skip=deferred)
        if bad:
            print('\n  HOOKS ARE WIRED BUT NOT HEALTHY:')
            for b in bad:
                print(f'    {b}')
            print('  Tell us rather than working around it.')
            return 1
        said = []
        if 'safety' not in deferred:
            said.append('lb_safety refuses its test command and lets an ordinary one through')
        if POSIX and 'selftest' not in deferred:
            said.append('the SessionStart self-test is silent')
        if 'coverage' not in deferred:
            said.append('lb_coverage loads')
        if a.with_gate and 'gate' not in deferred:
            said.append('lb_gate runs')
        if said:
            print('  hooks verified: ' + '; '.join(said))
        if 'safety' in deferred:
            print('  lb_safety: wired by your own entry, not verified by install. Check that '
                  'it refuses a guarded command.')
        if os.environ.get('LASERBRAIN_SAFETY_OFF'):
            print('  note: LASERBRAIN_SAFETY_OFF is set in this shell, so an agent started '
                  'from it runs with lb_safety switched off')

    # Say the other server exists, rather than leaving it to be found. Not wiring it by
    # default is a decision about what leaves the machine; hiding it would be a different
    # decision, about what the user gets to know.
    if a.server != 'node' and shutil.which('node') and Path(__file__).with_name('mcp-server.mjs').exists():
        print('\n  node is available: `laserbrain install --server node` registers the node server.')
        print('  It holds six tools that reach the hosted endpoint, which is why it is not the default.')

    print('\n  restart your agent, then:  laserbrain coverage')
    print('  to undo:  laserbrain uninstall')
    return 0


# ── uninstall ───────────────────────────────────────────────────────────────────────────

def uninstall(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog='laserbrain uninstall',
        description='Remove the hook and MCP server entries `laserbrain install` writes, and '
                    'nothing else. Entries you wrote yourself are listed and left alone. '
                    'Your readings and config are kept.')
    ap.add_argument('--host', default='claude', choices=['claude'])
    ap.add_argument('--dry-run', action='store_true', help='print what would be removed; write nothing')
    a = ap.parse_args(argv)

    path = _settings_path(a.host)
    cfg, err = _load(path)            # no file reads as {}, and nothing is created
    if err:
        print(err)
        return 1

    removed, kept = [], []
    hooks = cfg.get('hooks')
    if isinstance(hooks, dict):
        for event in list(hooks):
            groups = hooks[event]
            if not isinstance(groups, list):
                continue
            for g in groups:
                for h in (g.get('hooks') if isinstance(g, dict) else None) or []:
                    k = _ours(event, h)
                    if k:
                        removed.append(f'{event}/{_HOOK_OF[k]}')
                    elif _mentions(h):
                        kept.append(f'{event}/{_mentions(h)} (an entry install did not write)')
            _remove(hooks, event, lambda h, e=event: _ours(e, h) is not None)
        if not hooks and removed:
            del cfg['hooks']
    mcp = cfg.get('mcpServers')
    if isinstance(mcp, dict) and 'laserbrain' in mcp:
        if _ours_mcp(mcp['laserbrain']):
            del mcp['laserbrain']
            removed.append('mcpServers.laserbrain')
            if not mcp:
                del cfg['mcpServers']
        else:
            kept.append('mcpServers.laserbrain (not the entry install writes)')
    settings_removed = list(removed)

    # The server in Claude Code's own list: only the entry install registers.
    state, entry = _registered()
    unregister = state == 'present' and _ours_registered(entry)
    if unregister:
        removed.append('Claude Code MCP server laserbrain')
    elif state == 'present':
        kept.append('Claude Code MCP server laserbrain (not the entry install registers)')

    if a.dry_run:
        print('  would remove: ' + (', '.join(removed) if removed else 'nothing'))
        for k in kept:
            print(f'  would keep: {k}')
        return 0
    if not removed:
        where = path if path.exists() else f'{path} (no such file)'
        print(f'  nothing to remove: no entry laserbrain install writes is in {where}')
        for k in kept:
            print(f'  kept: {k}')
        return 0
    backup = _save(path, cfg, '.before-laserbrain-uninstall') if settings_removed else None
    rc = 0
    if unregister:
        res = _claude(REMOVE)
        if res is None:
            removed.remove('Claude Code MCP server laserbrain')
            print(f'  `claude` is not on PATH. Remove the MCP server with:\n    {_line(REMOVE)}')
        elif res[0] != 0:
            removed.remove('Claude Code MCP server laserbrain')
            print(f'  `{_line(REMOVE)}` failed: {res[1][-200:]}')
            rc = 1
    if removed:
        print(f'  removed: {", ".join(removed)}')
    for k in kept:
        print(f'  kept: {k}')
    if backup:
        print(f'  previous settings saved as {backup.name}')
    print('  restart your agent. Readings and config under the laserbrain state folders are kept.')
    return rc
