#!/usr/bin/env python3
"""Score the grammar against traces somebody ELSE labelled.

    python3 replay.py traces/example.jsonl
    python3 replay.py traces/*.jsonl --verbose

WHAT THIS IS FOR

Every label in the corpus was produced by this project. `label-fires.py` derives them by
rule, `mark_verdict` records `by` so self-marked ones can be discounted, and `corpus-map.py`
prints which is which — all of that is careful, and none of it is independent. An
instrument scored only on data it generated cannot be shown to be wrong in the one way that
matters: it might be measuring an artefact of its own design and agreeing with itself
perfectly. External labels are the only cure.

WHAT I FOUND WHEN I WENT LOOKING, AND WHY IT CONSTRAINS THIS FILE

Two candidate sources exist publicly, and neither supplies what precision needs:

  agent-drift (jhammant)          Probes whether an agent VIOLATES ITS SYSTEM PROMPT under
                                  adversarial pressure across six value dimensions, judged
                                  by an LLM, scored as a per-run percentage. That is
                                  jailbreak resistance, not task trajectory. An agent can
                                  hold every value perfectly while wandering off the
                                  errand, and can stay perfectly on-task while being talked
                                  out of a constraint. Wrong phenomenon; not adapted here.

  goal-drift-evals (RaunoArike)   The right phenomenon — the AIES paper's own code, agents
                                  under competing objectives. But GD_actions and
                                  GD_inaction are computed per RUN against a baseline run,
                                  and `--interrogate` asks the model its objective at the
                                  END. There is no per-timestep label anywhere in it.

So the honest scope: **per-run agreement, not per-step precision.** The question this file
can answer is "on runs an independent party labelled drifted, did the grammar fire at all,
and did it stay quiet on the clean ones" — a coarser claim than precision, and the only one
the available ground truth actually supports. Anything finer would be invented.

THE DERIVATION PROBLEM — READ THIS BEFORE TRUSTING ANY NUMBER

laserbrain measures a state the agent SPELLS: a goal, a progress word, a distance. Foreign
traces contain none of those. They contain actions, messages and tool calls. To replay one
you must manufacture the very inputs the instrument reads, and that manufacturing is a
judgement that can be wrong in the direction that flatters the result.

This file therefore refuses to guess. A trace must carry `goal` explicitly on every step;
`progress` and `distance` may be absent and are then recorded as derived, with the rule
used written into the output. `--verbose` prints the derived state for every step so a
reader can see exactly what was invented on their behalf. If an adapter has to imagine the
goal itself, that is not a replay of a foreign trace — it is this project writing its own
data again with extra steps, and the whole point was to stop doing that.

TRACE SCHEMA — one JSON object per line

    {"run": "r1", "step": 1, "goal": "...", "drifted": false,      # run-level truth
     "progress": "advancing",       # optional; derived if absent
     "distance": 6,                 # optional; derived if absent
     "label": "clean"}              # optional free-text, carried through

`drifted` is the external judgement about the RUN and must be identical on every row of
that run; a trace that disagrees with itself is rejected rather than silently majority-voted.
"""
import argparse
import glob
import json
import pathlib
import sys
from collections import defaultdict

SDK = pathlib.Path.home() / ('Library/Mobile Documents/com~apple~CloudDocs/phronesis/'
                             'laserbrain-sdk')
sys.path.insert(0, str(SDK))
try:
    from laserbrain import Harness
except Exception as e:                                              # noqa: BLE001
    print(f'  cannot import laserbrain from {SDK}: {e}')
    print('  A replay against a different build of the grammar measures nothing, so this')
    print('  refuses to fall back to a vendored copy.')
    sys.exit(1)

# Derivation rules, named so they can be printed and argued with rather than buried.
# Both are deliberately dull: a clever derivation would be a second instrument smuggled in
# beside the one under test, and any agreement it produced would be unattributable.
DERIVE_PROGRESS = 'advancing-unless-stated@1'
DERIVE_DISTANCE = 'linear-countdown-from-run-length@1'


