#!/usr/bin/env python3
"""A flat distance is only a stall when nothing else is moving.

WHY, MEASURED

`stalled` read distance monotonicity and nothing else. That cannot separate three
situations which need three different responses:

    genuinely stuck      distance flat, nothing happening
    EXECUTING a plan     distance flat by nature — carrying a box across a room does not
                         reduce distance-to-done on any single step
    the GOAL MOVED       distance rose through no fault of the agent at all

ARC-AGI-3, 2026-08-05, five agent runs: `stalled` fired on 35 of 133 steps and ALL 35
reached a state the run had never seen before. Not one landed on a step where nothing
happened. Three agents, none of whom knew laserbrain existed, independently described the
fires as "purposeful walking rather than confusion", "pure execution toward a target I'd
already verified", and "execution along a route I already understood". The rule was correct
about the number and wrong about the run.

THE FIX: the observed channel gets a veto. `saw()` already records what happened between
checks; `_anchor` already decides per check whether the report was backed. The stall branch
now reads that history. Every check in the window backed by observed work means the flat
distance is execution, and "return" would be the wrong instruction.

WHAT THIS PINS, and the last two matter most

  no evidence at all      -> stalls exactly as before. Every agent that never calls saw()
                             sees identical behaviour, so nothing calibrated moves.
  fully backed window     -> advancing, not stalled
  PARTIALLY backed        -> still stalls. The veto requires the WHOLE window; a run with
                             intermittent evidence is not executing, it is limping.
  a run that GOES static  -> stalls. This is the inertness check. Replaying the ARC traces
                             with evidence took 35 fires to 0, which is the shape of a rule
                             that has been switched off rather than corrected — so this
                             drives a run that moves and then stops, and requires the fire.
                             On ARC only 3% of steps were static, which is why the veto
                             applies nearly always THERE; that is a fact about the workload,
                             not about the rule.
"""
import os
import pathlib
import sys
import tempfile

os.environ['LASERBRAIN_HOME'] = tempfile.mkdtemp(prefix='lb-stall-')
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'laserbrain-sdk'))

from laserbrain import Harness                                     # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def flat(n=8, evidence='none'):
    h = Harness()
    v = None
    for i in range(n):
        if evidence == 'all' or (evidence == 'half' and i % 2 == 0):
            h.saw('tool', f'move-{i}', ok=True)
        v = h.check('ship the thing', 'advancing', 5)
    return v


print('a flat distance with nothing observed is still a stall — unchanged\n')
check('no evidence -> stalled', flat(evidence='none').reason == 'stalled',
      flat(evidence='none').reason)

print()
print('a flat distance with every check backed is execution, not a stall')
v = flat(evidence='all')
check('fully backed -> advancing', v.reason == 'advancing', v.reason)
check('  and it is not drifting', not v.drifting)
check('  and the report is corroborated', v.anchored == 1.0, str(v.anchored))

print()
print('but the veto is conservative — partial evidence is not execution')
check('half backed -> still stalled', flat(evidence='half').reason == 'stalled',
      flat(evidence='half').reason)

print()
print('and a run that MOVES and then GOES STATIC must still be caught')
# The inertness check. Replaying real traces took 35 fires to 0, which is what a
# switched-off rule looks like as well as a corrected one. This separates them.
h = Harness()
seen = []
for i in range(12):
    if i < 4:
        h.saw('tool', f'move-{i}', ok=True)
    seen.append(h.check('ship the thing', 'advancing', 5).reason)
check('the tail stalls once the world stops responding', seen[-1] == 'stalled', seen[-1])
check('  and it was NOT stalling while it moved', 'stalled' not in seen[:4], str(seen[:4]))

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — stalled fires on stillness, not on a flat number, and it can still fire.')
