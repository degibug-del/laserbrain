#!/usr/bin/env python3
"""Replay the whole corpus through both decisions and count where they part.

    python3 control_vs_verdict.py                # the live corpus
    python3 control_vs_verdict.py --log PATH     # some other drift log

WHY, 2026-08-06

0.46.0 split laserbrain's one decision in two: `verdict` learns from the agent's self-report,
`control` decides continuation on evidence the agent cannot author. The changelog for it
makes a claim that has to be checkable, and said so:

    "If the two never disagree, control is ceremony, and the log will say so."

Waiting a month for new rows to accumulate is the slow way to find out. 1,755 rows across
229 runs already exist, and the decision logic is in the package — so the honest test is to
run the real code over the real history rather than to wait.

HOW THE REPLAY IS FAITHFUL, AND WHERE IT IS NOT

Faithful: runs are replayed IN CHRONOLOGICAL ORDER into one private state root, so the
context store accumulates sessions exactly as it did live. That is what makes control's
recurrence arm (`prior_sessions >= 3`) real rather than always-zero — the fourth time a
context appears, it is genuinely the fourth. Goal overlap is recomputed by the harness from
the spelled goals, so the goal-drift arm is real too.

NOT faithful, and this is the load-bearing caveat: `anchored` was never written to the drift
log. It shipped reported-on-every-verdict and recorded nowhere, which is precisely how it
sat structurally broken for its whole life. So the corpus cannot say whether any historical
check was corroborated, and control's evidence arms — `verify`, and the `observed` flag —
are UNMEASURABLE here. They are excluded from the counts rather than assumed either way.
Every number below therefore comes from the count and history arms alone, which makes it a
LOWER BOUND on disagreement: the arms that cannot be replayed can only add more.

The budget arm is off by default and stays off, so it contributes nothing.

WHAT A DISAGREEMENT MEANS. Both answer "should this run continue". `verdict` says stop via
abandon / wrong-problem / over-budget; `control` speaks with anything but `proceed`. A row
where one halts and the other does not is a case where self-report was carrying the
decision — the whole thesis, and the thing worth being wrong about in public.

WHAT IT MEASURED, 2026-08-06, on 231 runs / 1,727 spelled checks:

    verdict stop     control speaks      107
    verdict stop     control proceed       0     control is never the quieter one
    verdict continue control speaks      134     self-report was buying these a pass
    verdict continue control proceed   1486

    disagree on 134 of 1727 rows (7.8%), across 12 runs
    control said:  proceed 1486   reground 241   stop 0

Control is strictly louder, which is what the 0.46.0 changelog claimed and is now measured
rather than argued: there is no row where the verdict halts a run and control lets it live.

TWO FINDINGS THAT CHANGED THE INSTRUMENT.

First: every one of the 134 came from the goal-drift arm. The recurrence arm produced none,
and the budget arm is off by default. So one arm was the whole of control's extra reach.

Second, and the reason 0.48.0 exists: that arm was answering `stop`, the same word as a
spent budget. Control is meant to be acted on mechanically, and a caller wiring
`if decision == 'stop': halt()` would have killed all twelve of those runs — which, read
one by one, were working: fixing mutate.sh, regenerating a stale fixture, shipping a
registry pin. What was wrong with them was never that the work was worthless. It was that
the goal kept moving and nobody said so. The heaviest, run 6718dbcd, ran 40 steps under 37
DISTINCT GOALS — 28 goal-drift readings against 7 declared re-grounds — while reporting a
falling distance the whole way, so `wrong-problem` stayed silent on its `pace <= 0`
condition and the verdict read `continue`.

That arm now answers `reground`. Across the whole corpus control says `stop` zero times,
which is the honest shape of it: the evidence-only decision has plenty to say, and almost
none of what it has to say is "give up".
"""
import argparse
import collections
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
LIVE = pathlib.Path.home() / '.config' / 'laserbrain'      # one-root: live

ap = argparse.ArgumentParser()
ap.add_argument('--log', default=str(LIVE / 'drift-log.jsonl'))
ap.add_argument('--verbose', action='store_true', help='print every disagreement')
args = ap.parse_args()

# ISOLATED, and set before laserbrain is imported — CONTEXTS binds at import time. The
# replay writes a full synthetic history; landing that in the live corpus would corrupt the
# very thing being measured, which is the mistake four scripts made this week.
HOME = tempfile.mkdtemp(prefix='lb-replay-')
os.makedirs(os.path.join(HOME, 'config'), exist_ok=True)
os.makedirs(os.path.join(HOME, 'sessions'), exist_ok=True)
os.environ['LASERBRAIN_HOME'] = HOME
sys.path.insert(0, str(HERE.parent / 'laserbrain-sdk'))

from laserbrain import Harness                                      # noqa: E402

STOPPING = {'abandon', 'wrong-problem', 'over-budget'}


