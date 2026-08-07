#!/usr/bin/env python3
"""Label drift fires from the run's own later steps, by rule rather than by opinion.

    python3 label-fires.py            # show what it would write, change nothing
    python3 label-fires.py --write    # append the labels

WHY A RULE AND NOT A JUDGEMENT
------------------------------
The corpus held 1 label against 218 fires, so precision was uncomputable and every
threshold in the calibration was tuned on how OFTEN a rule fires rather than on whether
it fired on the right thing. The obvious fix — sit down and judge them — produces the
weakest evidence there is: an agent grading the instrument that judged it, on its own
runs, from memory. `mark_verdict` already records `by` precisely so that kind of label
can be discounted.

So this labels by a rule instead. Not better than a human call, but different in the way
that matters: reproducible, auditable, and wrong in the same direction every time rather
than wrong in whichever direction the labeller was feeling. Every row it writes carries
`by: rule:<name>` and the rule's own reasoning in `why`, so nothing here can be mistaken
for a considered opinion, and a later human pass can overwrite any of it — mark_verdict
allows re-labelling and reports what it replaced.

THE RULE, AND WHAT IT ASSUMES
-----------------------------
A goal-drift fire means "your goal no longer matches the one you started with". The fire
is USEFUL if the agent had wandered and needed to come back, and a FALSE ALARM if the
goal legitimately moved — a redirect the instrument has no way to distinguish from drift,
because `parent_goal` and the user-turn signal both go unspelled.

The run itself answers this, after the fact:

  RETURNED   a later step comes back to the ground the fire was measured against
             (overlap >= goal_min). The agent went back. -> useful
  CARRIED ON the run continues on the new goal AND closes distance from the fire to the
             end of the run. It was real work that went somewhere. -> false
  NEITHER    no return, no closure. The rule declines. -> unclear

The assumption worth stating: "closed distance" is the agent's own reported distance, so
CARRIED_ON inherits whatever the agent claimed about its progress. That is exactly the
unanchored half of `anchored`, and it is why this rule can be wrong. It is recorded in
`why` on every row so the weakness travels with the label instead of being lost.

Only fires are labelled. A quiet reading interrupted nothing, so there is nothing to
judge — and precision is a statement about fires alone. This corpus cannot yield d-prime
at any point in the future, because nothing collects the other half of the matrix.
"""
import json
import os
import pathlib
import sys
from collections import defaultdict

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
import _root                                                       # noqa: E402

DRIFT = pathlib.Path(os.environ.get('LASERBRAIN_DRIFT_LOG')
                     or _root.config('drift-log.jsonl'))
OUT = pathlib.Path(os.environ.get('LASERBRAIN_OUTCOMES_LOG')
                   or _root.config('verdict-outcomes.jsonl'))
GOAL_MIN = 0.30
RULE = 'rule:returned-or-closed@1'

sys.path.insert(0, str(pathlib.Path.home() /
                       'Library/Mobile Documents/com~apple~CloudDocs/phronesis/laserbrain-sdk'))
try:
    from laserbrain import norm
except Exception:
    print('  cannot import laserbrain.norm — the rule needs the same normaliser the '
          'instrument used, not a second one')
    sys.exit(1)


def jaccard(a, b):
    u = a | b
    return len(a & b) / len(u) if u else 1.0


