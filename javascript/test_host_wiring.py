#!/usr/bin/env python3
"""Can the client actually REACH the instrument? Not: does the gate behave once it does.

laserbrain is served from lasermind/mcp-server.mjs and agents connect to it as CLIENTS.
Neither is a host, and nothing here should read as one vendor's product with a guest — this
file used to call grok "agent-b", a de-branding placeholder that then leaked into a real
path and cost six days of silence. See the note above the parity block.

test_gate_grok.py covers the gate's logic and passes. It passed every day from 2026-07-27 to
2026-08-01 while grok could not connect to laserbrain at all, because nothing checked the
wiring — only the behaviour on the far side of it.

WHAT BROKE, AND WHY NOTHING CAUGHT IT

The instruction layer was named `lasergear` on 2026-07-27 and the MCP server settled in
`lasermind`. One rename, four breakages in the client's setup, none visible from any gate:

  · config.toml launched phronesis/laserbrain/mcp-server.mjs — a directory that does not
    exist. The server never started, so check_state never existed for that client.
  · the groklaserbrain skill called tandem_whoami / tandem_read / tandem_write. Those were
    renamed to link_* and zero tandem_* tools remain.
  · hooks/lib/*.py were 2026-07-25 copies; lb_coverage.py was 353 lines against a
    canonical 671.
  · sync_from_icloud.sh pulled from lasermind/hooks, which now holds 20-line fail-loud
    shims. Running it would have overwritten working hooks with shims.

The symptom was a deadlock that looked like a hook bug: lb_gate.py denies tool calls until
check_state is spelled, and with no server there was no check_state to spell. The hook was
working correctly on an agent with no way to comply.

This repo gates every host-facing surface — check-laserbrain-parity, check-worker-deployed,
sync-grammar --check. It gated none of the client's. That asymmetry is the whole reason six
days of silence read as "this agent does not drift" rather than "this agent is not connected".

WHAT IS AND IS NOT LIVE HERE, stated because green must not be read as more than it is: the
MCP wiring below is real and exercised — the server is launched and its tools are listed. The
hook copies are checked for currency but CANNOT EXECUTE for a client running hooks = false,
which this prints rather than implies.

SKIPS CLEANLY when the client is not installed. The SDK ships to people who do not have it,
and a gate that fails on a missing sibling install teaches people to ignore gates.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

# ONE STATE ROOT — a private tree, so this suite cannot write into the live corpus.
#
# It could, and it did. On 2026-08-05 the live drift log held 2,644 rows of which 1,058 —
# 40% — were written by suites spawning the server against the real ~/.config/laserbrain.
# Synthetic runs are pathological ON PURPOSE (flat distance, repeated goals, abandon bait),
# so they do not dilute the corpus evenly: `stalled` is 39.7% of the test rows against 3.2%
# of the real ones, which makes the whole-log rate 5.6x the truth. Every threshold ever read
# off this log was read off that mixture.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _testhome                                                   # noqa: E402
_testhome.isolate()


HOME = pathlib.Path.home()
# Both roots are injectable, and they are SEPARATE on purpose. A harness that wants to
# point this at a broken fixture overrides GROK_ROOT; overriding HOME instead used to move
# the canonical root too, which silently disabled the three hook comparisons — they
# vanished from the output rather than failing, and only 2 of 4 known breakages fired.
# The real directory is ~/.grok. `.agent-b` is a de-branding rename that hit a PATH — the
# same pass that rewrote live model IDs and a working file path elsewhere — and no such
# directory has ever existed. So this file skipped on every run since, printing "not
# installed; nothing to check" while the host it names sat there unchecked.
#
# It cost exactly what it was written to prevent: grok's hooks went stale again by
# 2026-08-03 (678 lines against a canonical 771, missing the gate-block exclusion and the
# arm recording), and its catches would have been dropped by sensitivity.py as
# pre-contamination — from the one other agent whose data can speak to the single-agent
# caveat at all.
#
# Both names are tried, the real one first, so this cannot go quiet again by rename.
def _grok_root():
    env = os.environ.get('LB_GROK_ROOT')
    if env:
        return pathlib.Path(env)
    for name in ('.grok', '.agent-b'):
        if (HOME / name).is_dir():
            return HOME / name
    return HOME / '.grok'


GROK = _grok_root()
CLIENT = GROK.name.lstrip('.')          # the client's own name — never "the host", never "agent-b"

# OPT-IN, BECAUSE THE SUBJECT IS NOT IN USE. Diego stopped using this client in August 2026,
# and its hook copies have drifted from lasergear accordingly — three parity checks that
# fail on a deployment nobody runs. A permanently red suite is worse than no suite: it
# teaches everyone to ignore the colour, which is the thing this repository is organised
# against.
#
# Not deleted, because "not using it these days" is not "never again" and this file is the
# only thing that checks a host's wiring end to end — the config, the server actually
# starting, the tool list, and the skill naming only tools that exist. Set
# LASERBRAIN_CHECK_GROK=1 to run it; it will report the hook drift again the moment it is
# asked to.
#
# 77, not 0. tests/test_suites.py reads 0 as a PASS and 77 as a skip. Skipping with 0 was
# how this suite reported success on machines that had never seen the client at all.
if os.environ.get('LASERBRAIN_CHECK_GROK', '').strip() not in ('1', 'true', 'yes'):
    print(f'  SKIP — {CLIENT} wiring is not checked by default; '
          f'set LASERBRAIN_CHECK_GROK=1 to run it')
    sys.exit(77)
ICLOUD = pathlib.Path(os.environ.get('LB_ICLOUD_ROOT')
                      or HOME / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis')
LASERGEAR = ICLOUD / 'lasergear'
CANONICAL_SERVER = ICLOUD / 'lasermind/mcp-server.mjs'

if not GROK.exists():
    print(f'  SKIP — {GROK} not present; nothing to check')
    sys.exit(77)

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


# ── 1 · the MCP server the client is configured to launch must exist ────────────
cfg = GROK / 'config.toml'
if not cfg.exists():
    print(f'  SKIP — no {cfg}')
    sys.exit(77)

raw = cfg.read_text()
m = re.search(r'\[mcp_servers\.laserbrain\](.*?)(?=\n\[|\Z)', raw, re.S)
check(f'{CLIENT} has a laserbrain MCP server configured', m is not None)
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
                             env={**os.environ, 'LASERBRAIN_AGENT': CLIENT})
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

# ── 4 · the client's hook copies must match canonical lasergear ──────────────────
#
# CAN THESE FILES EVEN RUN? Asked out loud, because for this client the answer is no.
#
# ~/.grok/config.toml carries `[compat.claude] hooks = false`. The MCP wiring above is
# live — the server is launched, the tools are served, check_state is reachable — but
# nothing in hooks/lib executes. Four green lines saying the copies match canonical
# therefore assure nobody of anything about a running system; they assure you a disabled
# file is a current disabled file.
#
# That is still worth checking, and the parity checks stay: the day hooks are switched on,
# stale copies are exactly the failure this file was written after. What changes is that
# the status is printed rather than implied, so green is never read as "the gate is
# protecting this client". A check whose subject cannot execute is the same species of
# false assurance as a check that silently vanished — this file has already been bitten by
# the second kind and should not ship the first.
#
# NAMING: this is a CLIENT, not a host. laserbrain is served from lasermind/mcp-server.mjs
# and agents connect to it; describing one client as a host makes a shared instrument sound
# like one vendor's product with a guest. The old `agent-b` labels are gone for the same
# reason — a de-branding placeholder that also cost this file six days of silence when it
# leaked into a real path.
hooks_live = None
if cfg.exists():
    _t = cfg.read_text()
    _m = re.search(r'^\s*hooks\s*=\s*(true|false)\s*$', _t, re.M)
    hooks_live = (_m.group(1) == 'true') if _m else None
print()
if hooks_live is False:
    print(f'  note  {CLIENT} runs with hooks = false — nothing in hooks/lib executes for it.')
    print('        The parity checks below keep the copies current for the day that changes;')
    print('        they say nothing about a running gate.')
elif hooks_live is None:
    print(f'  note  no hooks setting found in {cfg.name} — parity checked, execution unknown.')

lib = GROK / 'hooks/lib'
if not lib.exists():
    skip(f"{CLIENT}'s hook copies match lasergear", f'{lib} not present')
elif not LASERGEAR.exists():
    skip(f"{CLIENT}'s hook copies match lasergear", f'{LASERGEAR} not present')
else:
    for f in ('lb_paths.py', 'lb_gate.py', 'lb_coverage.py', 'lb_safety.py'):
        mine, canon = lib / f, LASERGEAR / f
        if not canon.exists():
            continue
        if not mine.exists():
            check(f'{CLIENT} has {f}', False, 'missing')
            continue
        same = mine.read_bytes() == canon.read_bytes()
        check(f'{CLIENT}\'s {f} matches lasergear', same,
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
print(f'  PASS — {CLIENT} can reach the instrument, and its copies agree with canonical.'
      + (' (with skips above)' if skipped else ''))
