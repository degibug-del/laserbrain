#!/usr/bin/env python3
"""The distributions the shipped constants were chosen from, computed from the live corpus.

    python3 corpus_facts.py            # print every fact, current values
    python3 corpus_facts.py --json     # the snapshot format, ready to paste

WHY THIS EXISTS, 2026-08-06

The constants in this instrument are derived from the corpus and defended in prose:

    repetition >= 3    "Across 432 observed contexts the maximum identical-spelling repeat
                        distributes: >= 2  12.0% ... >= 3  7.2% ... the elbow is still
                        between 2 and 3"
    stall_window = 4   "Longest flat-distance streak per run, across 209 observed runs:
                        >= 2  39.7% ... >= 4  4.3%"

Those paragraphs are the reasoning. They are also the part that rots, and it has already
happened once: the repetition figures said 9.7 / 2.6 / 1.0, measured before 248 of 680
contexts turned out to be test fixtures. The true figures were 12.0 / 7.2 / 6.0. Every
threshold taken from that log was taken from a mixture, and nothing anywhere compared the
claim to the corpus — it was found only because someone happened to re-derive by hand.

A constant that no longer matches its evidence is not a wrong number. It is a number nobody
can any longer say WHY. That is the failure this closes.

WHAT IS DELIBERATELY NOT DONE HERE: the constants do not move on their own.

An adaptive threshold makes every earlier reading incomparable with every later one, and
comparability is what a published instrument sells. This module measures; it never writes a
calibration. The gate that consumes it (test_thresholds_still_fit.py) fails the build and
prints the fresh numbers, and a human decides whether the constant follows.

THE ELBOW is the decision-relevant fact, not the individual percentages. It is the k where
the marginal drop is largest — where one more required repeat stops buying much selectivity.
A shipped constant need not sit on it (stall_window is 4 while the elbow is 3, chosen on
PRECISION rather than selectivity, and that reason is recorded with the fact). What must not
change unnoticed is the elbow itself: if it moves, the argument that placed the constant no
longer describes the corpus, whatever the constant is.
"""
import collections
import json
import pathlib
import sys

LIVE = pathlib.Path.home() / '.config' / 'laserbrain'   # one-root: live
SNAPSHOT = pathlib.Path(__file__).resolve().parent / 'corpus-facts.json'

# Below these the corpus cannot say anything and the honest output is "not enough", not a
# number. Same discipline as calibrate.py, which refuses to emit a profile from thin data:
# a threshold tuned on a handful of runs is a story about a handful of runs.
MIN_CONTEXTS, MIN_RUNS = 150, 60


def _tail(values, lo=2, hi=6):
    """Fraction of the population at or above each k, as percentages."""
    n = len(values)
    return {k: round(100 * sum(1 for v in values if v >= k) / n, 1) for k in range(lo, hi + 1)}


def _elbow(tail):
    """The k whose marginal drop from k-1 is largest — where selectivity stops being cheap."""
    ks = sorted(tail)
    drops = {k: tail[prev] - tail[k] for prev, k in zip(ks, ks[1:])}
    return max(drops, key=drops.get) if drops else None


def repetition_tail():
    """Max identical-spelling repeat per context — the population `repetition >= 3` reads."""
    cx = json.loads((LIVE / 'contexts.json').read_text())
    reps = [max((v.get('spellings') or {}).values(), default=0) for v in cx.values()]
    return reps


def flat_streak_tail():
    """Longest run of non-improving distance per run — the population `stall_window` reads."""
    runs = collections.defaultdict(list)
    for line in (LIVE / 'drift-log.jsonl').read_text().split('\n'):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        # Judgment rows are a second row keyed to the same step and carry no distance of
        # their own; counting them would double-count the step they annotate.
        if r.get('run') and r.get('distance') is not None and r.get('kind') != 'judgment':
            runs[r['run']].append(r['distance'])
    best = []
    for dh in runs.values():
        f = m = 0
        for i in range(1, len(dh)):
            f = f + 1 if dh[i] >= dh[i - 1] else 0
            m = max(m, f)
        best.append(m)
    return best


# Each fact names the constant it justifies and the criterion that placed it, so a
# constant sitting OFF its elbow reads as a recorded decision rather than as an error.
FACTS = {
    'repetition': {
        'population': repetition_tail,
        'unit': 'contexts',
        'floor': MIN_CONTEXTS,
        'constant': 'repetition >= 3 (laserbrain/__init__.py, mcp-server.mjs)',
        'chosen_on': 'the elbow — past 3 the curve is flat',
    },
    'flat_streak': {
        'population': flat_streak_tail,
        'unit': 'runs',
        'floor': MIN_RUNS,
        'constant': 'stall_window = 4 (grammar.json)',
        'chosen_on': 'PRECISION, not selectivity — window 3 fired on ordinary sub-work. '
                     'The elbow is 3 and the constant is deliberately 4.',
    },
}


def measure():
    """Every fact, measured now. `enough` is False when the corpus cannot support a claim."""
    out = {}
    for name, spec in FACTS.items():
        try:
            pop = spec['population']()
        except Exception as e:
            out[name] = {'enough': False, 'why': f'{type(e).__name__}: {e}'}
            continue
        if len(pop) < spec['floor']:
            out[name] = {'enough': False, 'n': len(pop),
                         'why': f"{len(pop)} {spec['unit']}, floor is {spec['floor']}"}
            continue
        tail = _tail(pop)
        out[name] = {'enough': True, 'n': len(pop), 'unit': spec['unit'],
                     'tail': tail, 'elbow': _elbow(tail),
                     'constant': spec['constant'], 'chosen_on': spec['chosen_on']}
    return out


def load_snapshot():
    try:
        return json.loads(SNAPSHOT.read_text())
    except Exception:
        return {}


if __name__ == '__main__':
    m = measure()
    if '--json' in sys.argv:
        print(json.dumps(m, indent=2))
        sys.exit(0)
    for name, f in m.items():
        if not f.get('enough'):
            print(f'  {name}: not enough evidence — {f["why"]}')
            continue
        print(f'  {name}  ({f["n"]} {f["unit"]})   elbow at {f["elbow"]}')
        print(f'    {f["constant"]}')
        print(f'    chosen on: {f["chosen_on"]}')
        prev = None
        for k in sorted(f['tail']):
            buys = '' if prev is None else f'   buys {prev - f["tail"][k]:4.1f}'
            print(f'      >= {k}   {f["tail"][k]:5.1f}%{buys}')
            prev = f['tail'][k]
        print()
