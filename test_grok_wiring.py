#!/usr/bin/env python3
"""Can grok actually REACH the instrument? Not: does the gate behave once it does.

test_gate_grok.py covers the gate's logic and passes. It passed every day from
2026-07-27 to 2026-08-01 while grok could not connect to laserbrain at all, because
nothing checked the wiring — only the behaviour on the far side of it.

WHAT BROKE, AND WHY NOTHING CAUGHT IT

The instruction layer was named `lasergear` on 2026-07-27 and the MCP server settled in
`lasermind`. One rename, four breakages in grok's setup, none of them visible from any
existing gate:

  · ~/.grok/config.toml launched phronesis/laserbrain/mcp-server.mjs — a directory that
    does not exist. The server never started, so check_state never existed for grok.
  · the groklaserbrain skill called tandem_whoami / tandem_read / tandem_write. Those were
    renamed to link_* and zero tandem_* tools remain.
  · ~/.grok/hooks/lib/*.py were 2026-07-25 copies; lb_coverage.py was 353 lines against a
    canonical 671.
  · sync_from_icloud.sh pulled from lasermind/hooks, which now holds 20-line fail-loud
    shims. Running it would have overwritten working hooks with shims.

The symptom was a deadlock that looked like a hook bug: lb_gate.py denies tool calls until
check_state is spelled, and with no server there was no check_state to spell. The hook was
working correctly on an agent with no way to comply.

This repo gates every Claude-facing surface — check-laserbrain-parity, check-worker-deployed,
sync-grammar --check. It gated none of grok's. That asymmetry is the whole reason six days
of silence read as "grok does not drift" rather than "grok is not connected".

SKIPS CLEANLY when grok is not installed. The SDK ships to people who do not have it, and
a gate that fails on a missing sibling install teaches people to ignore gates.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

HOME = pathlib.Path.home()
# Both roots are injectable, and they are SEPARATE on purpose. A harness that wants to
# point this at a broken fixture overrides GROK_ROOT; overriding HOME instead used to move
# the canonical root too, which silently disabled the three hook comparisons — they
# vanished from the output rather than failing, and only 2 of 4 known breakages fired.
GROK = pathlib.Path(os.environ.get('LB_GROK_ROOT') or HOME / '.grok')
ICLOUD = pathlib.Path(os.environ.get('LB_ICLOUD_ROOT')
                      or HOME / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis')
LASERGEAR = ICLOUD / 'lasergear'
CANONICAL_SERVER = ICLOUD / 'lasermind/mcp-server.mjs'

if not GROK.exists():
    print('  SKIP — ~/.grok not present; nothing to check')
    sys.exit(0)

fails = []
skipped = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def skip(label, why):
    """A check that could not run must SAY so. A vanished check reads as a passing one,
    which is how this file reported 2 of 4 breakages and looked thorough doing it."""
    print(f'  ????  {label}   SKIPPED: {why}')
    skipped.append(label)


# ── 1 · the MCP server grok is configured to launch must exist ────────────────
cfg = GROK / 'config.toml'
if not cfg.exists():
    print('  SKIP — no ~/.grok/config.toml')
    sys.exit(0)

raw = cfg.read_text()
m = re.search(r'\[mcp_servers\.laserbrain\](.*?)(?=\n\[|\Z)', raw, re.S)
check('grok has a laserbrain MCP server configured', m is not None)
server_path = None
if m:
    am = re.search(r'args\s*=\s*\[\s*"([^"]+)"', m.group(1))
    check('  with an args path', am is not None)
    if am:
        server_path = pathlib.Path(am.group(1))
        check('  and that path EXISTS on disk', server_path.exists(),
              str(server_path) if not server_path.exists() else '')
        # RESOLVING IS NOT ENOUGH. The broken config was repaired twice: the path was
        # repointed at lasermind, AND a symlink was added at the old location. Either
        # alone works, but a gate that only asks "does it resolve" goes green the moment
        # somebody papers over the symptom, and stops watching the thing that broke. So
        # it also asks whether the file it lands on is the canonical server.
        if server_path.exists() and CANONICAL_SERVER.exists():
            same = server_path.resolve() == CANONICAL_SERVER.resolve()
            via = ' (via symlink)' if server_path.is_symlink() else ''
            check('  and resolves to the canonical lasermind server', same,
                  f'{server_path.resolve()}{via}' if not same else f'ok{via}')
        elif not CANONICAL_SERVER.exists():
            skip('  resolves to the canonical server', f'{CANONICAL_SERVER} not present')

# ── 2 · it must actually start and serve the tools ────────────────────────────
if not (server_path and server_path.exists()):
    skip('the server starts and lists tools', 'no resolvable server path')
elif not shutil.which('node'):
    skip('the server starts and lists tools', 'node not on PATH')
else:
    probe = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                        'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                                   'clientInfo': {'name': 'wiring', 'version': '1'}}}) + '\n'
    probe += json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}) + '\n'
    try:
        out = subprocess.run(['node', str(server_path)], input=probe, capture_output=True,
                             text=True, timeout=60,
                             env={**os.environ, 'LASERBRAIN_AGENT': 'grok'})
        names = set()
        for line in out.stdout.splitlines():
            try:
                msg = json.loads(line)
            except Exception:
                continue
            for t in (msg.get('result') or {}).get('tools') or []:
                names.add(t.get('name'))
        check('  the server starts and lists tools', bool(names), f'{len(names)} tools')
        check('  check_state is among them', 'check_state' in names,
              'without it the gate can never be satisfied')

        # ── 3 · the skill may only name tools that exist ──────────────────────
        skill = GROK / 'skills/groklaserbrain/SKILL.md'
        if skill.exists() and names:
            text = skill.read_text()
            named = set(re.findall(r'\b([a-z][a-z0-9]*_[a-z0-9_]+)\b', text))
            # only judge things that look like laserbrain tool calls
            candidates = {n for n in named
                          if n.split('_')[0] in {'link', 'tandem', 'check', 'reset',
                                                 'read', 'speak', 'field', 'mark', 'review'}}
            missing = sorted(c for c in candidates if c not in names)
            check('  the skill names only tools the server serves',
                  not missing, f'missing: {missing}' if missing else '')
    except subprocess.TimeoutExpired:
        check('  the server starts and lists tools', False, 'timed out')
    except Exception as e:
        check('  the server starts and lists tools', False, f'{type(e).__name__}: {e}')

# ── 4 · grok's hook copies must match canonical lasergear ─────────────────────
lib = GROK / 'hooks/lib'
if not lib.exists():
    skip("grok's hook copies match lasergear", f'{lib} not present')
elif not LASERGEAR.exists():
    skip("grok's hook copies match lasergear", f'{LASERGEAR} not present')
else:
    for f in ('lb_gate.py', 'lb_coverage.py', 'lb_safety.py'):
        mine, canon = lib / f, LASERGEAR / f
        if not canon.exists():
            continue
        if not mine.exists():
            check(f'grok has {f}', False, 'missing')
            continue
        same = mine.read_bytes() == canon.read_bytes()
        check(f'grok\'s {f} matches lasergear', same,
              '' if same else f'{len(mine.read_text().splitlines())} vs '
                              f'{len(canon.read_text().splitlines())} lines — run sync_from_icloud.sh')

# ── 5 · the sync script must pull from a path that exists ─────────────────────
sync = lib / 'sync_from_icloud.sh'
if not sync.exists():
    skip('sync_from_icloud.sh points at a real source', 'script not present')
else:
    sm = re.search(r'SRC="\$\{LASERBRAIN_HOOKS_SRC:-([^}]+)\}"', sync.read_text())
    if sm:
        src = pathlib.Path(os.path.expandvars(sm.group(1).replace('$HOME', str(HOME))))
        check('sync_from_icloud.sh points at a real source', src.exists(), str(src))
        if src.exists():
            shim = (src / 'lb_gate.py')
            is_shim = shim.exists() and len(shim.read_text().splitlines()) < 60
            check('  and not at the fail-loud shims', not is_shim,
                  'syncing from there would overwrite working hooks with shims' if is_shim else '')

print()
if skipped:
    print(f'  {len(skipped)} check(s) SKIPPED — this run did not cover: ' + '; '.join(s.strip() for s in skipped))
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(f.strip() for f in fails))
    sys.exit(1)
print('  PASS — grok can reach the instrument, and its copies agree with canonical.'
      + (' (with skips above)' if skipped else ''))
