#!/usr/bin/env python3
"""The part that is not a reading: an action that does not happen.

    python3 demos/02_refused.py          # no key, no network, no history

01_two_references.py shows laserbrain NOTICING. This shows it ACTING. Same slide, but with an
Operator holding the hands, proposing an irreversible file write on every step.

THE AUTHORIZER BELOW SAYS YES TO EVERYTHING. That is the point of the demo. A human policy
that approves every request is the weakest possible guard, and the last write still does not
happen — because Operator reads the harness itself before taking anything it cannot take
back.

WHAT IT REFUSES ON, AND WHAT IT NO LONGER REFUSES ON. Since 2026-11-15 a goal whose wording
has moved off the ground is a NOTE (`goal-drift`, drifting False), not an interrupt: measured
on real sessions, that wording signal alone was a redirect or a new phase far more often than
a wander (0 of 7 live fires real; 0 of 24 in the July corpus). So one off-goal step proceeds,
and the demo shows that honestly. What still stops the act is the run's own JUDGMENT: three
goal-drifts with no re-ground and no progress read as `wrong-problem`, and Operator refuses
the irreversible act without ever asking the authorizer. It keeps a counter for exactly this:
`blocked_by_judgment` (a drifting verdict would count in `blocked_by_drift`).

HISTORY. The harness remembers contexts across runs (that is how it can say "this is your
fourth attempt"). Run against your real store, this demo would accumulate history and start
refusing earlier on every rerun. So it runs in a throwaway LASERBRAIN_HOME: same result every
time, and nothing written to your own store.

WHAT IT IS NOT. Operator refuses on the verdict and the judgment; that is this class. The
PreToolUse hook that ships with this package (`laserbrain.hooks.lb_gate`) refuses on neither
by default: it records what it would have refused (shadow mode) and blocks nothing. Two
different surfaces, and worth keeping straight.
"""
import os
import tempfile

# Before the import: the context store's path is fixed when laserbrain loads.
os.environ['LASERBRAIN_HOME'] = tempfile.mkdtemp(prefix='laserbrain-demo-')

from laserbrain import Harness, Operator, Refused  # noqa: E402

RUN = [
    ("fix the failing auth test",            "tests/test_auth.py"),
    ("fix the auth test session handling",   "src/session.py"),
    ("refactor the session store",           "src/store/schema.sql"),
    ("rewrite the session store schema",     "src/store/schema.sql"),
    ("migrate the session store to sqlite",  "src/store/migrate.sql"),
]

harness = Harness()

# Yes to everything. No policy, no judgement, no conditions.
ops = Operator(authorize=lambda act: True, harness=harness)

print()
for goal, path in RUN:
    v = harness.check(goal, distance=5)          # distance never falls: no progress is made
    note = '   (a note, not an interrupt)' if v.reason == 'goal-drift' else ''
    print(f"  step: {goal}")
    print(f"        verdict {v.reason:<12} Φ={v.phi:.2f}  overlap={v.goal_score:.2f}{note}")
    try:
        ops.act(lambda: f"wrote {path}", kind="file", target=path, reversible=False)
        print(f"        WROTE          {path}")
    except Refused as e:
        first = str(e).split(" — ")[0]
        print(f"        REFUSED        {first}")
    print()

print(f"  authorizer asked: {ops.asked}     taken: {ops.taken}     refused: {ops.refused}     "
      f"by drift: {ops.blocked_by_drift}     by judgment: {ops.blocked_by_judgment}")
print()
print(f"  Read the counter: the authorizer was asked {ops.asked} times for {len(RUN)} writes. The first")
print("  off-goal steps went ahead — a goal that has moved is noted, not stopped, because that")
print("  signal alone was usually a redirect. But three of them in a row, with no re-ground and no")
print("  progress, are a judgment on the run itself: wrong-problem. The last write was refused")
print("  before the question ever reached whoever would have said yes.")
print()
