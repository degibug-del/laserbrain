#!/usr/bin/env python3
"""Allocation routing — the one place supercode is allowed to recommend anything.

Everywhere else this class refuses to act, and the reason is stated in its own docstring:
a supervisor sees three spelled fields while the agent sees the work, so one that regrounds
mid-run is a planner with less information than the planner it overrides.

Allocation inverts that. Which agents are on which grounds is a fact NO agent can observe
— each is perfectly on its own ground and correct at every step. Here the supervisor holds
strictly more information than anyone it advises, which is the only condition under which
advising is honest.

So the boundary these tests defend is: route WORK, never route EXECUTION. And when the
observable state gives no basis to choose, say so rather than flipping a coin and calling
it a decision.
"""
import sys

from laserbrain import Supercode
from laserbrain.catches import Event

FAIL = []


def check(name, got, want):
    if got != want:
        FAIL.append(f'{name}: got {got!r}, want {want!r}')
    print(f"  {'ok  ' if got == want else 'FAIL'} {name:50} {got}")


SAME_A = 'fix the auth bug in session handling'
SAME_B = 'fix the session auth bug'


def two(steps_a=1, steps_b=1, catches_a=0, catches_b=0):
    sc = Supercode()
    sc.observe('a', goal=SAME_A, progress='advancing', distance=5)
    sc.observe('b', goal=SAME_B, progress='advancing', distance=5)
    for _ in range(steps_a):
        sc.observe('a', goal=SAME_A, progress='advancing', distance=4)
    for _ in range(steps_b):
        sc.observe('b', goal=SAME_B, progress='advancing', distance=4)
    for _ in range(catches_a):
        sc.saw('a', Event(kind='claim', name='perf', text='this is 3x faster'))
    for _ in range(catches_b):
        sc.saw('b', Event(kind='claim', name='perf', text='this is 3x faster'))
    return sc


# ── it recommends when it has grounds to ─────────────────────────────────────────
print('recommends on observable state')
r = two(steps_a=4, steps_b=1).route()[0]
check('more steps invested keeps the ground', r['keep'], 'a')
check('and the other yields', r['yield_'], 'b')

r = two(catches_a=1).route()[0]
# Evidence quality outranks investment: an agent whose claims are questioned has the
# weaker claim to the ground even if it has done more.
check('a questioned claim loses the ground', r['keep'], 'b')

# ── it declines when it does not ─────────────────────────────────────────────────
print('\ndeclines when there is no basis')
r = two().route()[0]
check('identical agents get no recommendation', r['keep'], None)
check('and it says why', 'no basis to choose' in r['why'], True)

# ── it never invents work ────────────────────────────────────────────────────────
print('\nit routes work, never execution')
r = two(steps_a=4).route()[0]
# The row says who yields. It does not say what the yielding agent should do instead,
# because supercode has no basis for that — inventing a replacement goal would be the
# exact overreach the rest of the class exists to avoid.
check('no replacement goal is proposed',
      any(k in r for k in ('new_goal', 'reassign', 'instead')), False)
check('the row carries only the shared ground', set(r) >= {'agents', 'keep', 'yield_', 'why'}, True)
# And no agent's verdict was touched by being routed.
sc = two(steps_a=4)
before = sc.agents['b'].last.reason
sc.route()
check('routing changes no verdict', sc.agents['b'].last.reason, before)

# ── no collision, nothing to route ───────────────────────────────────────────────
print('\nnothing to route')
sc = Supercode()
sc.observe('a', goal='ship the page', progress='advancing', distance=5)
sc.observe('b', goal='tune the cache layer', progress='advancing', distance=5)
check('unrelated agents are not routed', len(sc.route()), 0)
check('a single agent is not routed', len(Supercode().route()), 0)

print()
if FAIL:
    print(f'{len(FAIL)} FAILED')
    for f in FAIL:
        print('   ', f)
    sys.exit(1)
print('all pass')
