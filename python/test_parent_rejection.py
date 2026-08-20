#!/usr/bin/env python3
"""A declared parent that falls short must be told about, not silently discarded.

WHAT THIS IS FOR

`parent_goal` exists so a legitimate sub-task can be spelled instead of collapsing into
the single goal slot, and `excursion` is the verdict for one. In 1008 readings the field
was spelled 3 times and `excursion` fired 0 times. That looked like an adoption problem
for weeks. It is not:

  · the advice on every goal-drift already says "If this is a sub-task, pass parent_goal",
    so it is not an awareness problem;
  · all 3 declarations were RECEIVED, measured against the ground, and rejected for
    falling below goal_min — overlaps of 0.03, 0.04 and 0.17 against a floor of 0.30;
  · and the rejection was invisible. The verdict came back as plain goal-drift, whose
    advice then told the agent to pass parent_goal — which it had just done.

An agent that declares a parent, is silently ignored, and is then instructed to do the
thing it just did learns that the field does not work. That is the mechanism holding
adoption at 0.2%, and it is what this file pins.

WHAT IS DELIBERATELY NOT FIXED HERE

The threshold. Three rejected declarations cannot choose a replacement measure: on those
three, containment rescues one, child-in-parent rescues a different one, and neither
rescues the third. Moving a published calibration on three data points is precisely the
mistake the corpus work exists to prevent. Making the rejection legible is what will
generate enough labelled rejections to settle it properly — `parent_overlap` is recorded
for exactly that.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laserbrain import Harness  # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def grounded(goal='build the JSON parser and its benchmark'):
    h = Harness(goal)
    h.check(goal, 'advancing', 6)
    return h


print('a parent that falls short')

h = grounded()
v = h.check('investigate the flaky CI runner on linux', 'advancing', 5,
            parent_goal='ship the release notes for v2')
check('still reads as drift', v.reason == 'goal-drift', v.reason)
check('  but the declaration is acknowledged', 'DID declare a parent' in v.advice)
check('  with the number that decided it', '0.00' in v.advice and 'floor' in v.advice)
check('  and parent_overlap is on the verdict', v.parent_overlap == 0.0, repr(v.parent_overlap))

# THE ONE THAT MATTERS. Never tell an agent to do the thing it just did.
check('  it does NOT tell the agent to pass parent_goal',
      'pass parent_goal' not in v.advice,
      'that instruction is what taught agents the field is broken')
check('  and `why` records both overlaps for the corpus',
      'declared parent overlaps' in v.why, v.why[:60])

print()
print('a parent that holds')

h2 = grounded()
v2 = h2.check('tokenizer edge cases for escaped quotes', 'advancing', 5,
              parent_goal='build the JSON parser and its benchmark')
check('fires excursion, not drift', v2.reason == 'excursion', v2.reason)
check('  and is not counted as drifting', v2.drifting is False, str(v2.drifting))
check('  parent_overlap is absent — nothing was rejected',
      v2.parent_overlap is None, repr(v2.parent_overlap))

print()
print('no declaration at all — the old path, unchanged')

h3 = grounded()
v3 = h3.check('investigate the flaky CI runner on linux', 'advancing', 5)
check('reads as drift', v3.reason == 'goal-drift', v3.reason)
check('  advice still teaches the remedy', 'pass parent_goal' in v3.advice)
check('  and parent_overlap is None', v3.parent_overlap is None, repr(v3.parent_overlap))
check('  absent declaration and rejected declaration are distinguishable',
      v3.parent_overlap is None and v.parent_overlap == 0.0,
      'None means none was made; a number means one was made and rejected')

print()
print('the rejection must not leak into the next step')

# Found by executing edge cases, not by reading: _rejected_parent was only ever SET inside
# the parent block, so a later bare call inherited the previous step's rejection and
# reported parent_overlap on a call that declared nothing. That collapses the single
# distinction this field exists to draw.
hl = grounded()
a = hl.check('investigate the flaky CI runner', 'advancing', 5, parent_goal='ship release notes')
b = hl.check('investigate the flaky CI runner', 'advancing', 5)
check('a rejected declaration reports its overlap', a.parent_overlap == 0.0, repr(a.parent_overlap))
check('  the NEXT bare call reports None', b.parent_overlap is None, repr(b.parent_overlap))
c = hl.check('investigate the flaky CI runner', 'advancing', 5, parent_goal='ship release notes')
check('  and declaring again still reports it', c.parent_overlap == 0.0, repr(c.parent_overlap))

print()
print('the threshold is untouched')

# goal_min is the published calibration. If this test ever passes only because someone
# lowered it, the instrument moved and every drift vector became incomparable.
check('goal_min is still 0.30', h.calibration.goal_min == 0.30, str(h.calibration.goal_min))
# A genuine near-miss. The first draft of this test used 'benchmark the parser build',
# assuming it was under the floor; it shares benchmark/parser/build with the ground and
# scores 0.60, so excursion fired and the test was wrong about the instrument rather than
# finding a fault in it. Measured, not assumed: 0.14.
h4 = grounded()
v4 = h4.check('investigate the flaky CI runner on linux', 'advancing', 5,
              parent_goal='benchmark the release pipeline')
check('a near-miss parent (0.14) is still rejected', v4.reason == 'goal-drift',
      f'{v4.reason} at parent_overlap {v4.parent_overlap}')
check('  and its overlap is reported, not hidden', v4.parent_overlap == 0.14,
      repr(v4.parent_overlap))
# The floor still separates them: one token more of overlap and it would have fired.
h5 = grounded()
v5 = h5.check('escaped-quote handling', 'advancing', 5,
              parent_goal='benchmark the parser build')
check('a parent above the floor (0.60) fires excursion', v5.reason == 'excursion', v5.reason)

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(f.strip() for f in fails))
    sys.exit(1)
print('  PASS — a rejected declaration is named, a good one fires excursion, '
      'and the floor has not moved.')