def load(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


rows = load(DRIFT)
rows.sort(key=lambda r: (r.get('run') or '', r.get('step') or 0))
runs = defaultdict(list)
for r in rows:
    runs[r.get('run')].append(r)

already = {(l.get('run'), l.get('step')) for l in load(OUT)}

# The ground is the first goal of a run and moves on every reground — the same way the
# instrument tracks it. Reconstructing it any other way measures against the wrong thing.
labels, counts = [], defaultdict(int)
for run, seq in runs.items():
    ground = None
    for i, r in enumerate(seq):
        goal = r.get('goal')
        if ground is None and goal:
            ground = goal
        if r.get('reason') == 'reground' and goal:
            ground = goal
            continue
        if not (r.get('drifting') and r.get('reason') == 'goal-drift' and goal and ground):
            continue
        if (run, r.get('step')) in already:
            counts['already labelled'] += 1
            continue

        g = norm(ground)
        later = seq[i + 1:]
        returned = next((s for s in later
                         if s.get('goal') and jaccard(norm(s['goal']), g) >= GOAL_MIN), None)
        d_here = r.get('distance')
        d_end = next((s.get('distance') for s in reversed(later)
                      if s.get('distance') is not None), None)
        closed = (d_here is not None and d_end is not None and d_end < d_here)

        if returned is not None:
            outcome, why = 'useful', (
                f'RULE {RULE}: the run came back to its ground at step '
                f'{returned.get("step")} (overlap >= {GOAL_MIN}). The fire preceded a return.')
        elif closed:
            outcome, why = 'false', (
                f'RULE {RULE}: no return to ground; the run carried on and distance fell '
                f'{d_here} -> {d_end} by the end. A redirect the instrument could not tell '
                f'from drift. NOTE: distance is the agent\'s own report, so this label '
                f'inherits an unanchored claim.')
        else:
            outcome, why = 'unclear', (
                f'RULE {RULE}: no return to ground and no distance closed '
                f'({d_here} -> {d_end}). The rule declines rather than guessing.')

        counts[outcome] += 1
        labels.append({
            'ts': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
                  .isoformat().replace('+00:00', 'Z'),
            'run': run, 'agent': r.get('agent'), 'step': r.get('step'),
            'reason': r.get('reason'), 'phi': r.get('phi'),
            'outcome': outcome, 'why': why, 'by': RULE, 'retroactive': True,
        })


# ── RULE 2 · the other verdicts, each judged on what it actually claims ────────
#
# `returned-or-closed` only fits goal-drift, which claims the goal moved. The rest claim
# different things and need different evidence, and in every case the only non-circular
# evidence is what happened AFTER the window the detector could see.
#
#   oscillating       claims the agent returned to the same goals in a repeating ORDER.
#                     That is checkable directly: recompute the period over the ground
#                     trail. 14 of 16 have no such period — they fired on the fallback
#                     that reads the VERDICT sequence, which the grammar added the
#                     ground-first check precisely to stop relying on. A reading cycle
#                     over a run that then closes distance is a rhythm, not a loop.
#
#   stalled           claims distance stopped falling. The detector saw a 4-step window;
#   self-report:*     if distance falls shortly after, it fired on a plateau and the work
#                     was fine. If it stays flat with steps left to observe, the condition
#                     was real.
#
# Same inherited weakness as rule 1, stated again because it does not go away: `distance`
# is the agent's own report. These labels are only as good as that claim.
RULE2 = 'rule:claim-borne-out@1'
AFTER = 4

for run, seq in runs.items():
    for i, r in enumerate(seq):
        reason = r.get('reason')
        if not (r.get('drifting') and reason in
                ('oscillating', 'stalled', 'self-report:stuck', 'self-report:circling')):
            continue
        if (run, r.get('step')) in already:
            continue
        later = seq[i + 1:]
        d_here = r.get('distance')
        ds = [s.get('distance') for s in later[:AFTER] if s.get('distance') is not None]
        fell = d_here is not None and ds and min(ds) < d_here

        if reason == 'oscillating':
            trail = ['|'.join(sorted(norm(s.get('goal') or ''))) for s in seq[:i + 1]]
            period = None
            for pp in range(2, 7):
                if len(trail) >= 2 * pp and all(trail[-k] == trail[-k - pp] for k in range(1, pp + 1)):
                    period = pp
                    break
            if period:
                outcome, why = 'useful', (
                    f'RULE {RULE2}: the ground trail genuinely repeats with period {period} — '
                    f'the agent did return to the same goals in order.')
            elif fell:
                outcome, why = 'false', (
                    f'RULE {RULE2}: no repeating period in the ground trail, and distance fell '
                    f'{d_here} -> {min(ds)} within {AFTER} steps. The cycle was in the READINGS '
                    f'over a run that was moving — a rhythm, not a loop.')
            else:
                outcome, why = 'unclear', (
                    f'RULE {RULE2}: no ground cycle, and no distance movement to judge by.')
        else:
            if fell:
                outcome, why = 'false', (
                    f'RULE {RULE2}: the named condition did not hold — distance fell '
                    f'{d_here} -> {min(ds)} within {AFTER} steps of the fire. NOTE: distance is '
                    f'the agent\'s own report.')
            elif len(later) >= 2:
                outcome, why = 'useful', (
                    f'RULE {RULE2}: distance did not improve over the {len(later[:AFTER])} step(s) '
                    f'after the fire — the condition it named was real.')
            else:
                outcome, why = 'unclear', (
                    f'RULE {RULE2}: fewer than 2 later steps; nothing to observe.')

        counts[f'{reason} -> {outcome}'] += 1
        counts[outcome] += 1
        labels.append({
            'ts': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
                  .isoformat().replace('+00:00', 'Z'),
            'run': run, 'agent': r.get('agent'), 'step': r.get('step'),
            'reason': reason, 'phi': r.get('phi'),
            'outcome': outcome, 'why': why, 'by': RULE2, 'retroactive': True,
        })

print(f'  corpus      {len(rows)} readings, {sum(1 for r in rows if r.get("drifting"))} fires')
print(f'  rules       {RULE}\n              {RULE2}')
print(f'  labelling   {len(labels)} goal-drift fire(s)\n')
for k in sorted(counts, key=lambda k: (k in ('useful','false','unclear','already labelled'), k)):
    if counts[k]:
        print(f'    {k:<18}{counts[k]:>5}')
judged = counts['useful'] + counts['false']
if judged:
    print(f'\n  precision if written: {counts["useful"]}/{judged} = '
          f'{counts["useful"] / judged * 100:.1f}%')

if '--write' in sys.argv:
    with OUT.open('a') as fh:
        for row in labels:
            fh.write(json.dumps(row) + '\n')
    print(f'\n  wrote {len(labels)} label(s) -> {OUT}')
else:
    print('\n  dry run — nothing written. Pass --write to append.')
