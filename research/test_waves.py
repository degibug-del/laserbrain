#!/usr/bin/env python3
"""test_waves.py — the wave protocol, against the collisions that motivated it.

Two real collisions on 2026-07-25 with only two agents running:

  1. both fell back to the session id 'unknown' and merged 50 steps into one file
  2. a host edited app/locus/products/page.tsx while a host was building on /locus

Neither was a code failure. Both were coordination failures, and both would have been
refused by a claim check that ran BEFORE the edit. That is what these tests hold to.

Every case runs against a scratch log, never the live one.
"""
import os, json, tempfile, pathlib

TMP = tempfile.mkdtemp()
os.environ['LASERBRAIN_LINK_LOG'] = str(pathlib.Path(TMP) / 'link.jsonl')

import waves                                    # noqa: E402  (after the env is set)

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def reset_log():
    p = pathlib.Path(os.environ['LASERBRAIN_LINK_LOG'])
    if p.exists():
        p.unlink()


# ── overlap detection: the part that actually prevents the collision ─────────
show('identical paths overlap', waves.overlaps('app/locus/', 'app/locus/'))
show('a parent contains a child', waves.overlaps('app/locus', 'app/locus/products/page.tsx'),
     'this is the /locus collision, caught')
show('a child is contained by a parent', waves.overlaps('app/locus/products/page.tsx', 'app/locus'))
show('a glob matches beneath it', waves.overlaps('app/**', 'app/locus/page.tsx'))
show('siblings do NOT overlap', not waves.overlaps('app/locus', 'app/laserbot'))
show('a prefix that is not a path boundary does not overlap',
     not waves.overlaps('app/locus', 'app/locusts'),
     'naive startswith would call these a collision')

# ── a wave, end to end ───────────────────────────────────────────────────────
reset_log()
row, err = waves.open_wave('ship the coverage gate', surf='agent-a', agent='agent-a')
show('a wave opens', err is None and row['payload']['wave'] == 1, err or '')

row, err = waves.claim('agent-a', ['lasermind/hooks/'])
show('a disjoint claim is accepted', err is None, err or '')

row, err = waves.claim('agent-b', ['app/locus/'])
show('a second disjoint claim is accepted', err is None, err or '')

# ── the collision that actually happened ─────────────────────────────────────
row, err = waves.claim('agent-a', ['app/locus/products/page.tsx'])
show('claiming INSIDE another agent\'s scope is refused', err is not None,
     (err or '')[:74])

# ── the lock disguised as a claim ────────────────────────────────────────────
row, err = waves.claim('agent-a', ['app/**'])
show('an over-broad claim is refused, not merely warned about', err is not None,
     'LINK.md: the protocol can check overlap, it cannot check good faith')

# ── waves do not overlap in time ─────────────────────────────────────────────
row, err = waves.open_wave('a second goal', surf='agent-b', agent='agent-b')
show('a new wave cannot open while one is still open', err is not None,
     (err or '')[:70])

waves.close('agent-a', 'hooks wired')
row, err = waves.open_wave('a second goal', surf='agent-b', agent='agent-b')
show('and still cannot while ONE agent has not closed', err is not None,
     'agent-b claimed and has not closed')

waves.close('agent-b', 'locus pages done')
row, err = waves.open_wave('a second goal', surf='agent-b', agent='agent-b')
show('once everyone closes, the next wave opens', err is None and row['payload']['wave'] == 2,
     err or 'wave 2')

# ── append-only, always ──────────────────────────────────────────────────────
lines = pathlib.Path(os.environ['LASERBRAIN_LINK_LOG']).read_text().splitlines()
show('every line is valid json', all(json.loads(l) for l in lines if l.strip()))
show('nothing was ever rewritten — the log only grew', len(lines) >= 6, f'{len(lines)} lines')
show('a refused claim wrote NOTHING',
     sum(1 for l in lines if json.loads(l).get('kind') == 'claim') == 2,
     'refusals must not pollute the corpus')

# ── the deadlock, and the way out of it ──────────────────────────────────────
# The first implementation had no timeout: claim three paths, walk away, and no wave
# could ever open again. The author did exactly that on the live log.
import datetime
reset_log()
waves.open_wave('an abandoned wave', surf='agent-a', agent='agent-a')
waves.claim('agent-a', ['lasermind/'])

