#!/usr/bin/env python3
"""Temperature on the search — an ensemble reading, and nothing else may move.

Two claims, and the file exists to prove them rather than assert them:

1. IT IS UNDEFINED FOR A COMPONENT. A single ground has a novelty and does not have a
   temperature, the way a single molecule has a velocity and does not have one. That is
   not a limitation of the measurement, it is what the measurement means — so the answer
   before an ensemble exists must be None, never 0.0.

2. IT DECIDES NOTHING. Every existing verdict thresholds the novelty distribution at its
   extremes; this reports its middle. If adding it moved a single reading it would have
   stopped being a report and become a rule, and the calibration behind those rules would
   silently no longer be the published one.

The third case is the interesting one: a window holding one hot ground among cold ones
reads neither `settled` nor `narrowing` while its temperature is genuinely low. That is
the gap the extremes cannot see, and the reason a middle is worth reporting at all.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laserbrain.explore import Search  # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


print('undefined for a component')

s = Search()
check('no grounds at all -> None', s.temperature() is None, repr(s.temperature()))

r1 = s.ground('design the field in the 1950s New Look')
check('one ground has a novelty', r1.novelty > 0, str(r1.novelty))
check('  and no temperature', s.temperature() is None, repr(s.temperature()))
check('  which the Reading carries as None too', r1.temperature is None)

s.ground('show the modes by teaching speed')
s.ground('build a spectral analyzer')
check('below a full window, still None', s.temperature() is None, repr(s.temperature()))

r4 = s.ground('write the grammar formalization')
check('a full window has one', s.temperature() is not None, str(s.temperature()))
check('  and it is the mean of that window',
      s.temperature() == round(sum(s.novelty[-s.WINDOW:]) / s.WINDOW, 2),
      f'{s.temperature()} vs novelty {[round(x, 2) for x in s.novelty[-s.WINDOW:]]}')
check('  and the Reading carries it', r4.temperature == s.temperature())

print()
print('the middle is not the extremes')

# One hot ground among cold ones. `settled` needs max(window) <= SETTLED_MAX so it cannot
# fire; temperature still reads low because most of the window is cold — the fact neither
# extreme reports.
cold = Search()
cold.ground('alpha beta gamma delta')
for g in ('alpha beta gamma', 'alpha beta', 'alpha beta gamma delta epsilon zeta eta theta'):
    last = cold.ground(g)
t = cold.temperature()
check('a window with one hot ground still reads a low-ish temperature',
      t is not None and t < 0.5, str(t))
check('  while `settled` correctly does NOT fire (an extreme is high)',
      last.reason != 'settled', last.reason)
check('  so the two readings are genuinely different facts',
      max(cold.novelty[-cold.WINDOW:]) > cold.SETTLED_MAX and t < 0.5,
      f'max {max(cold.novelty[-cold.WINDOW:]):.2f}, mean {t}')

print()
print('it decides nothing')

# The same trails read twice: once normally, once with temperature() forced to None.
# Every verdict must be identical — the only way to show the reading is inert.
TRAILS = [
    ['a b c', 'a b c', 'a b c', 'a b c', 'a b c'],
    ['a b c', 'd e f', 'g h i', 'j k l', 'm n o'],
    ['a b c d', 'a b c', 'a b', 'a', 'a b c d e f g h'],
    ['red blue', 'blue red', 'green', 'red blue', 'yellow'],
]
mismatches = []
for trail in TRAILS:
    live, inert = Search(), Search()
    inert.temperature = lambda: None          # the reading, removed
    for g in trail:
        a, b = live.ground(g), inert.ground(g)
        if (a.reason, a.novelty, a.revisit, a.advice) != (b.reason, b.novelty, b.revisit, b.advice):
            mismatches.append((g, a.reason, b.reason))
check('every verdict is identical with and without the reading',
      not mismatches, '' if not mismatches else str(mismatches[:2]))

print()
print('wiring')

check('territory() reports it', 'temperature' in cold.territory())
# It is a WINDOWED mean, and the opening ground stays inside that window for WINDOW
# steps. Four identical grounds read 0.25, not 0.0 — [1.0, 0, 0, 0] — because the first
# genuinely did open new territory. This test asserted 0.0 and was wrong about the
# instrument rather than finding a fault in it; the distinction is worth keeping visible.
frozen = Search()
for g in ['same words here'] * 4:
    frozen.ground(g)
check('the opening ground stays hot inside the window',
      frozen.temperature() == 0.25, str(frozen.temperature()))
frozen.ground('same words here')
check('once the window clears it, a frozen search reads exactly 0.0',
      frozen.temperature() == 0.0, str(frozen.temperature()))
check('  which is a real reading, distinct from the undefined case',
      frozen.temperature() is not None and Search().temperature() is None)

print()
print('the frame is configurable, and saying so is the point')

# Reading another frame must not move this instrument. An observer can compute what a
# different frame would see without changing frames.
fr = Search()
for g in ['a b', 'c d', 'a b', 'e f g', 'h i', 'j k', 'j k', 'j k', 'l m n']:
    fr.ground(g)
before = fr.temperature()
others = {w: fr.temperature(window=w) for w in (2, 3, 6, 8)}
check('reading another frame leaves the instrument on its own',
      fr.temperature() == before and fr.WINDOW == Search.WINDOW, f'{fr.WINDOW}, T {before}')
check('  and the frames genuinely disagree', len(set(others.values())) > 1, str(others))

# NOT monotonic in the window — the reading depends on where the window lands relative to
# the structure of the trail, not only on how wide it is. This is why there is no
# transformation law between frames, and it is worth pinning as a fact about the measure
# rather than leaving it as a claim in a docstring.
seq = [fr.temperature(window=w) for w in (2, 3, 4, 6, 8)]
mono = all(a <= b for a, b in zip(seq, seq[1:])) or all(a >= b for a, b in zip(seq, seq[1:]))
check('temperature is NOT monotonic in the window', not mono, str(seq))

# A window of 1 is refused in both places, for the reason the whole measure exists.
for label, call in (('Search(window=1)', lambda: Search(window=1)),
                    ('temperature(window=1)', lambda: fr.temperature(window=1))):
    try:
        call()
        check(f'{label} is refused', False, 'it was accepted')
    except ValueError as e:
        check(f'{label} is refused', 'at least 2' in str(e), str(e)[:48])

# Silent truncation, found by executing the parameter rather than reading it. A frame
# quietly rounded down is a wrong answer with no symptom, and the frame moves the reading
# by 2.3x — so `Search(window=n/2)` handing back a different frame than the caller
# computed is exactly the class of failure this project is named after.
for bad, exc in ((2.9, ValueError), ('4', TypeError), ('wide', TypeError), (True, TypeError)):
    for label, call in ((f'Search(window={bad!r})', lambda b=bad: Search(window=b)),
                        (f'temperature(window={bad!r})', lambda b=bad: fr.temperature(window=b))):
        try:
            call()
            check(f'{label} is refused', False, 'accepted — silent truncation or coercion')
        except exc:
            check(f'{label} is refused', True)
        except Exception as e:
            check(f'{label} is refused', False, f'wrong error: {type(e).__name__}')

check('a whole float is the same frame, not a different one',
      Search(window=4.0).WINDOW == 4 and fr.temperature(window=6.0) == fr.temperature(window=6))

# THE ONE THAT MATTERS: a configured window is a calibration change, not a display
# option. If it did not move the verdicts, the docstring saying it does would be a lie.
trail = ['a b c', 'a b c', 'a b c d e f', 'a b c', 'a b c', 'a b c', 'a b c']
v4, v6 = [], []
s4, s6 = Search(), Search(window=6)
for g in trail:
    v4.append(s4.ground(g).reason); s4.step(); s4.step()
    v6.append(s6.ground(g).reason); s6.step(); s6.step()
check('a configured window really does move the verdicts', v4 != v6, f'{v4} vs {v6}')

check('territory() reports the frame beside the number',
      fr.territory().get('window') == fr.WINDOW, str(fr.territory().get('window')))

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — a property of the path, undefined for a ground, and decisive in nothing.')
