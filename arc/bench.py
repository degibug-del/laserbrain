#!/usr/bin/env python3
"""laserbrain on ARC-AGI-3 — observe-only, so every verdict has a knowable outcome.

    python3 bench.py --games 6 --steps 200
    python3 bench.py --report                 # re-read the last run without replaying it

WHY ARC-AGI-3 AND NOT ARC-AGI-1 OR 2

ARC-AGI-1 and 2 are static puzzles: one grid in, one grid out, the goal handed to you and
fixed. Nothing about them can exercise the thing laserbrain measures — `goal-drift` is 17.6%
of every real verdict in the corpus and on a static puzzle it cannot fire at all, because
the goal never moves. They were downloaded first and are the wrong instrument.

ARC-AGI-3 is interactive. An agent is dropped into a game with no instructions, no stated
goal and no rules, and has to work out what it is even trying to do. Three consequences:

  the agent SETS the goal      which is the thing laserbrain grounds against
  the score IS action waste    RHAE — Relative Human Action Efficiency. That is the same
                               quantity laserbrain claims to improve; ARC-AGI-1/2 have no
                               waste metric of any kind
  the failure mode is thrash   frontier models score under 1% where humans solve everything,
                               and they fail by flailing, which is what `stalled`,
                               `repeating` and `circling` claim to detect

THE DESIGN THAT MAKES THIS A MEASUREMENT AND NOT A DEMO

laserbrain never stops a run. It watches, its verdicts are recorded, and the agent does not
read them. That is not a simplification — it is the whole point. If a verdict halted the
run, the counterfactual would be unobservable: you could never tell whether the agent it
stopped was about to get somewhere. Observe-only means every fire has an outcome measured
from what actually happened next.

WHAT THE SELF-REPORT IS BUILT FROM, none of it invented:

    advancing   the action produced a frame this run has never seen
    circling    the action produced a frame this run HAS seen before
    stuck       the action changed nothing at all

Measured on 40 random actions before this was written: 34 new, 0 revisited, 6 no-change —
so all three terms are observable on real games, and an agent reporting them is reporting
the environment rather than its own mood.

`distance` is the honest hard case. An explorer with no stated goal genuinely does not know
how far from done it is, so it is derived from level progress — the only ground truth the
environment offers — and stays pinned near 10 for most runs. That is not a defect of the
harness; it is what the situation is, and it is worth knowing how the instrument behaves
when its second term carries almost no information.

THE GROUND TRUTH, stated before any number is computed

For `stalled`, `repeating` and the `wrong-problem` judgment, the claim is always some form
of "you are going nowhere — change something". So:

    a fire at step t is CORRECT   if the agent reached no state it had never seen before
                                  in the rest of the run
    a fire at step t is WRONG     if it did

That is the verdict's own claim, checked against what happened, with nothing to argue about
afterwards. It is decided per fire, and the tail is what decides it — so fires in the last
`--tail` steps are excluded from scoring rather than counted as correct by running out of
run, which would flatter the instrument for free.

ISOLATION: the whole benchmark runs under its own LASERBRAIN_HOME. On 2026-08-05 40% of the
live drift log turned out to be test output, and benchmark runs are exactly as pathological
as test runs. They belong in their own tree, and the analysis reads that tree.
"""
import argparse
import hashlib
import json
import os
import pathlib
import random
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / 'runs'

# ── isolation, before any laserbrain import: the package binds its paths at import time ──
BENCH_HOME = HERE / '.state'
(BENCH_HOME / 'config').mkdir(parents=True, exist_ok=True)
(BENCH_HOME / 'sessions').mkdir(parents=True, exist_ok=True)
os.environ['LASERBRAIN_HOME'] = str(BENCH_HOME)

sys.path.insert(0, str(HERE.parent.parent / 'laserbrain-sdk'))


def load_key():
    """The key set-arc-key.sh stored, or the anonymous one. Never printed.

    READ FROM THE LIVE ROOT ON PURPOSE, and marked `one-root: live` for the resolver gate.
    This harness points LASERBRAIN_HOME at its own ./.state so benchmark runs cannot reach
    the corpus — but the API key is not benchmark state, it is the machine's credential and
    it lives where set-arc-key.sh put it. Resolving it through the relocated root would look
    inside .state, find nothing, and silently fall back to the anonymous key, which is the
    quiet-degradation failure set-arc-key.sh was written to prevent.
    """
    p = pathlib.Path(os.environ.get('LASERBRAIN_ARC_KEY_PATH')
                     or (pathlib.Path.home() / '.config' / 'laserbrain' / 'arc-api-key'))  # one-root: live
    try:
        return p.read_text().strip()
    except OSError:
        return ''


