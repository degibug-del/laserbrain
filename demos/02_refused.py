#!/usr/bin/env python3
"""The part that is not a reading: an action that does not happen.

    python3 demos/02_refused.py          # no key, no network

01_two_references.py shows laserbrain NOTICING. This shows it ACTING. Same slide, but with an
Operator holding the hands, proposing an irreversible file write on every step.

THE AUTHORIZER BELOW SAYS YES TO EVERYTHING. That is the point of the demo. A human policy
that approves every request is the weakest possible guard, and the third write still does not
happen — because Operator reads the harness itself before taking anything it cannot take
back, and the agent is no longer on the goal it was given. It keeps a counter for exactly
this: `blocked_by_drift`.

WHAT IT IS NOT. Operator refuses on the verdict; that is this class. The PreToolUse hook that
ships with this package (`laserbrain.hooks.lb_gate`) has historically refused on COVERAGE —
have you checked recently enough — and not on the verdict at all. As of 2026-08-27 it reads
the verdict too, but in shadow mode by default: it records what it would have refused and
blocks nothing, because measured precision on goal-drift is 14.6%, and a gate that blocks on
a signal wrong six times in seven is worse than no gate. Set LASERBRAIN_GATE_ON_DRIFT=deny to
enforce it. Two different surfaces, and worth keeping straight.
"""
from laserbrain import Harness, Operator, Refused

RUN = [
    ("fix the failing auth test",           "tests/test_auth.py"),
    ("fix the auth test session handling",  "src/session.py"),
    ("refactor the session store",          "src/store/schema.sql"),
]

harness = Harness()

# Yes to everything. No policy, no judgement, no conditions.
ops = Operator(authorize=lambda act: True, harness=harness)

print()
for goal, path in RUN:
    v = harness.check(goal, distance=5)
    print(f"  step: {goal}")
    print(f"        verdict {v.reason:<12} Φ={v.phi:.2f}  overlap={v.goal_score:.2f}")
    try:
        ops.act(lambda: f"wrote {path}", kind="file", target=path, reversible=False)
        print(f"        WROTE          {path}")
    except Refused as e:
        first = str(e).split(" — ")[0]
        print(f"        REFUSED        {first}")
    print()

print(f"  authorizer asked: {ops.asked}     taken: {ops.taken}     "
      f"refused: {ops.refused}     of those, blocked by drift: {ops.blocked_by_drift}")
print()
print("  Read the counter again: the authorizer was ASKED TWICE, not three times. On the third")
print("  step it was never consulted at all — Operator checks the ground before it checks the")
print("  policy, so an irreversible act proposed off-ground is refused without the question")
print("  ever reaching whoever would have said yes. The file was never touched: not logged,")
print("  not warned about, not written.")
print()