def load(paths):
    rows = []
    for pat in paths:
        for f in sorted(glob.glob(pat)):
            for i, line in enumerate(pathlib.Path(f).read_text().splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except Exception as e:                              # noqa: BLE001
                    print(f'  {f}:{i}: unreadable — {e}')
                    sys.exit(1)
                r['_src'] = f
                rows.append(r)
    return rows


def group(rows):
    """Split into runs and reject a trace that contradicts itself about the truth."""
    runs = defaultdict(list)
    for r in rows:
        runs[r.get('run')].append(r)
    for run, seq in runs.items():
        seq.sort(key=lambda r: r.get('step') or 0)
        truths = {bool(r['drifted']) for r in seq if 'drifted' in r}
        if len(truths) > 1:
            print(f'  run {run!r}: rows disagree about `drifted` ({truths}).')
            print('  Majority-voting a contradictory label would produce a number with no')
            print('  referent. Fix the trace.')
            sys.exit(1)
        if not truths:
            print(f'  run {run!r}: no `drifted` field on any row — nothing to score against.')
            sys.exit(1)
    return runs


def replay(seq, verbose=False):
    """Feed one run through the real grammar. Returns the verdicts it produced."""
    n = len(seq)
    ground = str(seq[0].get('goal') or '').strip()
    if not ground:
        print(f"  run {seq[0].get('run')!r}: step 1 has no `goal`. The grammar measures")
        print('  displacement FROM a goal; inventing one here would be this project')
        print('  authoring its own ground truth again.')
        sys.exit(1)
    h = Harness(ground)
    out = []
    for i, r in enumerate(seq):
        goal = str(r.get('goal') or '').strip()
        if not goal:
            print(f"  run {r.get('run')!r} step {r.get('step')}: missing `goal`.")
            sys.exit(1)
        prog = r.get('progress')
        derived = []
        if prog not in ('advancing', 'stuck', 'circling'):
            prog = 'advancing'
            derived.append('progress')
        dist = r.get('distance')
        if not isinstance(dist, (int, float)):
            # A plain countdown. It encodes no opinion about whether the run went well,
            # which is the point: a derived distance that fell on good runs and stalled on
            # bad ones would hand the grammar the answer and call the result a measurement.
            dist = max(0, round(10 * (1 - i / max(n - 1, 1))))
            derived.append('distance')
        v = h.check(goal, prog, dist)
        out.append({'step': r.get('step'), 'reason': v.reason, 'drifting': bool(v.drifting),
                    'phi': v.phi, 'derived': derived})
        if verbose:
            d = f"  [derived: {', '.join(derived)}]" if derived else ''
            print(f"    step {r.get('step'):>3}  {prog:<9} d={dist:<2} -> "
                  f"{v.reason:<16} Φ={v.phi}{d}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('traces', nargs='+')
    ap.add_argument('--verbose', action='store_true', help='print every derived state')
    a = ap.parse_args()

    rows = load(a.traces)
    if not rows:
        print('  no rows. Nothing replayed, nothing claimed.')
        return 1
    runs = group(rows)

    bar = '=' * 68
    print(f'\n{bar}\n  REPLAY — the grammar against foreign labels\n{bar}')
    print(f'  runs          {len(runs)}')
    print(f'  rows          {len(rows)}')
    print(f'  derivation    progress: {DERIVE_PROGRESS}')
    print(f'                distance: {DERIVE_DISTANCE}')

    tp = fp = tn = fn = 0
    detail = []
    for run, seq in runs.items():
        truth = bool(next(r['drifted'] for r in seq if 'drifted' in r))
        if a.verbose:
            print(f"\n  run {run} (external: {'DRIFTED' if truth else 'clean'})")
        vs = replay(seq, a.verbose)
        # The first reading of any run is `grounded` by construction — it is where the run
        # starts, not a judgement about it — so it can never count as a detection.
        fired = [v for v in vs[1:] if v['drifting']]
        if truth and fired:
            tp += 1
        elif truth and not fired:
            fn += 1
        elif not truth and fired:
            fp += 1
        else:
            tn += 1
        detail.append((run, truth, fired, vs))

    print(f'\n{bar}\n  PER-RUN AGREEMENT\n{bar}')
    print(f'  external DRIFTED, grammar fired      {tp:>4}')
    print(f'  external DRIFTED, grammar silent     {fn:>4}   <- misses')
    print(f'  external clean,   grammar fired      {fp:>4}   <- false alarms')
    print(f'  external clean,   grammar silent     {tn:>4}')
    n = tp + fn + fp + tn
    if tp + fn:
        print(f'\n  recall     {tp}/{tp + fn} = {tp / (tp + fn) * 100:.0f}%   of drifted runs, caught')
    if tp + fp:
        print(f'  precision  {tp}/{tp + fp} = {tp / (tp + fp) * 100:.0f}%   of fired runs, real')
    if n < 20:
        print(f'\n  {n} run(s). Too few to move a threshold on, and said so here rather than')
        print('  in a footnote — the corpus already has one statistic that got quoted')
        print('  without its denominator.')

    if fn:
        print(f'\n{bar}\n  THE MISSES — a drifted run the grammar sat through\n{bar}')
        for run, truth, fired, vs in detail:
            if truth and not fired:
                seen = ', '.join(sorted({v['reason'] for v in vs}))
                print(f'  {run}: {len(vs)} reading(s), only: {seen}')
    print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