row, err = waves.open_wave('the next one', surf='agent-b', agent='agent-b')
show('a fresh unclosed wave still blocks the next', err is not None, (err or '')[:52])

# age the wave past the stale threshold by rewriting its timestamp in the scratch log
lp = pathlib.Path(os.environ['LASERBRAIN_LINK_LOG'])
old = (datetime.datetime.now(datetime.timezone.utc)
       - datetime.timedelta(hours=waves.STALE_AFTER_H + 1)).isoformat(timespec='seconds').replace('+00:00', 'Z')
lines = []
for l in lp.read_text().splitlines():
    d = json.loads(l)
    if d.get('kind') == 'wave_open':
        d['ts'] = old
    lines.append(json.dumps(d))
lp.write_text('\n'.join(lines) + '\n')

cur = waves.current_wave()
show('a wave past the threshold reads as stale', cur['stale'], f"{cur['age_h']:.1f}h old")

row, err = waves.open_wave('the next one', surf='agent-b', agent='agent-b')
show('a stale wave no longer deadlocks the protocol', err is None, err or 'wave opened')

forced = [json.loads(l) for l in lp.read_text().splitlines()
          if json.loads(l).get('payload', {}).get('forced')]
show('the forced close is RECORDED, not silent', len(forced) == 1,
     forced[0]['text'][:58] if forced else 'nothing recorded')
show('and it names who closed on whose behalf',
     forced and forced[0]['payload']['on_behalf_of'] == 'agent-a'
     and forced[0]['payload']['by'] == 'agent-b')

# ── a forced close must be COUNTED, not merely recorded ─────────────────────
# The pair of assertions above passed for a fortnight while the forced close did nothing:
# current_wave() credited it to `from` (the agent doing the forcing) instead of
# `payload.on_behalf_of`, so the abandoned claimant stayed outstanding and the wave stayed
# OPEN. Found by running `force-close --for agent-b`, watching it print success, and seeing
# the very next `status` still say agent-b was working. Recorded is not the same as counted.
reset_log()
waves.open_wave('a wave someone walks away from', surf='agent-a', agent='agent-a')
waves.claim('agent-a', ['lasermind/'])
waves.claim('agent-b', ['app/locus/'])
waves.close('agent-a', 'my part is done')
row, err = waves.open_wave('the next one', surf='agent-a', agent='agent-a')
show('one agent still working keeps the wave open', err is not None, (err or '')[:46])

import pathlib as _pl
import subprocess, sys as _sys
# ABSOLUTE PATH, EXPLICIT CWD, AND THE EXIT CODE IS CHECKED.
#
# This read `'waves.py'` relative with no cwd, and capture_output swallowed the resulting
# "no such file". Run from lasermind/ it passed; run from the repo root — which is how the
# suite is invoked — the force-close silently never happened and the two assertions below
# failed. The failure looked exactly like the product bug they were written to catch, and
# on 2026-08-04 it was reported as one.
#
# A subprocess whose exit code nobody reads is not a step in a test, it is a wish.
_WAVES = str(_pl.Path(__file__).resolve().parent / 'waves.py')
_forced = subprocess.run([_sys.executable, _WAVES, 'force-close', '--for', 'agent-b'],
                         cwd=_pl.Path(__file__).resolve().parent,
                         env={**os.environ, 'LASERBRAIN_AGENT': 'agent-a'},
                         capture_output=True, text=True)
show('the force-close subprocess actually ran', _forced.returncode == 0,
     (_forced.stderr or _forced.stdout or '').strip().splitlines()[-1][:60]
     if (_forced.stderr or _forced.stdout).strip() else f'exit {_forced.returncode}')
cur = waves.current_wave()
show('after force-close the outstanding agent is cleared',
     'agent-b' not in cur['outstanding'], f"outstanding={cur['outstanding']}")
show('and the wave actually reads CLOSED', not cur['open'],
     'this is the assertion that was missing')
row, err = waves.open_wave('the next one', surf='agent-a', agent='agent-a')
show('so the next wave can open', err is None, err or f"wave {row['payload']['wave']}")

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
