#!/usr/bin/env python3
"""The frozen ground comes back on EVERY verdict, not only when one fires.

    python3 test_ground_returned.py

WHY THIS TEST EXISTS, 2026-08-18.

Until this date the ground was returned only inside a firing `goal-drift`, in the `why`
field. An agent on a healthy step never saw the goal it started with, and the advice could
read "return to the goal you started with" without saying what that goal was.

That made re-presentation conditional on a detector whose published precision is 4 of 50.
The mechanism actually measured to work is unconditional — re-presenting the ground at every
step took rule survival from 0/8 chains to 8/8 with no detector in the loop, while a generic
reminder fired just as often scored 0/6.

This is exactly the class of property that regresses silently: nothing errors, no verdict
changes, no test fails, and the field simply stops being populated. Hence a test that reads
the field on every reason a run can produce, rather than on one happy path.
"""
import sys
import laserbrain as lb

fails = []

def check(cond, msg):
    print(f"  {'ok  ' if cond else 'FAIL'}  {msg}")
    if not cond:
        fails.append(msg)

print("\nthe ground is returned on every verdict")

# A run that passes through grounded -> advancing -> goal-drift.
h = lb.Harness()
seen = {}
for goal, dist in [('fix the failing auth test', 6),
                   ('fix the auth test session handling', 5),
                   ('fix the auth session store', 5),
                   ('refactor the session store for auth', 4),
                   ('rewrite the billing module entirely', 4)]:
    v = h.check(goal=goal, progress='advancing', distance=dist)
    seen.setdefault(v.reason, []).append(v)
    check(getattr(v, 'ground', None) == 'fix the failing auth test',
          f"{v.reason:12s} carries the original ground")

check(len(seen) >= 2, f"the run produced more than one verdict type ({sorted(seen)})")
check('goal-drift' in seen, "a firing verdict was reached, so both paths were exercised")
check(any(not v.drifting for vs in seen.values() for v in vs),
      "a NON-firing verdict was reached — the point of the change")

# Self-reported stalls take a different branch inside emit().
h2 = lb.Harness()
h2.check(goal='migrate the timezone column', progress='advancing', distance=4)
v2 = h2.check(goal='migrate the timezone column', progress='stuck', distance=4)
check(getattr(v2, 'ground', None) == 'migrate the timezone column',
      f"{v2.reason:12s} carries the ground on the self-report branch")

# An ungrammatical state cannot be spelled, so there is no reading — but if a ground was
# already set, it is still what the run is anchored to and must still come back.
h3 = lb.Harness()
h3.check(goal='write the migration plan', progress='advancing', distance=5)
v3 = h3.check(goal='', progress='advancing', distance=5)
check(v3.reason == 'ungrammatical', "an empty goal is ungrammatical")
check(getattr(v3, 'ground', None) == 'write the migration plan',
      "ungrammatical still carries the ground that was already set")

print()
if fails:
    print(f"  FAIL — {len(fails)} of the above\n")
    sys.exit(1)
print("  PASS — the ground is unconditional\n")
