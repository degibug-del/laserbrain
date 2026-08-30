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
show('all three events are wired',
     set(hooks) == {'PreToolUse', 'PostToolUse', 'UserPromptSubmit'}, str(sorted(hooks)))
cmds = [h['command']
        for groups in hooks.values() for g in groups for h in g.get('hooks', [])]
show('there are three hook commands', len(cmds) == 3, str(len(cmds)))
for c in cmds:
    name = c.split('laserbrain.hooks.')[-1].split()[0] if 'laserbrain.hooks.' in c else c[:30]
    show(f'{name} is guarded', "import laserbrain' 2>/dev/null &&" in c and '|| exit 0' in c, c[:90])

print('\n  the guard actually works, against a module that truly does not exist')
bare = subprocess.run([sys.executable, '-m', 'definitely_not_installed_xyz'],
                      capture_output=True)
guarded = subprocess.run(
    ['bash', '-c', f"{sys.executable} -c 'import definitely_not_installed_xyz' 2>/dev/null "
                   f"&& {sys.executable} -m definitely_not_installed_xyz || exit 0"],
    capture_output=True)
show('an unguarded missing module exits non-zero', bare.returncode != 0, str(bare.returncode))
show('the guarded form exits 0', guarded.returncode == 0, str(guarded.returncode))

print('\n  the skill and command came along')
show('the drift skill is present', (ROOT / 'skills/drift/SKILL.md').is_file())
show('the /drift command is present', (ROOT / 'commands/drift.md').is_file())
show('the README states the 14.6% precision',
     '14.6' in (ROOT / 'README.md').read_text() if (ROOT / 'README.md').is_file() else False)

print('\n  ' + ('PASS — the plugin installs without denying every tool call.' if ok
                else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
