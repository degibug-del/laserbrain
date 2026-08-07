#!/usr/bin/env python3
"""`oscillating` must name a cycle in the WORK, not in the rhythm of a session.

THE MEASUREMENT THAT RETIRED AN ARM

The verdict had two arms. The first looks for a cycle in the GROUND — the goals themselves
repeating — which is what x = [x, f(x)] is about: the ground is x, the verdicts are f(x),
and a cycle in x is the thing worth naming. The second was a fallback that looked for a
cycle in the READINGS when the grounds showed none.

Scored against the recorded corpus on 2026-08-04:

    oscillating fires        16  in 1,823 recorded readings
      cycle in the goals      0
      goals all different    16   precision 0.00

Every window looked like A A A B — one goal worked for several checks, then another handed
over. What repeated was the verdict sequence, which in a working session is
grounded, advancing, advancing, grounded, ... because that is what happens every time a
user speaks. The arm was detecting TASK SWITCHING, and it cannot be tuned out of it: the
period it finds is a property of how often a person talks, not of the work.

So the fallback is gone and the ground arm stays. The ground arm has produced no fires
yet, which makes it untested rather than disproven — an arm that has never cried wolf is
not the one to remove.

WHAT THIS PINS

  the artifact no longer fires   the exact shape from the corpus: several checks on one
                                 goal, then a switch, repeated. It must stay silent.
  a real ground cycle still does an agent alternating between two goals it has already
                                 held is the subject, and must still be caught.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'laserbrain-sdk'))

from laserbrain import Harness                                    # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def verdicts_of(h, steps):
    """The reasons RETURNED to the caller, which is not what the trace holds.

    emit() records the original reading in the trace and returns `oscillating` instead —
    "the cycle is a fact about the sequence, so the original goes in and oscillating is
    what comes out". Reading h._run.trace therefore shows advancing/stalled even on the
    step that fired, and a first version of this test asserted against exactly that and
    called a working detector broken. The corpus is unaffected: lb_coverage records the
    RESPONSE, so its 16 fires are returned verdicts.
    """
    return [v.reason for v in steps]


print('the corpus artifact — work a goal, switch, repeat — stays silent')
h = Harness()
seen = []
for block, goal in enumerate(['ship the CSV export',
                              'fix the flaky auth test',
                              'write the release notes',
                              'update the billing docs']):
    for _ in range(3):
        seen.append(h.check(goal, 'advancing', 6 - block))
rs = verdicts_of(h, seen)
check('no oscillating fire on four consecutive tasks',
      'oscillating' not in rs, ' -> '.join(rs[-6:]))
check('  and the readings themselves DID repeat periodically',
      len(rs) >= 12, f'{len(rs)} readings — the old arm keyed on exactly this')

print()
print('a real cycle in the GROUND is still caught')
h2 = Harness()
seen2 = []
for _ in range(4):
    seen2.append(h2.check('fix the flaky checkout test', 'advancing', 5))
    seen2.append(h2.check('fix the checkout test timeout', 'advancing', 4))
v2 = verdicts_of(h2, seen2)
check('alternating between two held goals fires oscillating',
      'oscillating' in v2, ' -> '.join(v2[-4:]))

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — the verdict names a cycle in the work. The rhythm of a session is not one.')
