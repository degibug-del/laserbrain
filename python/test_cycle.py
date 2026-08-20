#!/usr/bin/env python3
"""The cycle detector behind the `oscillating` verdict.

Written 2026-07-27, after `oscillating` had already shipped in three implementations with
no test of its own. That absence is the whole story: the detector tested periods 2 and 3
only, and nobody noticed, because a range that is too narrow does not fail — it returns 0
and every reading beneath it looks healthy.

What exposed it was two lines of mathematics rather than a bug report:

    x = [sin, f(x)],  f = d/dx

sin -> cos -> -sin -> -cos -> sin. Period FOUR. The canonical cycle of the very equation
the verdict was derived from, and the detector could not see it — sixteen readings, four
whole repeats, still 0.
"""
import sys

from laserbrain import Harness, _cycle

FAIL = []


def check(name, got, want):
    if got != want:
        FAIL.append(f'{name}: got {got!r}, want {want!r}')
    print(f"  {'ok  ' if got == want else 'FAIL'} {name:44} {got}")


# ── the case that found the bug ──────────────────────────────────────────────────
print('x = [sin, f(x)], f = d/dx  — period 4')
TRAJ = ['sin', 'cos', '-sin', '-cos']

check('period 4, 8 readings (2 whole repeats)', _cycle(TRAJ * 2), 4)
check('period 4, 16 readings', _cycle(TRAJ * 4), 4)
# Under two whole repeats there is not yet evidence of a cycle, only of variety.
check('period 4, 6 readings (1.5 repeats)', _cycle((TRAJ * 2)[:6]), 0)

# ── every period the detector claims to cover ────────────────────────────────────
print('\nthe declared range, 2..6')
A = [chr(97 + i) for i in range(10)]
for p in range(2, 7):
    n = max(6, 2 * p)
    check(f'period {p} over {n} readings', _cycle([A[i % p] for i in range(n)]), p)

print('\nabove the cap')
for p in (7, 8):
    n = 2 * p
    # Not a failure to detect — a deliberate bound. A pattern this long needs a window no
    # real run produces, and is better described as a process than an oscillation.
    check(f'period {p} is out of range', _cycle([A[i % p] for i in range(n)]), 0)

# ── the things that must NOT read as cycles ──────────────────────────────────────
print('\nnot cycles')
check('constant tail is settled, not oscillating', _cycle(['a'] * 12), 0)
check('healthy varied run',
      _cycle(['grounded', 'advancing', 'advancing', 'reground',
              'advancing', 'advancing', 'advancing', 'excursion']), 0)
check('empty', _cycle([]), 0)
check('single reading', _cycle(['a']), 0)

# ── the smallest period is the true one ──────────────────────────────────────────
print('\nsmallest period wins')
# [a,b] repeated also satisfies period 4 and period 6; 2 is the honest answer, so the
# search must run in ascending order and return the first match.
check('[a,b] x4 is period 2, not 4', _cycle(['a', 'b'] * 4), 2)
check('[a,b,c] x4 is period 3, not 6', _cycle(['a', 'b', 'c'] * 4), 3)

# ── end to end, through a real Harness ───────────────────────────────────────────
print('\nend to end: an agent whose ground cycles with period 4')
# The STATE cycles, so distance cycles with it. Holding distance constant instead would
# be a stall, not a cycle — and it reads as `stalled`, which is a different verdict and a
# different bug. The first version of this test made that mistake and proved nothing.
STATES = [('differentiate sin', 5), ('differentiate cos', 3),
          ('differentiate negative sin', 4), ('differentiate negative cos', 2)]
h = Harness()
seen = []
for i in range(16):
    g, d = STATES[i % 4]
    seen.append(h.check(goal=g, progress='advancing', distance=d).reason)

check('oscillating fires', 'oscillating' in seen, True)
check('fires within 12 steps', min((i for i, r in enumerate(seen) if r == 'oscillating'),
                                   default=99) < 12, True)
# It announces once and re-arms, rather than shouting on every subsequent step.
check('fires once, not every step', seen.count('oscillating'), 1)

# ── the ground, not the reading ──────────────────────────────────────────────────
print('\ncycles in the GROUND (x), not just the reading (f(x))')
# x = [x, f(x)] says the state is the PAIR. `trace` only ever held f(x), so a genuinely
# circling agent was caught only when its READINGS also happened to repeat periodically —
# a coincidence stacked on the thing being detected. Cycling on the ground catches the
# agent that keeps returning to the same goals, whatever the verdicts did.
def run(states, n):
    h = Harness()
    out = [h.check(goal=states[i % len(states)][0], progress='advancing',
                   distance=states[i % len(states)][1]).reason for i in range(n)]
    return next((i + 1 for i, r in enumerate(out) if r == 'oscillating'), None)

# the classic: bouncing between two files
check('period-2 ground fires', run([('read auth.py', 5), ('read session.py', 3)], 12), 6)
check('period-3 ground fires', run([('survey the corpus', 6), ('narrow to physics', 4),
                                    ('read one paper', 2)], 12), 6)
# sin/cos — caught at 8 on the ground, where the reading-only detector needed 11
check('period-4 ground fires at 8',
      run([('differentiate sin', 5), ('differentiate cos', 3),
           ('differentiate negative sin', 4), ('differentiate negative cos', 2)], 16), 8)

print('\nand must still not fire on healthy work')
# A goal that never repeats and a distance that keeps falling is the shape of a run that
# is working. A stall holds ONE ground, which is a settled state, not an oscillation —
# it reads as `stalled`, a different verdict for a different failure.
check('monotonic progress', run([('ship the page', d) for d in range(9, 0, -1)], 9), None)
check('one ground held (stall)', run([('hold the line', 4)], 10), None)

print()
if FAIL:
    print(f'{len(FAIL)} FAILED')
    for f in FAIL:
        print('   ', f)
    sys.exit(1)
print('all pass')
