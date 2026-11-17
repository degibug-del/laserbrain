"""The Claude Code plugin must install without bricking the session that installs it.

WHY THIS SUITE EXISTS. The plugin ships three hooks, and one of them is a PreToolUse hook. A
PreToolUse hook that exits non-zero is a REFUSAL — so if the hook command fails because the
Python package is not installed, every tool call in that session is denied. Someone who
installs the plugin and has not yet run `pip install laserbrain` would find their session
unusable, with an error naming a module rather than a plugin.

Proven on 2026-08-27:
    python3 -m definitely_not_installed_xyz                              -> exit 1
    python3 -c 'import X' 2>/dev/null && python3 -m X || exit 0          -> exit 0

So every hook command is guarded, and this suite asserts that none of them loses the guard.
It also pins the manifests as valid JSON and the MCP entry as the keyless hosted server,
because a plugin whose .mcp.json points somewhere that needs a credential is a plugin whose
first-run experience is a 401.

Run:  python3 test_plugin_manifest.py
"""
import json
import re
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / 'plugin'
ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


show('the plugin directory exists', ROOT.is_dir(), str(ROOT))
if not ROOT.is_dir():
    raise SystemExit(1)

print('\n  manifests')
manifests = {}
for rel in ('.claude-plugin/plugin.json', '.mcp.json', 'hooks/hooks.json'):
    p = ROOT / rel
    try:
        manifests[rel] = json.loads(p.read_text())
        show(f'{rel} parses', True)
    except Exception as e:
        show(f'{rel} parses', False, str(e))

# The MARKETPLACE manifest lives at the REPO ROOT, not inside the plugin — that is where
# `/plugin marketplace add <owner>/<repo>` looks for it. A copy inside plugin/ would be a
# second manifest for the same plugin and the two would drift; this asserts there is one.
mk_path = ROOT.parent / '.claude-plugin/marketplace.json'
show('the marketplace manifest is at the repo root', mk_path.is_file(), str(mk_path))
show('there is no second copy inside the plugin',
     not (ROOT / '.claude-plugin/marketplace.json').exists())
if mk_path.is_file():
    mk = json.loads(mk_path.read_text())
    entries = mk.get('plugins') or []
    show('the marketplace lists one plugin', len(entries) == 1, str(len(entries)))
    for e in entries:
        src = (ROOT.parent / e.get('source', '')).resolve()
        show(f"source {e.get('source')!r} resolves to a real directory", src.is_dir(), str(src))
        show(f"…and that directory holds a plugin.json",
             (src / '.claude-plugin/plugin.json').is_file())

pj = manifests.get('.claude-plugin/plugin.json', {})
show('plugin.json names the plugin', pj.get('name') == 'laserbrain', repr(pj.get('name')))
show('plugin.json carries a version', bool(pj.get('version')))

print('\n  the hosted MCP entry, so first run needs no key')
mcp = manifests.get('.mcp.json', {}).get('mcpServers', {})
show('one server, named laserbrain', list(mcp) == ['laserbrain'], str(list(mcp)))
entry = mcp.get('laserbrain', {})
show('it is the http transport', entry.get('type') == 'http', repr(entry.get('type')))
# Was 'workers.dev', which is degibug.workers.dev — a personal subdomain. 0.57.0 moved the
# default to the API's own name, and this assertion is what stops it drifting back.
show('it points at the hosted worker',
     'api.phronesis.world' in (entry.get('url') or ''), repr(entry.get('url')))

