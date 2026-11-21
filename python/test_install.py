#!/usr/bin/env python3
"""test_install.py — `laserbrain install` and `laserbrain uninstall` on synthetic settings (0.58.0).

    python3 test_install.py

WHAT IS PINNED. Every case runs the real command, `python3 -m laserbrain install|uninstall`,
as a subprocess with HOME in a temp dir, on a settings.json written here. Nothing outside the
temp dirs is read or written, and every path and command in the fixtures is made up.

  1  a fresh install wires exactly five entries: the SessionStart self-test, lb_safety alone
     on PreToolUse, lb_coverage through hooks/fast.py on PostToolUse, PostToolUseFailure and
     UserPromptSubmit. No lb_gate, no `-m` form, no LASERBRAIN_* value but LASERBRAIN_AGENT,
     and no path but this interpreter and this install's hooks folder
  2  the commands are exactly the shapes test_safety_wiring.py proves, so its checks
     (missing file exits 1, missing interpreter falls back, -I -S isolation, self-test)
     cover what install writes
  3  the wired commands work: lb_safety refuses a guarded command and lets `ls` through, the
     self-test is silent, lb_coverage writes its session file
  4  idempotent: a second run changes nothing, byte for byte
  5  it merges: other keys, other hooks in the same events and other MCP servers are kept as
     they were, and uninstall then hands back the original file byte for byte
  6  an install made by 0.57.0 (`<python> -P -m laserbrain.hooks.<hook>`) is brought to the
     new shape in place; its lb_gate entry is removed, and kept with --with-gate
  7  hand-written wiring that runs the same hooks another way is left exactly as it is, not
     doubled, and uninstall leaves it too (and says so)
  8  a moved install (other interpreter, other hooks folder, same shape) is updated in place
  9  --with-gate wires lb_gate in its own group; uninstall removes it
 10  uninstall: --dry-run writes nothing; no settings file is not an error and creates none;
     an edited copy of an install entry is kept
 11  a broken or non-object settings.json is refused by both commands, unchanged
 12  --no-hooks; a symlinked settings.json is written through, not replaced
 13  recognising entries: the Windows forms, and lookalikes that must not count as ours
 14  the CLI hands both commands to install.py's own parsers
 15  install.py holds no path, name or setting from the machine it was written on
 16  the MCP server goes into Claude Code's own list through `claude mcp add --scope user`
     (a stand-in `claude` on PATH records the calls), never into settings.json; with no
     `claude` on PATH install prints the line to run; an earlier install's settings.json
     entry is removed; uninstall runs `claude mcp remove` only for the entry install registers
 17  0.57.0 entries whose interpreter path holds a space read as ours and are rewritten
 18  install defers to the user's lb_safety only when it really runs it on Bash, and then
     says it did not verify it

THIS TEST CAN FAIL: wire lb_gate by default, or lb_safety through `-m`, and 1 goes red; drop
a check from _ours and 5 or 7 go red (uninstall removes too much or install doubles); make
uninstall match on hook names and 7 and 10 go red; write mcpServers into settings.json again
and 1 and 16 go red; defer to any entry that mentions lb_safety and 18 goes red.

Guarded phrases are assembled by concatenation so this file never holds one whole
(lb_safety reads the shell text).
"""
import importlib.util
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
PKG = ROOT / 'laserbrain'
HOOKS = PKG / 'hooks'
PY = sys.executable
FLAGS = ['-P'] if sys.version_info >= (3, 11) else []
GUARDED = 'git push --' + 'force origin main'
ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and bool(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# install.py imports only the standard library, so it loads from its file: this copy's code,
# without the package __init__.
ins = _load('lb_install_under_test', PKG / 'install.py')
tsw = _load('lb_safety_wiring_shapes', ROOT / 'test_safety_wiring.py')


class Home:
    """One scratch HOME, state dir and settings.json."""

    def __init__(self, claude=False):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix='lb-install-'))
        self.bin = None
        if claude:
            self.bin = self.dir / 'fakebin'
            self.bin.mkdir()
            exe = self.bin / 'claude'
            exe.write_text(f'#!{PY} -I -S\n' + FAKE_CLAUDE)
            exe.chmod(0o755)
        self.state = self.dir / 'state'
        self.state.mkdir()
        for off in ('askllm-watch.off', 'turnwatch.off'):
            (self.state / off).write_text('')
        self.settings = self.dir / '.claude' / 'settings.json'

    def env(self):
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(('LASERBRAIN', 'CLAUDE', 'ANTHROPIC', 'PYTHON'))}
        e.update(HOME=str(self.dir), PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1',
                 PATH=(f'{self.bin}:' if self.bin else '') + '/usr/bin:/bin',
                 LASERBRAIN_STATE_DIR=str(self.state),
                 LASERBRAIN_HOME=str(self.dir / 'lbhome'), LASERBRAIN_ASKLLM_WATCH='off',
                 LASERBRAIN_ASKLLM_MODE='off', LASERBRAIN_TURNWATCH='off',
                 LASERBRAIN_TURNS_HARVEST='0', LASERBRAIN_API='http://127.0.0.1:9',
                 LASERBRAIN_HUB='http://127.0.0.1:9')
        return e

    def write(self, cfg):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')

    def read(self):
        return json.loads(self.settings.read_text(encoding='utf-8'))

    def raw(self):
        return self.settings.read_bytes() if self.settings.exists() else None

    def run(self, *args):
        return subprocess.run([PY, *FLAGS, '-m', 'laserbrain', *args], cwd=str(self.dir),
                              env=self.env(), capture_output=True, text=True, timeout=180)

    def sh(self, cmd, stdin=''):
        return subprocess.run(['/bin/sh', '-c', cmd], input=stdin, cwd=str(self.dir),
                              env=self.env(), capture_output=True, text=True, timeout=60)

    def claude_json(self):
        p = self.dir / '.claude.json'
        return json.loads(p.read_text()) if p.exists() else None

    def calls(self):
        p = self.dir / 'claude-calls.log'
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


