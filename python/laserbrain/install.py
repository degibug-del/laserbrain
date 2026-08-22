"""`laserbrain install` — wire the harness into an agent host.

The MCP server is the instrument; the hooks are the harness. Installing only the server
gives you a detector your agent calls when it remembers to, and an agent that has drifted
is exactly the one that will not remember. This wires both.

Hooks are referenced as MODULES, never as file paths:

    python3 -m laserbrain.hooks.lb_gate

so an upgrade moves them and nothing in settings.json goes stale, and a venv path never
gets baked into a config file that outlives it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOOKS = [
    ('UserPromptSubmit', 'lb_coverage', None),
    ('PostToolUse',      'lb_coverage', '*'),
    ('PreToolUse',       'lb_gate',     '*'),
    ('PreToolUse',       'lb_safety',   '*'),
]


def _settings_path(host: str) -> Path:
    return Path.home() / '.claude' / 'settings.json'


def _verify() -> list[str]:
    """Prove each hook executes. Correct wiring and broken hooks look identical from
    outside — which is how they were shipped broken once already."""
    probe = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'echo hi'},
                        'session_id': 'install-check'})
    bad = []
    for mod in ('lb_safety', 'lb_gate', 'lb_coverage'):
        try:
            r = subprocess.run([sys.executable, '-m', f'laserbrain.hooks.{mod}'],
                               input=probe, capture_output=True, text=True, timeout=30)
            noise = (r.stdout + r.stderr).lower()
            if 'unavailable' in noise or 'traceback' in noise:
                bad.append(f'{mod}: {(r.stdout + r.stderr).strip()[:100]}')
        except Exception as e:                                    # noqa: BLE001
            bad.append(f'{mod}: {type(e).__name__}: {e}')
    return bad


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog='laserbrain install')
    ap.add_argument('--host', default='claude', choices=['claude'],
                    help='agent host to wire (only Claude Code today)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--server', choices=['python', 'node'], default='python',
                    help="which stdio server to wire. 'python' (default) is offline — no "
                         "network, no key. 'node' serves 7 more tools, six of which reach a "
                         "hosted service; it needs node on PATH.")
    ap.add_argument('--no-hooks', action='store_true',
                    help='MCP server only — the detector without the enforcement')
    a = ap.parse_args(argv)

    path = _settings_path(a.host)
    cfg = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text())
        except Exception:
            print(f'  {path} is not valid JSON. Fix or move it first; refusing to overwrite.')
            return 1

    changed = []
    mcp = cfg.setdefault('mcpServers', {})
    if 'laserbrain' not in mcp:
        # THE OFFLINE SERVER IS THE DEFAULT, AND STAYS THE DEFAULT.
        #
        # The wheel also ships mcp-server.mjs, which serves 28 tools against this one's 21.
        # It is not wired here unless asked, because six of that difference — ask_alice,
        # analyze_language, compare_phrasings, remember_self, resume_self, forget_self —
        # reach a hosted service. SECURITY.md says the hosted endpoint is "opt-in and
        # separate", and an installer that silently turned it on would make that false for
        # everyone who ran it without reading this.
        #
        # So: --server node opts in, and the line printed afterwards says the option exists.
        # A default that quietly widens what leaves the machine is not a default anyone
        # chose.
        if a.server == 'node':
            mjs = Path(__file__).with_name('mcp-server.mjs')
            if not shutil.which('node'):
                print('  --server node needs node on PATH; not wiring a server')
                mjs = None
            elif not mjs.exists():
                print(f'  --server node: {mjs.name} is not in this install; not wiring')
                mjs = None
            if mjs:
                mcp['laserbrain'] = {'type': 'stdio', 'command': 'node', 'args': [str(mjs)]}
                changed.append('mcpServers.laserbrain (node, 28 tools)')
        else:
            mcp['laserbrain'] = {'type': 'stdio', 'command': 'laserbrain', 'args': ['mcp']}
            changed.append('mcpServers.laserbrain')

    if not a.no_hooks:
        hooks = cfg.setdefault('hooks', {})
        for event, mod, matcher in HOOKS:
            cmd = f'{sys.executable} -m laserbrain.hooks.{mod}'
            entries = hooks.setdefault(event, [])
            if any(mod in str(h.get('command', ''))
                   for e in entries for h in e.get('hooks', [])):
                continue
            entry = {'hooks': [{'type': 'command', 'command': cmd}]}
            if matcher:
                entry['matcher'] = matcher
            entries.append(entry)
            changed.append(f'{event}/{mod}')

    if a.dry_run:
        print('  would change: ' + (', '.join(changed) if changed else 'nothing'))
        return 0

    if changed:
        if path.exists():
            shutil.copy(path, str(path) + '.before-laserbrain')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2))
        print(f'  wired: {", ".join(changed)}')
        if os.path.exists(str(path) + '.before-laserbrain'):
            print(f'  previous settings saved as {path.name}.before-laserbrain')
    else:
        print('  already wired — nothing changed')

    if not a.no_hooks:
        bad = _verify()
        if bad:
            print('\n  HOOKS ARE WIRED BUT NOT HEALTHY:')
            for b in bad:
                print(f'    {b}')
            print('  Tell us rather than working around it.')
            return 1
        print('  hooks verified: lb_safety, lb_gate, lb_coverage all execute')

    # Say the richer server exists, rather than leaving it to be found. Not wiring it by
    # default is a decision about what leaves the machine; hiding it would be a different
    # decision, about what the user gets to know.
    if a.server != 'node' and shutil.which('node') and Path(__file__).with_name('mcp-server.mjs').exists():
        print('\n  node is available: `laserbrain install --server node` wires a server with '
              '7 more tools.')
        print('  Six of them reach the hosted endpoint, which is why it is not the default.')

    print('\n  restart your agent, then:  laserbrain coverage')
    print(f'  to undo: restore {path}.before-laserbrain')
    return 0