print('\n  every hook fails open — the load-bearing property')
hooks = manifests.get('hooks/hooks.json', {}).get('hooks', {})
# PostToolUseFailure since 2026-11-14 (round 2 B3): Claude Code skips PostToolUse for a
# failed call, so without it 26 lbq non-zero exits never reached lb_coverage.
show('all four events are wired',
     set(hooks) == {'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'UserPromptSubmit'},
     str(sorted(hooks)))
cmds = [h['command']
        for groups in hooks.values() for g in groups for h in g.get('hooks', [])]


def modname(c):
    """The module a command runs.

    Was `.split()[0]`, which broke the moment the command stopped ending in whitespace:
    the if/then form ends the invocation with `;`, so every name came back as `lb_gate;`
    and three assertions failed for a formatting reason rather than a real one.
    """
    m = re.search(r'laserbrain\.hooks\.([A-Za-z_][A-Za-z0-9_]*)', c)
    return m.group(1) if m else c[:30]


# Was `len(cmds) == 3`, which encoded the state where lb_safety was not wired at all.
# A count is the wrong assertion here: it passed while the destructive-command guard was
# missing from every install, and it would have failed the fix. Name the modules instead.
wired = sorted({modname(c) for c in cmds if 'laserbrain.hooks.' in c})
show('all three hook modules are wired, safety included',
     wired == ['lb_coverage', 'lb_gate', 'lb_safety'], str(wired))
show('lb_gate and lb_safety both run on PreToolUse',
     sorted(modname(h['command'])
            for g in hooks.get('PreToolUse', []) for h in g.get('hooks', []))
     == ['lb_gate', 'lb_safety'], 'PreToolUse')
_fail_cmds = [h['command'] for g in hooks.get('PostToolUseFailure', []) for h in g.get('hooks', [])]
_post_cmds = [h['command'] for g in hooks.get('PostToolUse', []) for h in g.get('hooks', [])]
show('PostToolUseFailure runs lb_coverage only',
     [modname(c) for c in _fail_cmds] == ['lb_coverage'], str([modname(c) for c in _fail_cmds]))
# The PostToolUse command with ONE difference, the guard (B3/B4 review, 2026-11-14). This file
# ships through the plugin marketplace and the package through pip, and a package from before
# 2026-11-14 miscounts failure events (a failed check_state becomes a check row, a failed
# reset_task wipes the session). So this entry runs only where runtime.tool_outcome imports,
# stays silent where an older laserbrain does, and prints the usual notice where none does.
_GUARD_OLD = ("if [ -n \"$LB_PY\" ] && \"$LB_PY\" -c 'import laserbrain' 2>/dev/null; "
              "then LASERBRAIN_AGENT=claude \"$LB_PY\" -m laserbrain.hooks.lb_coverage; else")
_GUARD_NEW = ("if [ -n \"$LB_PY\" ] && \"$LB_PY\" -c 'from laserbrain.runtime import tool_outcome' "
              "2>/dev/null; then LASERBRAIN_AGENT=claude \"$LB_PY\" -m laserbrain.hooks.lb_coverage; "
              "elif [ -n \"$LB_PY\" ] && \"$LB_PY\" -c 'import laserbrain' 2>/dev/null; then :; else")
show('…with the PostToolUse command except its guard, which needs runtime.tool_outcome',
     len(_fail_cmds) == 1 and len(_post_cmds) == 1 and _post_cmds[0].count(_GUARD_OLD) == 1
     and _fail_cmds[0] == _post_cmds[0].replace(_GUARD_OLD, _GUARD_NEW), 'PostToolUseFailure')
show('…and matcher "*", as PostToolUse',
     [g.get('matcher') for g in hooks.get('PostToolUseFailure', [])] == ['*'],
     str([g.get('matcher') for g in hooks.get('PostToolUseFailure', [])]))
for c in cmds:
    name = modname(c)
    # Fails open: every branch reaches exit 0. Denial travels as stdout JSON
    # (lb_gate.py:712), so exiting 0 cannot suppress a real block.
    show(f'{name} fails open', c.rstrip().endswith('exit 0'), c[-40:])
    # `python3` is the wrong name on Windows and anywhere the interpreter is `python`.
    show(f'{name} resolves the interpreter',
         'command -v python3 || command -v python' in c, c[:64])
    # The case that actually happens is a python3 that EXISTS and cannot import
    # laserbrain — venv, pipx, conda. Every mcp-server.mjs has read this variable since
    # line 689; the hooks were the one component that ignored it.
    show(f'{name} honours LASERBRAIN_PYTHON', 'LASERBRAIN_PYTHON' in c, c[:60])
    # The old form ended in `|| exit 0`, so a missing package produced no output at all
    # and nothing distinguished it from a quiet session.
    show(f'{name} says so when it cannot load',
         'laserbrain hooks are inert' in c and '>&2' in c, c[:60])

print('\n  the guard actually works, against a module that truly does not exist')
bare = subprocess.run([sys.executable, '-m', 'definitely_not_installed_xyz'],
                      capture_output=True)
guarded = subprocess.run(
    ['bash', '-c', f"{sys.executable} -c 'import definitely_not_installed_xyz' 2>/dev/null "
                   f"&& {sys.executable} -m definitely_not_installed_xyz || exit 0"],
    capture_output=True)
show('an unguarded missing module exits non-zero', bare.returncode != 0, str(bare.returncode))
show('the guarded form exits 0', guarded.returncode == 0, str(guarded.returncode))

print('\n  the PostToolUseFailure guard tells a current package from an older one')
# Three fake `laserbrain` packages on PYTHONPATH, run through the real command string: one
# with runtime.tool_outcome (runs the hook), one without (an older pip install: runs nothing,
# says nothing), and none at all (the inert notice). The fake hook module only writes a
# marker, so nothing real runs. The interpreter is wrapped in `-S` so an installed laserbrain
# in site-packages cannot stand in for the fakes, HOME is the temp dir, and TMPDIR keeps the
# notice's marker file there too.
import os                                                          # noqa: E402
import tempfile                                                    # noqa: E402
if _fail_cmds:
    _tmp = pathlib.Path(tempfile.mkdtemp(prefix='lbguard-'))
    _py = _tmp / 'py-nosite'
    _py.write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n')
    _py.chmod(0o755)

    def _fake(name, runtime_src):
        pkg = _tmp / name / 'laserbrain'
        (pkg / 'hooks').mkdir(parents=True)
        (pkg / '__init__.py').write_text('')
        (pkg / 'hooks' / '__init__.py').write_text('')
        (pkg / 'runtime.py').write_text(runtime_src)
        (pkg / 'hooks' / 'lb_coverage.py').write_text(
            f"import pathlib; pathlib.Path({str(_tmp / (name + '.ran'))!r}).write_text('ran')\n")
        return str(_tmp / name)

    _cases = {'current': _fake('current', 'def tool_outcome(ev):\n    return True, ""\n'),
              'older': _fake('older', '# a laserbrain from before 2026-11-14\n'),
              'none': str(_tmp / 'empty')}
    (_tmp / 'empty').mkdir()
    _res = {}
    for _name, _pp in _cases.items():
        _env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN')}
        _env.update(PYTHONPATH=_pp, LASERBRAIN_PYTHON=str(_py), HOME=str(_tmp),
                    TMPDIR=str(_tmp / f'tmp-{_name}'))
        (_tmp / f'tmp-{_name}').mkdir()
        _r = subprocess.run(['sh', '-c', _fail_cmds[0]], input='{}', capture_output=True,
                            text=True, env=_env, cwd=str(_tmp), timeout=60)
        _res[_name] = (_r.returncode, (_tmp / f'{_name}.ran').exists(),
                       'laserbrain hooks are inert' in _r.stderr)
    show('a current package runs the hook', _res['current'] == (0, True, False), str(_res['current']))
    show('an older package runs nothing and prints nothing', _res['older'] == (0, False, False),
         str(_res['older']))
    show('no package prints the inert notice and exits 0', _res['none'] == (0, False, True),
         str(_res['none']))

print('\n  the skill and command came along')
show('the drift skill is present', (ROOT / 'skills/drift/SKILL.md').is_file())
show('the /drift command is present', (ROOT / 'commands/drift.md').is_file())
show('the README states the 14.6% precision',
     '14.6' in (ROOT / 'README.md').read_text() if (ROOT / 'README.md').is_file() else False)

print('\n  ' + ('PASS — the plugin installs without denying every tool call.' if ok
                else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