# A stand-in for Claude Code's `claude mcp add|remove --scope user`: it records each call and
# keeps ~/.claude.json the way the real command does (checked against Claude Code 2.1: an
# entry is {type, command, args, env: {}}; adding a name that exists, or removing one that
# does not, exits 1).
FAKE_CLAUDE = '''
import json, os, sys
home = os.environ['HOME']
p = os.path.join(os.environ.get('CLAUDE_CONFIG_DIR') or home, '.claude.json')
with open(os.path.join(home, 'claude-calls.log'), 'a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
try:
    d = json.load(open(p))
except FileNotFoundError:
    d = {}
a = sys.argv[1:]
m = d.setdefault('mcpServers', {})
if a[:6] == ['mcp', 'add', '--scope', 'user', 'laserbrain', '--']:
    if 'laserbrain' in m:
        print('MCP server laserbrain already exists in user config')
        sys.exit(1)
    m['laserbrain'] = {'type': 'stdio', 'command': a[6], 'args': a[7:], 'env': {}}
elif a == ['mcp', 'remove', '--scope', 'user', 'laserbrain']:
    if 'laserbrain' not in m:
        print('No MCP server named "laserbrain" in user scope')
        sys.exit(1)
    del m['laserbrain']
else:
    sys.exit(3)
json.dump(d, open(p, 'w'))
print('ok')
'''


def would(out, word='would change'):
    for ln in out.splitlines():
        if f'{word}:' in ln:
            rest = ln.split(f'{word}:', 1)[1].strip()
            return [] if rest == 'nothing' else [x.strip() for x in rest.split(',')]
    return None


def commands(cfg, event):
    return [h.get('command') for g in (cfg.get('hooks') or {}).get(event) or []
            for h in g.get('hooks') or []]


def pre_tool(tool, tool_input):
    return json.dumps({'session_id': 'install-test', 'hook_event_name': 'PreToolUse',
                       'tool_name': tool, 'tool_input': tool_input, 'cwd': '/'})


def denied(r):
    try:
        h = json.loads(r.stdout).get('hookSpecificOutput') or {}
    except Exception:
        return False
    return r.returncode == 2 and h.get('permissionDecision') == 'deny'


SAFETY = ins.command('safety', PY, HOOKS)
SELFTEST = ins.command('selftest', PY, HOOKS)
COVERAGE = ins.command('coverage', PY, HOOKS)
GATE = ins.command('gate', PY, HOOKS)
LEGACY = {m: f'{PY} -P -m laserbrain.hooks.{m}' for m in ('lb_gate', 'lb_safety', 'lb_coverage')}
EVENTS = ['SessionStart', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'UserPromptSubmit']
MCP = {'type': 'stdio', 'command': 'laserbrain', 'args': ['mcp']}      # 0.57.0's settings.json entry
SERVER = [PY] + FLAGS + ['-m', 'laserbrain', 'mcp']
ADD = ['mcp', 'add', '--scope', 'user', 'laserbrain', '--']
REMOVE = ['mcp', 'remove', '--scope', 'user', 'laserbrain']
ADD_LINE = 'claude mcp add --scope user laserbrain -- ' + ' '.join(shlex.quote(x) for x in SERVER)


def legacy_shape():
    """What 0.57.0's install wrote, in its order and key order (hooks before matcher)."""
    return {
        'mcpServers': {'laserbrain': dict(MCP)},
        'hooks': {
            'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': LEGACY['lb_coverage']}]}],
            'PostToolUse': [{'hooks': [{'type': 'command', 'command': LEGACY['lb_coverage']}], 'matcher': '*'}],
            'PostToolUseFailure': [{'hooks': [{'type': 'command', 'command': LEGACY['lb_coverage']}], 'matcher': '*'}],
            'PreToolUse': [{'hooks': [{'type': 'command', 'command': LEGACY['lb_gate']}], 'matcher': '*'},
                           {'hooks': [{'type': 'command', 'command': LEGACY['lb_safety']}], 'matcher': '*'}],
            'Stop': [{'hooks': [{'type': 'command', 'command': 'echo stopped'}]}],
        }}


