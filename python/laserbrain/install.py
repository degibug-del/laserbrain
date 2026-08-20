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
        # The package's OWN stdio server: offline, no key, no network call per step.
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

    print('\n  restart your agent, then:  laserbrain coverage')
    print(f'  to undo: restore {path}.before-laserbrain')
    return 0