def load_runs(path):
    """Runs in chronological order, each a list of spelled states in step order."""
    runs = collections.OrderedDict()
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            # Judgment rows are a second row on the same step and carry no spelled state.
            if r.get('kind') == 'judgment' or not r.get('run'):
                continue
            if r.get('goal') is None or r.get('distance') is None:
                continue
            runs.setdefault(r['run'], []).append(r)
    for steps in runs.values():
        steps.sort(key=lambda r: r.get('step') or 0)
    # Order the RUNS by their first timestamp, so the context store accumulates sessions in
    # the order they actually happened. Replaying out of order would hand early runs a
    # history they did not have.
    return sorted(runs.items(), key=lambda kv: kv[1][0].get('ts') or '')


runs = load_runs(args.log)
print(f'\n  {len(runs)} runs, {sum(len(s) for s in dict(runs).values())} spelled checks\n')

pairs = collections.Counter()      # (verdict-stops, control-stops)
by_verdict = collections.Counter()
by_control = collections.Counter()
disagreements = []
observed_any = 0

for run_id, steps in runs:
    h = Harness()
    for r in steps:
        prog = r.get('progress') or 'advancing'
        if prog not in ('advancing', 'stuck', 'circling'):
            prog = 'advancing'
        # REPLAY THE REGROUND, or this whole measurement is an artefact.
        #
        # The first version of this file did not, and it produced a headline that flattered
        # the change being measured: 18.3% disagreement, dominated by "the goal failed its
        # overlap check 3 times against 0 declared re-grounds" on runs whose verdict was
        # `finish`. Reading one of them settled it — run 3be8c681 closed its first goal to
        # distance 0 and was handed a second, and the LIVE log records step 7 as `reground`,
        # a healthy declared task change. The replay drove a Harness that was never told the
        # task changed, so a legitimate reground read as drift, three times, and control
        # duly stopped a run that was working.
        #
        # `regrounds` was 0 for every run in the corpus because reset_task was never
        # replayed — a property of the harness, not of control. The same shape as the
        # shared-goal confound in test_control_is_evidence_only and the ARC scoring errors:
        # a number that supports the thing you just built deserves more scrutiny, not less.
        try:
            h.check(r['goal'], prog, r['distance'],
                    user_turn=(r.get('reason') == 'reground'))
        except Exception:
            continue
        try:
            p = h.phronesis()
        except Exception:
            continue
        v, c = p['verdict'], p['control']['decision']
        by_verdict[v] += 1
        by_control[c] += 1
        if p['control']['observed']:
            observed_any += 1
        # `verify` is an evidence-arm answer and cannot fire here — no corroboration data
        # exists in the log. Excluded rather than counted as agreement, which would flatter
        # the result by treating an unmeasurable arm as a quiet one.
        if c == 'verify':
            continue
        # ANY non-proceed is control speaking. Written as `c == 'stop'` first, which would
        # have silently gone to zero the day `reground` split off — and reground is where
        # every disagreement here came from, so this file would have reported "they never
        # disagree, control is ceremony" at exactly the moment it stopped being one.
        vs, cs = v in STOPPING, c != 'proceed'
        pairs[(vs, cs)] += 1
        if vs != cs:
            disagreements.append((run_id, r.get('step'), v, c,
                                  p['control']['because'], r['goal'][:60]))

total = sum(pairs.values())
agree = pairs[(True, True)] + pairs[(False, False)]
print(f'  {"verdict":>22}   {"control":>10}   {"rows":>6}')
print(f'  {"stop":>22}   {"speaks":>10}   {pairs[(True, True)]:>6}')
print(f'  {"stop":>22}   {"proceed":>10}   {pairs[(True, False)]:>6}    control keeps it alive')
print(f'  {"continue":>22}   {"speaks":>10}   {pairs[(False, True)]:>6}    self-report was buying these a pass')
print(f'  {"continue":>22}   {"proceed":>10}   {pairs[(False, False)]:>6}')
print()
if total:
    d = total - agree
    print(f'  disagree on {d} of {total} rows  ({100 * d / total:.1f}%)')
print(f'  evidence channel live on {observed_any} rows — {"as expected, none: anchored was never logged" if not observed_any else "unexpected, investigate"}')
print()
print('  verdicts:', ', '.join(f'{k} {v}' for k, v in by_verdict.most_common()))
print('  control :', ', '.join(f'{k} {v}' for k, v in by_control.most_common()))

if disagreements:
    print()
    print('  where control speaks and the verdict would let the run continue:')
    seen = set()
    for run_id, step, v, c, why, goal in disagreements:
        if c == 'proceed' or run_id in seen:
            continue
        seen.add(run_id)
        print(f'    {run_id[:8]} step {step:>3}  {c:<9} verdict={v:<11} {why[:58]}')
        if len(seen) >= 8 and not args.verbose:
            print(f'    … and {len({d[0] for d in disagreements if d[3] != "proceed"}) - 8} more runs')
            break

print()
print('  Read as a LOWER BOUND: the evidence arms could not be replayed, and they can only')
print('  add disagreement. The budget arm is off by default and contributed nothing.')