def frame_key(obs):
    import numpy as np
    f = obs.frame
    a = np.array(f[-1] if isinstance(f, list) and len(f) else f)
    return hashlib.md5(a.tobytes()).hexdigest()[:12]


def play(arc, game_id, steps, seed, distance_mode='coverage'):
    """One run. Returns the step trace; laserbrain is consulted but never obeyed.

    TWO ARMS, because the first version of this benchmark measured its own scaffolding.

      levels     distance = how many levels remain. The only ground truth the environment
                 offers — and for a run that never completes a level it is CONSTANT at 10.
                 `stalled` is "distance stopped falling", so with a constant distance it
                 fires on every step by construction, and every fire is wrong because the
                 agent kept finding new states. That produced a clean 0% precision on all
                 four verdicts, which says nothing about laserbrain and everything about
                 feeding it a term with no information in it.

      coverage   distance = how much NEW ground the last window covered, scaled 10..0. It
                 falls while the agent is discovering and rises when it stops. This is the
                 honest distance for an explorer that has no stated finish line, and it is
                 what the instrument is designed to read.

    Running both is the measurement. The difference between them is how much laserbrain
    depends on its second term carrying real information — which is worth knowing, because
    on a real agent that term is self-reported and nobody checks it.
    """
    from arcengine import GameAction
    from laserbrain import Harness

    ACTS = [GameAction.ACTION1, GameAction.ACTION2, GameAction.ACTION3,
            GameAction.ACTION4, GameAction.ACTION5, GameAction.ACTION6]
    rng = random.Random(seed)
    env = arc.make(game_id)
    obs = env.reset()

    h = Harness()
    goal = f'complete a level of {game_id}'
    seen = {frame_key(obs)}
    prev = frame_key(obs)
    trace = []
    recent, WINDOW = [], 8

    for i in range(steps):
        act = rng.choice([a for a in ACTS if a.value in (obs.available_actions or [1])] or ACTS)
        t0 = time.time()
        obs = env.step(act)
        k = frame_key(obs)

        if k == prev:
            progress = 'stuck'          # the action changed nothing
        elif k in seen:
            progress = 'circling'       # somewhere this run has already been
        else:
            progress = 'advancing'      # genuinely new ground

        novel = k not in seen
        seen.add(k)
        prev = k
        recent.append(novel)
        if len(recent) > WINDOW:
            recent.pop(0)
        if distance_mode == 'levels':
            remaining = max(0, (obs.win_levels or 1) - (obs.levels_completed or 0))
            distance = min(10, round(10 * remaining / max(1, obs.win_levels or 1)))
        else:
            # Coverage: the share of the last WINDOW actions that broke new ground. All new
            # -> 0 (moving well); none new -> 10 (going nowhere). An explorer's real sense
            # of "how far from done" is how much is still being discovered.
            rate = sum(recent) / len(recent)
            distance = int(round(10 * (1 - rate)))

        v = h.check(goal, progress, distance)
        j = h.phronesis()

        trace.append({
            'step': i + 1, 'action': act.name, 'progress': progress, 'distance': distance,
            'novel': novel, 'levels': obs.levels_completed, 'state': str(obs.state),
            'reason': v.reason, 'drifting': bool(v.drifting),
            'judgment': j.get('verdict'), 'phi': round(float(v.phi), 3),
            'anchored': v.anchored, 'goal_score': v.goal_score,
            'ms': int((time.time() - t0) * 1000),
        })
        if str(obs.state).endswith('WIN'):
            break

    return {'game': game_id, 'seed': seed, 'steps': len(trace),
            'levels': trace[-1]['levels'] if trace else 0,
            'distinct_states': len(seen), 'trace': trace}


