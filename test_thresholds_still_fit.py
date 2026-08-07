#!/usr/bin/env python3
"""The evidence behind each constant is re-measured, and the build fails when it has moved.

WHY, 2026-08-06

Every constant in this instrument is derived from the corpus and defended in a paragraph of
source comment. Those paragraphs are the reasoning — and they are the part that rots.

It has already happened. The `repetition >= 3` docstring quoted 9.7 / 2.6 / 1.0 percent,
measured before 248 of 680 contexts turned out to be test fixtures. The true figures were
12.0 / 7.2 / 6.0 — the tail, which is exactly the part that threshold reads, was more than
five times heavier than the code claimed. Nothing compared the claim to the corpus. It was
found only because someone happened to re-derive by hand, and had they not, the number would
still be sitting there with a confident and false justification under it.

A constant that no longer matches its evidence is not a wrong number. It is a number nobody
can any longer say WHY, and an instrument whose reasons have quietly expired is worse than
one with no reasons, because it still reads as justified.

WHAT THIS DOES NOT DO: move anything.

An adaptive threshold makes every earlier reading incomparable with every later one, and
comparability is the whole product. So this measures and fails; a human decides whether the
constant follows. That is the same division the rest of the harness runs on — the instrument
reads, the agent acts.

WHAT IT CHECKS

  the elbow has not moved   the decision-relevant fact. A constant need not sit ON the elbow
                            (stall_window is 4 while the elbow is 3, chosen on precision),
                            but if the elbow itself moves, the argument that placed the
                            constant no longer describes the corpus — whatever the constant.
  the percentages still hold within tolerance, so the prose in the source stays true

  and it REFUSES to judge on thin data, rather than passing quietly. A corpus below the
  floor cannot support a claim either way, and saying so is the honest output — the same
  refusal calibrate.py makes.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import corpus_facts                                                # noqa: E402

# Percentage points. The staleness that prompted this moved the tail by 4.6 and 5.0 points,
# so 3.0 would have caught it with room. Tighter than that starts firing on the ordinary
# growth of a live corpus, which trains people to ignore the gate — the failure mode of
# every alarm that cries wolf.
TOLERANCE = 3.0

fails = []
stale = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


snapshot = corpus_facts.load_snapshot()
now = corpus_facts.measure()

check('a shipped snapshot exists to compare against',
      any(isinstance(v, dict) and v.get('enough') for k, v in snapshot.items()
          if not k.startswith('_')),
      f"measured {snapshot.get('_measured', '?')}")

for name, fresh in now.items():
    was = snapshot.get(name) or {}
    print()
    print(f'{name}  —  {was.get("constant", "?")}')

    if not fresh.get('enough'):
        # NOT A FAILURE. The corpus shrank below the floor, or is not there at all (a fresh
        # machine, a quarantine that removed a lot). Nothing can be concluded, and inventing
        # a pass or a fail from no data is the thing this file exists to prevent.
        print(f'    skipped — {fresh.get("why")}. No claim either way.')
        continue

    if not was.get('enough'):
        check(f'{name}: snapshot has a baseline', False,
              'no baseline recorded — run: python3 corpus_facts.py --json > corpus-facts.json')
        continue

    check(f'{name}: the elbow has not moved',
          fresh['elbow'] == was['elbow'],
          f'was {was["elbow"]}, now {fresh["elbow"]}' if fresh['elbow'] != was['elbow']
          else f'still {fresh["elbow"]}  ({fresh["n"]} {fresh["unit"]}, was {was["n"]})')

    moved = {k: (was['tail'].get(str(k), was['tail'].get(k)), v)
             for k, v in fresh['tail'].items()
             if was['tail'].get(str(k), was['tail'].get(k)) is not None
             and abs(was['tail'].get(str(k), was['tail'].get(k)) - v) > TOLERANCE}
    check(f'{name}: the quoted percentages still hold (±{TOLERANCE})', not moved,
          '; '.join(f'>={k}: {a} -> {b}' for k, (a, b) in sorted(moved.items()))
          if moved else f'{len(fresh["tail"])} points within tolerance')
    if moved:
        stale.append(name)

print()
if stale:
    # PASTE-READY, because a gate that only says no gets suppressed. The whole cost of
    # re-deriving should be reading the new numbers and deciding.
    print('  the corpus has moved under these constants. Current distributions:')
    print()
    for name in stale:
        f = now[name]
        prev = None
        print(f'    {name}  ({f["n"]} {f["unit"]})   elbow at {f["elbow"]}')
        for k in sorted(f['tail']):
            buys = '' if prev is None else f'   buys {prev - f["tail"][k]:4.1f}'
            print(f'      >= {k}   {f["tail"][k]:5.1f}%{buys}')
            prev = f['tail'][k]
    print()
    print('    Decide whether the constant follows, update the paragraph that defends it,')
    print('    then: python3 corpus_facts.py --json > corpus-facts.json')

if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — every constant can still say why it is what it is.')
