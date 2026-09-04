#!/usr/bin/env python3
"""thresholds.py — check every calibrated constant against the data it acts on.

WHY THIS EXISTS. research/THRESHOLDS.md reports that three constants in grammar.json sit in
regions of their own distributions where there is little or no data. A document making that
argument with an unrunnable "Reproduce" section would be committing the fault it describes,
so this is the section.

Every number in that file is a count over rows in ~/.config/laserbrain/drift-log.jsonl. The
counts will move as the log grows. The shape is the claim, not the counts.

Run:  python3 research/thresholds.py
      python3 research/thresholds.py --log /path/to/drift-log.jsonl
"""
from __future__ import annotations
import argparse, itertools, json, pathlib, random, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'python'))
from laserbrain import norm, PUBLISHED  # noqa: E402

DEFAULT_LOG = pathlib.Path.home() / '.config/laserbrain/drift-log.jsonl'


def jac(a: str, b: str) -> float:
    A, B = norm(a), norm(b)
    return len(A & B) / len(A | B) if (A or B) else 1.0


def histogram(vals, edges, label, width=52):
    n = len(vals)
    if not n:
        print(f'    {label}: no data')
        return
    for lo, hi in zip(edges, edges[1:]):
        c = sum(1 for v in vals if lo <= v < hi)
        bar = '█' * int(width * c / n)
        print(f'    {lo:>4.2f}-{hi:<4.2f} {c:>6}  ({100*c/n:>5.2f}%)  {bar}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', type=pathlib.Path, default=DEFAULT_LOG)
    ap.add_argument('--pairs-from', type=int, default=180,
                    help='how many distinct grounds to draw pairs from')
    a = ap.parse_args()
    if not a.log.exists():
        sys.exit(f'  no log at {a.log}')

    rows = [json.loads(l) for l in a.log.read_text(errors='ignore').splitlines() if l.strip()]
    print(f'\n  {len(rows)} readings from {a.log}')
    print(f'  constants from grammar.json: goal_min {PUBLISHED.goal_min}, '
          f'self_report_min {PUBLISHED.self_report_min}\n')

    # ── goal_min ────────────────────────────────────────────────────────────────
    gs = sorted(float(r['goal_score']) for r in rows if r.get('goal_score') is not None)
    print(f'  goal_min = {PUBLISHED.goal_min}   ({len(gs)} readings carry goal_score)')
    histogram(gs, [0, .1, .3, .5, .9, 1.01], 'goal_score')
    gap = sum(1 for v in gs if PUBLISHED.goal_min <= v < 0.90)
    print(f'    in [{PUBLISHED.goal_min}, 0.90): {gap}'
          + ('   <- the threshold is in an empty region' if gap == 0 else ''))

    # ── collision_min / revisit_min ─────────────────────────────────────────────
    grounds = {}
    for r in rows:
        if r.get('run') and r.get('goal') and r['run'] not in grounds:
            grounds[r['run']] = r['goal']
    picked = list(grounds.values())
    random.Random(5).shuffle(picked)
    picked = picked[:a.pairs_from]
    pairs = sorted(jac(x, y) for x, y in itertools.combinations(picked, 2))
    print(f'\n  collision_min = 0.60, explore.revisit_min = 0.60'
          f'   ({len(picked)} grounds, {len(pairs)} pairs)')
    histogram(pairs, [0, .1, .3, .6, .9, 1.01], 'ground-pair jaccard')
    above = sum(1 for v in pairs if v >= 0.60)
    print(f'    at or above 0.60: {above} of {len(pairs)} ({100*above/len(pairs):.3f}%)')

    # ── self_report_min ─────────────────────────────────────────────────────────
    sr = sorted(float(r['phi']) for r in rows
                if r.get('progress') in ('stuck', 'circling') and r.get('phi') is not None)
    t = PUBLISHED.self_report_min
    print(f'\n  self_report_min = {t}   (Φ on {len(sr)} stuck/circling readings)')
    histogram(sr, [0, .05, .15, .30, .60, 1.01], 'phi')
    if sr:
        near = sum(1 for v in sr if abs(v - t) <= 0.05)
        admits = sum(1 for v in sr if v > t)
        print(f'    within +-0.05 of {t}: {near}'
              + ('   <- nothing sits near the threshold' if near == 0 else ''))
        print(f'    admitted by `phi > {t}`: {admits}/{len(sr)} ({100*admits/len(sr):.1f}%)')

    print(f'\n  A threshold with no data around it was not derived from this distribution.')
    print(f'  See research/THRESHOLDS.md for what that does and does not mean.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
