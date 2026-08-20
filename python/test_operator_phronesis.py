"""The whole-trace half of the sixth join.

test_operator_harness.py covers the one-step question: does a single drifting reading
block an irreversible act? This covers the other one: does a BAD RUN whose latest step
looks fine also get blocked? `harness.last.drifting` cannot see that — it only ever
looks at the most recent reading — which is exactly why `harness.phronesis()` reads the
whole trace instead. Same testing rule as test_operator.py: every blocking assertion
carries a side effect and checks it did not happen, not just that an exception fired.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laserbrain import Harness, Operator, Refused  # noqa: E402

fails = []

# A goal this machine's context store has provably never seen. Plain phrases like "ship
# the release" collide with real accumulated dogfooding history — the store is shared
# across every local laserbrain run, not scoped to this test process — and that history
# can make `abandon` (prior_runs >= 2) fire before `repeating` ever gets evaluated. Same
# isolation freshtest.mjs used for the Worker's equivalent store.
GOAL = f'ship the {uuid.uuid4().hex[:8]} release'  


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


# ── repeating: identical spelling three times, latest step still reads clean ──────────
# None of these three checks are individually drifting — same goal, same progress,
# same distance is a perfectly reasonable-looking single step. Only the WHOLE TRACE
# shows the run has not moved. If the operator only read harness.last this would sail
# through; blocked_by_judgment is what proves it did not.
h = Harness(GOAL)
op = Operator(authorize=lambda a: True, harness=h)
fired = []
for _ in range(3):
    h.check(GOAL, 'advancing', 5)
check('the latest step alone does not read as drifting', not h.last.drifting, h.last.reason)
j = h.phronesis()
# Any of the three hard verdicts proves the point (a bad run, clean latest step); which
# ONE fires depends on what else this context's store already knows, and that is exactly
# the thing this test must not depend on to be deterministic.
check('phronesis judges this run one of the blocking verdicts',
      j['verdict'] in ('abandon', 'wrong-problem', 'repeating'), j['verdict'])

try:
    op.act(lambda: fired.append('deployed'), kind='deploy', target='prod')
    check('a repeating run is refused even on a clean latest step', False)
except Refused as e:
    check('a repeating run is refused even on a clean latest step', True, str(e)[:70])
check('  and the deploy never ran', fired == [])
check('  blocked_by_judgment counts it', op.blocked_by_judgment == 1, str(op.blocked_by_judgment))
check('  blocked_by_drift did NOT count it — different failure, different counter',
      op.blocked_by_drift == 0, str(op.blocked_by_drift))

# ── ordering: the human is never asked about a run judged repeating ───────────────────
asked = []
op2 = Operator(authorize=lambda a: (asked.append(a), True)[1], harness=h)
try:
    op2.act(lambda: None, kind='deploy', target='prod')
except Refused:
    pass
check('the authorizer is NOT consulted on a repeating run', asked == [],
      f'{len(asked)} call(s) — a human was asked to rubber-stamp a bad run')

# ── reversible acts still pass — the judgment gate has the same shape as the drift gate
try:
    out = op.act(lambda: 'contents', kind='read', target='f.txt', reversible=True)
    check('a repeating run may still do reversible things', out == 'contents', str(out))
except Refused as e:
    check('a repeating run may still do reversible things', False, str(e)[:60])

# ── a healthy run is unaffected — this cannot become a gate that blocks everything ────
h2 = Harness('write the changelog')
op3 = Operator(authorize=lambda a: True, harness=h2)
for d in (5, 3, 1):
    h2.check('write the changelog', 'advancing', d)
j2 = h2.phronesis()
check('a genuinely closing run is not judged repeating/abandon/wrong-problem',
      j2['verdict'] not in ('abandon', 'wrong-problem', 'repeating'), j2['verdict'])
try:
    out = op3.act(lambda: 'shipped', kind='deploy', target='prod')
    check('a healthy run may still act', out == 'shipped', str(out))
except Refused as e:
    check('a healthy run may still act', False, str(e)[:60])

# ── opt-in: no harness, no change ──────────────────────────────────────────────────────
plain = Operator(authorize=lambda a: True)
try:
    check('an operator with no harness is unaffected by this gate',
          plain.act(lambda: 'ok', kind='deploy', target='prod') == 'ok')
except Refused as e:
    check('an operator with no harness is unaffected by this gate', False, str(e)[:60])

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — a run judged not worth continuing cannot act irreversibly, even on a clean step.')
