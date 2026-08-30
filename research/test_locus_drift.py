#!/usr/bin/env python3
"""test_locus_drift.py — the three false positives this adapter produced, pinned.

Every case below is a bug that shipped in a draft of locus_drift.py on 2026-07-25 and
reported a WORKING rig as off-goal. None was caught by reasoning; all three were caught by
running it against real lab logs and disbelieving the output.

  1. flat AT the goal read as `stuck`   — 4798/4800 samples on a matched rig
  2. arrived read as `stalled`          — distance cannot fall below zero
  3. drive OFF read as full detune      — 1200/4800 samples on a run whose status was PASS

The third is the worst, because I wrote "unknown is not zero" in the module docstring and
then computed |0 − f0| as though a stopped drive were a mistuned one. A rule written down
is not a rule applied.
"""
import json, tempfile, pathlib
from locus_drift import detuning, progress_from, score, HELD_HZ

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


# ── 1. unknown is not zero, and not a large number either ────────────────────
show('no frequency channel -> detuning is None', detuning({'G': 900}) is None)
show('drive OFF -> detuning is None, not |0 - f0|',
     detuning({'drive_on': False, 'f_drive': 0.0, 'f0': 1.007}) is None,
     'this is the one that called a PASSING run 1200 samples off-goal')
show('drive ON and matched -> 0.0 Hz',
     detuning({'drive_on': True, 'f_drive': 1.007, 'f0': 1.007}) == 0.0)
show('drive ON and mistuned -> the real gap',
     abs(detuning({'drive_on': True, 'f_drive': 2.007, 'f0': 1.007}) - 1.0) < 1e-9)

# ── 2. flat AT the goal is held, flat AWAY from it is stuck ──────────────────
show('flat at 0.00 Hz is advancing, not stuck', progress_from([0.0, 0.0, 0.0, 0.0]) == 'advancing',
     'a matched rig holds a perfectly flat series')
show('flat at 2.00 Hz IS stuck', progress_from([2.0, 2.0, 2.0, 2.0]) == 'stuck')
show('falling detuning is advancing', progress_from([3.0, 2.0, 1.0, 0.5]) == 'advancing')
show('alternating detuning is circling', progress_from([2.0, 1.0, 2.0, 1.0]) == 'circling',
     'a controller hunting around f0')

# ── 3. arrived is reported as held, never as drift ───────────────────────────
run = {'goal': 'hold f0', 'samples':
       [{'drive_on': True, 'f_drive': 1.0, 'f0': 1.0} for _ in range(30)]}
res, err = score(run)
show('a rig that arrives and holds never reads as drift', err is None and
     all(t['reason'] in ('grounded', 'advancing', 'held') for t in res['trace']),
     'the harness says `stalled` here because distance stopped falling; it had arrived')
show('and those samples are counted as held',
     sum(1 for t in res['trace'] if t['reason'] == 'held') > 0)

# ── a rig that genuinely leaves the pass line must still be caught ───────────
drifted = {'goal': 'hold f0', 'samples':
           [{'drive_on': True, 'f_drive': 1.0, 'f0': 1.0} for _ in range(10)] +
           [{'drive_on': True, 'f_drive': 1.0 + 0.4 * i, 'f0': 1.0} for i in range(1, 12)]}
res2, _ = score(drifted)
off = [t for t in res2['trace'] if t['reason'] not in ('grounded', 'advancing', 'held')]
show('a rig that walks away from f0 IS caught', len(off) > 0,
     f'{len(off)} sample(s) flagged, first at {off[0]["hz"]:.2f} Hz' if off else 'nothing flagged')

# ── the schema contract ──────────────────────────────────────────────────────
show('a run with no declared pass line is refused, not guessed at',
     score({'samples': [{'f_drive': 1, 'f0': 1}]})[1] is not None)

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