def hand_shape():
    """Hand-written wiring that runs the same hooks in another way (made-up paths)."""
    p, d = '/opt/example/bin/python3', '/opt/example/src/laserbrain/python/laserbrain/hooks'
    cov = (f'P={p}; F={d}/fast.py; [ -x "$P" ] && [ -r "$F" ] && LASERBRAIN_AGENT=claude '
           f'LASERBRAIN_TURNWATCH_TRIGGER=first_tool "$P" -I -S "$F" lb_coverage; exit 0')
    return {'hooks': {
        'SessionStart': [{'hooks': [{'type': 'command', 'command': tsw.selftest_command(p, d, who='the owner')}]}],
        'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': tsw.safety_command(p, d)}]}],
        'PostToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': cov}]}],
        'PostToolUseFailure': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': cov}]}],
        'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': cov}]}],
    }}


def main():
    if not (HOOKS / 'lb_safety.py').is_file() or not (HOOKS / 'fast.py').is_file():
        show('the hooks this install wires exist', False, str(HOOKS))
        return 1

    print('\n  1. a fresh install: five entries, the measured shape, nothing machine-specific')
    h = Home()
    try:
        r = h.run('install')
        show('install exits 0 and verifies the hooks', r.returncode == 0 and 'hooks verified' in r.stdout,
             (r.returncode, r.stdout[-400:], r.stderr[-400:]))
        cfg = h.read()
        hooks = cfg.get('hooks') or {}
        show('exactly the five events', sorted(hooks) == sorted(EVENTS), sorted(hooks))
        show('one group with one command on each',
             all(len(hooks[e]) == 1 and len(hooks[e][0]['hooks']) == 1 for e in EVENTS if e in hooks))
        show('PreToolUse: lb_safety alone, as its own file', commands(cfg, 'PreToolUse') == [SAFETY],
             commands(cfg, 'PreToolUse'))
        show('SessionStart: the lb_safety self-test', commands(cfg, 'SessionStart') == [SELFTEST])
        show('PostToolUse, PostToolUseFailure, UserPromptSubmit: lb_coverage through fast.py',
             all(commands(cfg, e) == [COVERAGE] for e in EVENTS[2:]))
        show('matchers: * on the tool events, none on SessionStart and UserPromptSubmit',
             [hooks[e][0].get('matcher') for e in EVENTS] == [None, '*', '*', '*', None],
             [hooks[e][0].get('matcher') for e in EVENTS])
        text = json.dumps(hooks)
        show('lb_gate is not wired', 'lb_gate' not in text)
        show('no `-m laserbrain` form', '-m laserbrain' not in text)
        show('the only LASERBRAIN_* value is LASERBRAIN_AGENT=claude',
             set(re.findall(r'LASERBRAIN_\w+', text)) == {'LASERBRAIN_AGENT'}
             and 'LASERBRAIN_AGENT=claude' in text, set(re.findall(r'LASERBRAIN_\w+', text)))
        bare = []
        for c in commands(cfg, 'SessionStart') + commands(cfg, 'PreToolUse') + commands(cfg, 'PostToolUse'):
            c = c.replace(shlex.quote(PY), 'PY')
            for f in ('lb_safety.py', 'fast.py'):
                c = c.replace(shlex.quote(f'{HOOKS}/{f}'), 'FILE')
            bare.append(c.replace('/dev/null', ''))
        show('no path but this interpreter and this install\'s hooks folder',
             not any('/' in c for c in bare), [c for c in bare if '/' in c])
        show('no MCP server in settings.json (Claude Code does not read servers there)', 'mcpServers' not in cfg)
        show('with no `claude` on PATH, it prints the line that registers the offline server',
             ADD_LINE in r.stdout and 'not on PATH' in r.stdout, r.stdout[-400:])
        show('no backup when there was no file before', not (h.settings.parent / 'settings.json.before-laserbrain').exists())

        print('\n  2. the same shapes test_safety_wiring.py proves')
        show('PreToolUse command == test_safety_wiring.safety_command(fallback python3)',
             SAFETY == tsw.safety_command(PY, HOOKS, fallback='python3'), SAFETY)
        show('SessionStart command == test_safety_wiring.selftest_command(fallback python3)',
             SELFTEST == tsw.selftest_command(PY, HOOKS, fallback='python3', who='the user'), SELFTEST)

        print('\n  3. the wired commands work')
        safety = commands(cfg, 'PreToolUse')[0]
        r = h.sh(safety, pre_tool('Bash', {'command': GUARDED}))
        show('lb_safety refuses a guarded command (exit 2, deny)', denied(r), (r.returncode, r.stdout[:200]))
        r = h.sh(safety, pre_tool('Bash', {'command': 'ls -la'}))
        show('lb_safety lets ls through silently', r.returncode == 0 and not r.stdout.strip(), (r.returncode, r.stdout[:200]))
        r = h.sh(safety, pre_tool('Read', {'file_path': '/etc/hosts'}))
        show('a non-shell tool: exit 0', r.returncode == 0 and not r.stdout.strip(), r.returncode)
        r = h.sh(commands(cfg, 'SessionStart')[0])
        show('the self-test is silent when lb_safety is healthy', r.returncode == 0 and not r.stdout.strip(),
             (r.returncode, r.stdout[:200]))
        ev = {'session_id': 'install-cov', 'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
              'tool_input': {'command': 'make t'}, 'tool_use_id': 'toolu_i1', 'cwd': str(h.dir),
              'tool_response': {'stdout': 'x', 'stderr': '', 'exit_code': 0}}
        r = h.sh(commands(cfg, 'PostToolUse')[0], json.dumps(ev))
        show('lb_coverage runs through fast.py and writes its session file',
             r.returncode == 0 and (h.state / 'install-cov.json').exists(),
             (r.returncode, r.stderr[-200:], sorted(p.name for p in h.state.iterdir())))

        print('\n  4. idempotent')
        before = h.raw()
        r = h.run('install', '--dry-run')
        show('dry run: would change nothing', would(r.stdout) == [], r.stdout[-300:])
        r = h.run('install')
        show('second run: nothing changed, byte for byte',
             r.returncode == 0 and 'nothing changed' in r.stdout and h.raw() == before, r.stdout[-300:])
    finally:
        h.close()

    print('\n  5. merging with settings that hold other things, and uninstall hands them back')
    h = Home()
    try:
        orig = {
            'theme': 'dark',
            'permissions': {'allow': ['Bash(ls:*)'], 'deny': []},
            'statusLine': {'type': 'command', 'command': 'echo "räksmörgås ✓"'},
            'env': {'EXAMPLE_FLAG': '1'},
            'mcpServers': {'other': {'type': 'stdio', 'command': 'other-server', 'args': []}},
            'hooks': {
                'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'my-own-guard.sh'}]}],
                'PostToolUse': [{'matcher': 'Edit', 'hooks': [{'type': 'command', 'command': 'prettier --write'},
                                                              {'type': 'command', 'command': 'echo edited'}]}],
                'Stop': [{'hooks': [{'type': 'command', 'command': 'say done'}]}],
            }}
        h.write(orig)
        raw0 = h.raw()
        r = h.run('install')
        cfg = h.read()
        show('install exits 0', r.returncode == 0, (r.stdout[-300:], r.stderr[-300:]))
        show('other top-level keys untouched',
             all(cfg.get(k) == orig[k] for k in ('theme', 'permissions', 'statusLine', 'env')))
        show('the other MCP server is kept', cfg['mcpServers'].get('other') == orig['mcpServers']['other'])
        show('existing hook groups are kept, in place, first',
             all(cfg['hooks'][e][:len(orig['hooks'][e])] == orig['hooks'][e] for e in orig['hooks']),
             {e: cfg['hooks'][e] for e in orig['hooks']})
        show('laserbrain entries are added beside them',
             SAFETY in commands(cfg, 'PreToolUse') and COVERAGE in commands(cfg, 'PostToolUse'))
        show('the backup holds the original bytes',
             (h.settings.parent / 'settings.json.before-laserbrain').read_bytes() == raw0)
        r = h.run('uninstall', '--dry-run')
        show('uninstall --dry-run lists exactly the five entries install wrote',
             sorted(would(r.stdout, 'would remove') or []) == sorted(
                 ['SessionStart/lb_safety', 'PreToolUse/lb_safety',
                  'PostToolUse/lb_coverage', 'PostToolUseFailure/lb_coverage', 'UserPromptSubmit/lb_coverage']),
             r.stdout[-400:])
        show('  and writes nothing', h.read() == cfg)
        r = h.run('uninstall')
        show('uninstall exits 0', r.returncode == 0, (r.stdout[-300:], r.stderr[-300:]))
        show('uninstall hands back the original file, byte for byte', h.raw() == raw0,
             json.dumps(h.read())[:400])
        r = h.run('uninstall')
        show('a second uninstall has nothing to remove', r.returncode == 0 and 'nothing to remove' in r.stdout
             and h.raw() == raw0, r.stdout[-200:])
    finally:
        h.close()

    print('\n  6. an install made by 0.57.0')
    h = Home()
    try:
        h.write(legacy_shape())
        raw0 = h.raw()
        r = h.run('install', '--dry-run')
        show('dry run: drops the unread server entry, updates the four, adds the self-test, removes the gate',
             would(r.stdout) == ['mcpServers.laserbrain removed (Claude Code does not read servers here)',
                                 'SessionStart/lb_safety', 'PreToolUse/lb_safety updated',
                                 'PostToolUse/lb_coverage updated', 'PostToolUseFailure/lb_coverage updated',
                                 'UserPromptSubmit/lb_coverage updated', 'PreToolUse/lb_gate removed'],
             r.stdout[-500:])
        show('  and names the flag that keeps the gate', '--with-gate' in r.stdout)
        show('  and writes nothing', h.raw() == raw0)
        r = h.run('install')
        cfg = h.read()
        show('install exits 0', r.returncode == 0, (r.stdout[-300:], r.stderr[-300:]))
        show('PreToolUse holds lb_safety alone, in the new shape', commands(cfg, 'PreToolUse') == [SAFETY],
             commands(cfg, 'PreToolUse'))
        show('lb_coverage is in the new shape on all three events, once each',
             all(commands(cfg, e) == [COVERAGE] for e in EVENTS[2:]))
        show('the self-test is added', commands(cfg, 'SessionStart') == [SELFTEST])
        show('the unrelated Stop hook is untouched', cfg['hooks']['Stop'] == legacy_shape()['hooks']['Stop'])
        show('no `-m` form is left', '-m laserbrain' not in json.dumps(cfg))
        r = h.run('install')
        show('then a second run changes nothing', 'nothing changed' in r.stdout, r.stdout[-200:])
    finally:
        h.close()
    h = Home()
    try:
        shape = legacy_shape()
        shape['hooks']['PreToolUse'][1]['hooks'][0]['command'] = f'{PY} -m laserbrain.hooks.lb_safety'
        h.write(shape)
        r = h.run('install', '--with-gate')
        cfg = h.read()
        show('--with-gate keeps the gate, brought to the new shape',
             r.returncode == 0 and commands(cfg, 'PreToolUse') == [GATE, SAFETY], commands(cfg, 'PreToolUse'))
        show('the form without -P (before Python 3.11) is recognised too', '-m laserbrain.hooks.lb_safety' not in json.dumps(cfg))
        r = h.sh(GATE, pre_tool('Bash', {'command': 'ls'}))
        show('the gate command runs and lets ls through', r.returncode == 0 and 'Traceback' not in r.stderr,
             (r.returncode, r.stderr[-300:]))
    finally:
        h.close()

    print('\n  7. hand-written wiring is left alone')
    h = Home()
    try:
        h.write(hand_shape())
        hooks0 = h.read()['hooks']
        r = h.run('install', '--dry-run')
        show('dry run: nothing in settings.json would change', would(r.stdout) == [], r.stdout[-500:])
        show('  and it says the hooks are already wired another way', 'did not write' in r.stdout)
        r = h.run('install')
        show('install leaves every hand-written hook exactly as it was',
             r.returncode == 0 and h.read()['hooks'] == hooks0, r.stdout[-300:])
        r = h.run('uninstall')
        cfg = h.read()
        show('uninstall removes nothing: install added nothing',
             r.returncode == 0 and 'nothing to remove' in r.stdout and cfg['hooks'] == hooks0, r.stdout[-300:])
        show('  and lists the hand-written entries it kept', r.stdout.count('kept:') == 5, r.stdout[-600:])
    finally:
        h.close()

    print('\n  8. a moved install is updated in place')
    h = Home()
    try:
        old = ins.command('safety', '/old/env/bin/python3', '/old/env/lib/site-packages/laserbrain/hooks')
        show('the old entry reads as ours', ins._ours('PreToolUse', {'type': 'command', 'command': old}) == 'safety')
        h.write({'hooks': {'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': old}]}]}})
        r = h.run('install')
        cfg = h.read()
        show('updated, not doubled', commands(cfg, 'PreToolUse') == [SAFETY] and 'PreToolUse/lb_safety updated' in r.stdout,
             (commands(cfg, 'PreToolUse'), r.stdout[-300:]))
    finally:
        h.close()
    h = Home()
    try:
        h.write({'hooks': {'PostToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': COVERAGE}]},
                                           {'matcher': '*', 'hooks': [{'type': 'command', 'command': LEGACY['lb_coverage']}]}]}})
        r = h.run('install')
        show('two copies of our entry become one', commands(h.read(), 'PostToolUse') == [COVERAGE]
             and 'PostToolUse/lb_coverage duplicate removed' in r.stdout, (commands(h.read(), 'PostToolUse'), r.stdout[-300:]))
    finally:
        h.close()

    print('\n  9. --with-gate')
    h = Home()
    try:
        r = h.run('install', '--with-gate')
        cfg = h.read()
        show('install --with-gate exits 0 and verifies the gate', r.returncode == 0 and 'lb_gate runs' in r.stdout,
             (r.stdout[-300:], r.stderr[-300:]))
        show('lb_gate is in its own group; lb_safety stays alone in its group',
             [[x['command'] for x in g['hooks']] for g in cfg['hooks']['PreToolUse']] == [[SAFETY], [GATE]],
             cfg['hooks']['PreToolUse'])
        r = h.run('install')
        show('install without the flag takes the gate out again', commands(h.read(), 'PreToolUse') == [SAFETY],
             commands(h.read(), 'PreToolUse'))
        h.run('install', '--with-gate')
        r = h.run('uninstall')
        show('uninstall removes the gate with the rest', r.returncode == 0 and h.read() == {}, h.read())
    finally:
        h.close()

    print('\n 10. uninstall: dry run, no file, an edited entry')
    h = Home()
    try:
        r = h.run('uninstall')
        show('no settings file: exit 0, nothing to remove, no file created',
             r.returncode == 0 and 'nothing to remove' in r.stdout and not h.settings.parent.exists(), r.stdout)
        h.run('install')
        raw1 = h.raw()
        r = h.run('uninstall', '--dry-run')
        show('--dry-run writes nothing', r.returncode == 0 and h.raw() == raw1 and would(r.stdout, 'would remove'),
             r.stdout[-300:])
        show('--dry-run makes no backup', not (h.settings.parent / 'settings.json.before-laserbrain-uninstall').exists())
        cfg = h.read()
        cfg['hooks']['PreToolUse'][0]['hooks'][0]['command'] = SAFETY + ' # edited by hand'
        h.write(cfg)
        r = h.run('uninstall')
        cfg = h.read()
        show('an edited copy of an install entry is kept, and named',
             commands(cfg, 'PreToolUse') == [SAFETY + ' # edited by hand'] and 'kept: PreToolUse/lb_safety' in r.stdout,
             (commands(cfg, 'PreToolUse'), r.stdout[-300:]))
        show('everything else install wrote is gone', sorted(cfg.get('hooks', {})) == ['PreToolUse'] and 'mcpServers' not in cfg,
             cfg)
        r = h.run('install')
        show('install does not add a second lb_safety beside the edited one',
             commands(h.read(), 'PreToolUse') == [SAFETY + ' # edited by hand'], commands(h.read(), 'PreToolUse'))
    finally:
        h.close()

    print('\n 11. a settings.json that cannot be read is refused, unchanged')
    for label, body in (('broken JSON', '{"hooks": '), ('a JSON list', '[]')):
        h = Home()
        try:
            h.settings.parent.mkdir(parents=True)
            h.settings.write_text(body)
            r1 = h.run('install')
            r2 = h.run('uninstall')
            show(f'{label}: install and uninstall exit 1 and leave it as it was',
                 r1.returncode == 1 and r2.returncode == 1 and h.settings.read_text() == body,
                 (r1.returncode, r2.returncode, r1.stdout[-200:]))
        finally:
            h.close()
    h = Home()
    try:
        h.write({'hooks': {'PreToolUse': {'not': 'a list'}}})
        raw0 = h.raw()
        r = h.run('install')
        show('a hooks event that is not a list: refused, unchanged', r.returncode == 1 and h.raw() == raw0, r.stdout[-200:])
    finally:
        h.close()

    print('\n 12. --no-hooks, and a symlinked settings.json')
    h = Home()
    try:
        r = h.run('install', '--no-hooks')
        show('--no-hooks writes no settings file and prints the server line',
             r.returncode == 0 and not h.settings.exists() and ADD_LINE in r.stdout, r.stdout[-300:])
    finally:
        h.close()
    h = Home()
    try:
        real = h.dir / 'dotfiles' / 'claude-settings.json'
        real.parent.mkdir()
        real.write_text(json.dumps({'theme': 'light'}, indent=2))
        h.settings.parent.mkdir(parents=True)
        h.settings.symlink_to(real)
        r = h.run('install')
        show('install writes through the link and keeps it a link',
             r.returncode == 0 and h.settings.is_symlink() and 'hooks' in json.loads(real.read_text()), r.stdout[-200:])
        h.run('uninstall')
        show('uninstall does too', h.settings.is_symlink() and json.loads(real.read_text()) == {'theme': 'light'},
             real.read_text()[:200])
    finally:
        h.close()

    print('\n 13. recognising entries')
    wpy, wdir = r'C:\Py\python.exe', r'C:\Users\someone\venv\Lib\site-packages\laserbrain\hooks'
    wsafety = ins.command('safety', wpy, wdir, posix=False)
    flag = ' -P' if FLAGS else ''
    show('Windows: lb_safety is the module form, which exits 1 (not 2) when it is gone',
         wsafety == f'"{wpy}"{flag} -m laserbrain.hooks.lb_safety', wsafety)
    show('Windows: so is lb_coverage (exit 2 on UserPromptSubmit would refuse every prompt)',
         ins.command('coverage', wpy, wdir, posix=False) == f'"{wpy}"{flag} -m laserbrain.hooks.lb_coverage')
    r2 = subprocess.run([PY, '-P', '-m', 'laserbrain_gone.hooks.lb_safety'], capture_output=True, text=True,
                        env={'PATH': '/usr/bin:/bin'})
    show('a module that is not there exits 1, never 2', r2.returncode == 1, r2.returncode)
    show('Windows: no self-test is written', ins.command('selftest', wpy, wdir, posix=False) is None)
    wcov = ins.command('coverage', wpy, wdir, posix=False)
    show('Windows: both read as ours on their own events',
         ins._ours('PreToolUse', {'type': 'command', 'command': wsafety}) == 'safety'
         and ins._ours('UserPromptSubmit', {'type': 'command', 'command': wcov}) == 'coverage')
    show('an entry on an event install never writes it on is not ours',
         ins._ours('PreToolUse', {'type': 'command', 'command': COVERAGE}) is None
         and ins._ours('Stop', {'type': 'command', 'command': SAFETY}) is None)
    evil = ins.command('safety', PY, '/tmp/elsewhere/hooks')
    show('the safety shape pointing at a file outside a laserbrain/hooks folder is not ours',
         ins._ours('PreToolUse', {'type': 'command', 'command': evil}) is None)
    show('a quoted path with spaces and a quote reads as ours',
         ins._ours('PreToolUse', {'type': 'command', 'command': ins.command(
             'safety', "/opt/my env/it's/python3", "/opt/my env/it's/laserbrain/hooks")}) == 'safety')
    show('a shell line that runs the module among other things is not ours',
         ins._ours('PreToolUse', {'type': 'command', 'command': f'cd /x && {LEGACY["lb_gate"]}'}) is None)
    show('a hook of another type is not ours',
         ins._ours('PreToolUse', {'type': 'prompt', 'command': SAFETY}) is None)
    show('the node MCP entry install writes reads as ours, an edited one does not',
         ins._ours_mcp({'type': 'stdio', 'command': 'node', 'args': [str(PKG / 'mcp-server.mjs')]})
         and not ins._ours_mcp({'type': 'stdio', 'command': 'node', 'args': [str(PKG / 'mcp-server.mjs')],
                                'env': {'LASERBRAIN_TOOLS': 'all'}}))

    print('\n 14. the CLI hands both commands to install.py')
    h = Home()
    try:
        r = h.run('--help')
        show('`laserbrain --help` lists install and uninstall', 'install' in r.stdout and 'uninstall' in r.stdout, r.stdout[-400:])
        r = h.run('install', '--help')
        show('`laserbrain install --help` is install.py\'s parser',
             r.returncode == 0 and '--with-gate' in r.stdout and '--dry-run' in r.stdout, r.stdout[-400:])
        r = h.run('uninstall', '--help')
        show('`laserbrain uninstall --help` shows --dry-run', r.returncode == 0 and '--dry-run' in r.stdout, r.stdout[-400:])
        r = h.run('install', '--no-such-flag')
        show('an unknown flag is refused (exit 2) and writes nothing', r.returncode == 2 and not h.settings.exists(),
             r.returncode)
    finally:
        h.close()

    print('\n 16. the MCP server, in Claude Code\'s own list')
    h = Home(claude=True)
    try:
        h.write(legacy_shape())
        r = h.run('install', '--dry-run')
        show('dry run with `claude` on PATH: would register, and calls nothing',
             'Claude Code MCP server laserbrain' in (would(r.stdout) or []) and h.calls() == [], r.stdout[-400:])
        r = h.run('install')
        show('install exits 0', r.returncode == 0, (r.stdout[-300:], r.stderr[-300:]))
        show('it runs `claude mcp add --scope user laserbrain -- <python> -P -m laserbrain mcp`',
             h.calls() == [ADD + SERVER], h.calls())
        show('  so Claude Code lists the offline server, run by this interpreter',
             (h.claude_json() or {}).get('mcpServers', {}).get('laserbrain')
             == {'type': 'stdio', 'command': PY, 'args': SERVER[1:], 'env': {}}, h.claude_json())
        show('  and the 0.57.0 settings.json entry is gone', 'mcpServers' not in h.read(), h.read().get('mcpServers'))
        r = h.run('install')
        show('a second install registers nothing and changes nothing',
             h.calls() == [ADD + SERVER] and 'nothing changed' in r.stdout, (h.calls(), r.stdout[-200:]))
        r = h.run('uninstall', '--dry-run')
        show('uninstall --dry-run lists the server too, and calls nothing',
             'Claude Code MCP server laserbrain' in (would(r.stdout, 'would remove') or [])
             and h.calls() == [ADD + SERVER], r.stdout[-300:])
        r = h.run('uninstall')
        show('uninstall runs `claude mcp remove --scope user laserbrain`',
             r.returncode == 0 and h.calls()[-1] == REMOVE
             and 'laserbrain' not in (h.claude_json() or {}).get('mcpServers', {}), (h.calls(), r.stdout[-300:]))
    finally:
        h.close()
    h = Home(claude=True)
    try:
        moved = {'type': 'stdio', 'command': '/old/env/bin/python3', 'args': SERVER[1:], 'env': {}}
        (h.dir / '.claude.json').write_text(json.dumps({'mcpServers': {'laserbrain': moved}}))
        r = h.run('install', '--no-hooks')
        show('a moved install\'s entry is replaced: remove, then add',
             h.calls() == [REMOVE, ADD + SERVER] and 'laserbrain updated' in r.stdout, (h.calls(), r.stdout[-300:]))
    finally:
        h.close()
    h = Home(claude=True)
    try:
        own = {'type': 'stdio', 'command': 'node', 'args': ['/opt/example/mcp-server.mjs'],
               'env': {'LASERBRAIN_AGENT': 'claude'}}
        (h.dir / '.claude.json').write_text(json.dumps({'mcpServers': {'laserbrain': own}}))
        r = h.run('install', '--no-hooks')
        show('the user\'s own laserbrain server is kept, and said so',
             h.calls() == [] and 'did not register' in r.stdout
             and h.claude_json()['mcpServers']['laserbrain'] == own, (h.calls(), r.stdout[-300:]))
        r = h.run('uninstall')
        show('  and uninstall leaves it too', h.calls() == [] and 'not the entry install registers' in r.stdout
             and h.claude_json()['mcpServers']['laserbrain'] == own, (h.calls(), r.stdout[-300:]))
    finally:
        h.close()
    h = Home(claude=True)
    try:
        (h.dir / '.claude.json').write_text('{"mcpServers": ')
        r = h.run('install', '--no-hooks')
        show('an unreadable ~/.claude.json: nothing called, the line printed',
             h.calls() == [] and ADD_LINE in r.stdout and r.returncode == 0, (h.calls(), r.stdout[-300:]))
    finally:
        h.close()
    h = Home(claude=True)
    try:
        cfgdir = h.dir / 'claude-config'
        cfgdir.mkdir()
        env = h.env()
        env['CLAUDE_CONFIG_DIR'] = str(cfgdir)
        own = {'type': 'stdio', 'command': 'my-server', 'args': [], 'env': {}}
        (cfgdir / '.claude.json').write_text(json.dumps({'mcpServers': {'laserbrain': own}}))
        r = subprocess.run([PY, *FLAGS, '-m', 'laserbrain', 'install', '--no-hooks'], cwd=str(h.dir), env=env,
                           capture_output=True, text=True, timeout=180)
        show('CLAUDE_CONFIG_DIR moves the list install reads', h.calls() == [] and 'did not register' in r.stdout,
             (h.calls(), r.stdout[-300:]))
    finally:
        h.close()

    print('\n 17. a 0.57.0 entry whose interpreter path holds a space')
    spaced = '/opt/First Last/env/bin/python3'
    for hook, event in (('lb_safety', 'PreToolUse'), ('lb_coverage', 'PostToolUse'), ('lb_gate', 'PreToolUse')):
        show(f'`{spaced} -P -m laserbrain.hooks.{hook}` reads as ours on {event}',
             ins._ours(event, {'type': 'command', 'command': f'{spaced} -P -m laserbrain.hooks.{hook}'}) is not None)
    for bad in (f'/usr/bin/env EXAMPLE=1 {spaced} -m laserbrain.hooks.lb_safety',
                f'cd /tmp && {spaced} -m laserbrain.hooks.lb_safety',
                f'/bin/echo x; {spaced} -m laserbrain.hooks.lb_safety'):
        show(f'not ours: {bad[:44]}...', ins._ours('PreToolUse', {'type': 'command', 'command': bad}) is None)
    h = Home()
    try:
        h.write({'hooks': {e: [{'matcher': '*', 'hooks': [{'type': 'command', 'command': f'{spaced} -P -m laserbrain.hooks.{m}'}]}]
                           for e, m in (('PreToolUse', 'lb_safety'), ('PostToolUse', 'lb_coverage'))}})
        r = h.run('install')
        show('install rewrites them in the new shape and verifies lb_safety',
             commands(h.read(), 'PreToolUse') == [SAFETY] and commands(h.read(), 'PostToolUse') == [COVERAGE]
             and 'lb_safety refuses its test command' in r.stdout, (commands(h.read(), 'PreToolUse'), r.stdout[-300:]))
    finally:
        h.close()

    print('\n 18. deferring to the user\'s own lb_safety')
    h = Home()
    try:
        h.write({'hooks': {'PreToolUse': [{'matcher': 'Edit', 'hooks': [
            {'type': 'command', 'command': 'echo editing; # see lb_safety docs'}]}]}})
        r = h.run('install')
        show('an entry that only names lb_safety in a comment, on Edit, does not stop the guard being wired',
             SAFETY in commands(h.read(), 'PreToolUse') and 'lb_safety refuses its test command' in r.stdout,
             (commands(h.read(), 'PreToolUse'), r.stdout[-300:]))
    finally:
        h.close()
    h = Home()
    try:
        own = tsw.safety_command('/opt/example/bin/python3', '/opt/example/src/laserbrain/hooks')
        h.write({'hooks': {'PreToolUse': [{'matcher': 'Edit|Write', 'hooks': [{'type': 'command', 'command': own}]}]}})
        r = h.run('install')
        show('a real lb_safety entry whose matcher skips Bash does not count either',
             commands(h.read(), 'PreToolUse') == [own, SAFETY], commands(h.read(), 'PreToolUse'))
    finally:
        h.close()
    h = Home()
    try:
        own = tsw.safety_command('/opt/example/bin/python3', '/opt/example/src/laserbrain/hooks')
        h.write({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': own}]}]}})
        r = h.run('install')
        show('a real lb_safety entry on Bash is kept, not doubled',
             commands(h.read(), 'PreToolUse') == [own], commands(h.read(), 'PreToolUse'))
        show('  and install says it did not verify it, instead of "lb_safety refuses"',
             'not verified' in r.stdout and 'lb_safety refuses its test command' not in r.stdout, r.stdout[-400:])
    finally:
        h.close()

    print('\n 15. install.py holds nothing from the machine it was written on')
    src = (PKG / 'install.py').read_text()
    hits = [p for p in (r'/Users/', r'/home/\w', r'\bmise\b', r'iCloud', r'Mobile Documents', r'TURNWATCH',
                        r'diego', r'@\w+\.\w+') if re.search(p, src, re.I)]
    show('no home paths, version-manager paths, cloud folders, names, handles or turnwatch values', not hits, hits)

    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