def score(runs, tail):
    """Precision of the 'you are going nowhere' verdicts, against what happened next.

    A fire is only scorable if there is enough run left to falsify it — see `tail`. Fires
    in the last `tail` steps are DROPPED, not counted correct, because a verdict that is
    right only because the run ended is not right about anything.
    """
    CLAIMS_NOWHERE = {'stalled', 'oscillating', 'self-report:circling', 'self-report:stuck'}
    JUDGES_NOWHERE = {'repeating', 'wrong-problem', 'abandon'}
    out = {}
    for label, field, wanted in (('reading', 'reason', CLAIMS_NOWHERE),
                                 ('judgment', 'judgment', JUDGES_NOWHERE)):
        rows = []
        for r in runs:
            tr = r['trace']
            for idx, s in enumerate(tr):
                v = s.get(field)
                if v not in wanted:
                    continue
                rest = tr[idx + 1:]
                if len(rest) < tail:
                    continue                       # not falsifiable — dropped, not scored
                went_somewhere = any(x['novel'] for x in rest)
                rows.append({'verdict': v, 'correct': not went_somewhere,
                             'new_states_after': sum(1 for x in rest if x['novel'])})
        by = {}
        for row in rows:
            b = by.setdefault(row['verdict'], {'n': 0, 'right': 0, 'after': 0})
            b['n'] += 1
            b['right'] += 1 if row['correct'] else 0
            b['after'] += row['new_states_after']
        out[label] = {'total': len(rows), 'by_verdict': by}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=6)
    ap.add_argument('--steps', type=int, default=200)
    ap.add_argument('--tail', type=int, default=25,
                    help='a fire needs this many steps after it to be falsifiable')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--distance', choices=['coverage', 'levels'], default='coverage',
                    help="what distance means: 'coverage' = new ground in the last window "
                         "(informative), 'levels' = levels remaining (constant, the control)")
    ap.add_argument('--report', action='store_true', help='re-read the last run')
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    latest = OUT / f'latest.json'

    if args.report:
        if not latest.exists():
            print('no run yet — drop --report')
            return 2
        data = json.loads(latest.read_text())
    else:
        import logging
        import warnings
        logging.disable(logging.INFO)
        warnings.filterwarnings('ignore')
        import arc_agi

        key = load_key()
        arc = arc_agi.Arcade(arc_api_key=key) if key else arc_agi.Arcade()
        envs = arc.get_environments()
        print(f'  {len(envs)} environments ({"keyed" if key else "anonymous"})')
        games = [e.game_id for e in envs[:args.games]]

        # A CLEAN CONTEXT STORE PER INVOCATION, and this is a methodological point rather
        # than a tidy-up. laserbrain keeps CROSS-SESSION memory: a context opened before and
        # never closed makes the judgment layer say `abandon`, correctly. Across three smoke
        # runs of the same games that memory built up, and `abandon` then fired from step 3
        # of every run — a true statement about my repeated testing, and a measurement of
        # nothing. Precision has to be computed on runs judged for themselves.
        import shutil
        cfg = BENCH_HOME / 'config'
        if cfg.exists():
            shutil.rmtree(cfg)
        cfg.mkdir(parents=True, exist_ok=True)

        runs = []
        for n, g in enumerate(games, 1):
            t0 = time.time()
            r = play(arc, g, args.steps, args.seed + n, args.distance)
            runs.append(r)
            fires = sum(1 for s in r['trace'] if s['judgment'])
            print(f'  [{n}/{len(games)}] {g}  {r["steps"]} steps  '
                  f'{r["distinct_states"]} states  levels {r["levels"]}  '
                  f'{fires} judgment fire(s)  {time.time() - t0:.0f}s')
        data = {'runs': runs, 'tail': args.tail, 'distance': args.distance}
        latest.write_text(json.dumps(data))

    runs, tail = data['runs'], data.get('tail', args.tail)
    s = score(runs, tail)

    print()
    print(f'  {len(runs)} runs, {sum(r["steps"] for r in runs)} steps, '
          f'{sum(r["distinct_states"] for r in runs)} distinct states reached')
    print(f'  levels completed: {sum(r["levels"] for r in runs)}')
    print()
    print('  "you are going nowhere" — was it right?')
    print('  a fire is correct if the agent reached NO new state in the rest of the run;')
    print(f'  fires with fewer than {tail} steps left are dropped as unfalsifiable.\n')
    for label in ('reading', 'judgment'):
        b = s[label]
        print(f'    {label}: {b["total"]} scorable fire(s)')
        if not b['by_verdict']:
            print('      none fired')
        for v, d in sorted(b['by_verdict'].items(), key=lambda kv: -kv[1]['n']):
            p = 100 * d['right'] / d['n']
            print(f'      {v:22} {d["right"]:3}/{d["n"]:<3} correct  {p:5.1f}%   '
                  f'mean new states after: {d["after"] / d["n"]:.1f}')
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
