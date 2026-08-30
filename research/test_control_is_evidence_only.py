#!/usr/bin/env python3
"""The control decision cannot be moved by what the agent says about itself.

WHY, 2026-08-06

laserbrain was making two decisions with one rule, and they have opposite tolerances for
being wrong:

    LEARNING   what is happening, what to try next — narrow, finish, continue.
               Being wrong costs a suggestion nobody had to take.
    CONTROL    should this run continue at all — stop, verify.
               Being wrong kills a run that was working, or lets a dead one run on.

Prime Intellect's harness, read the same day, keeps them apart without comment:
`shouldAutonomouslyContinue` decides on external quality gates and hard limits, and never
consults the model's opinion of how it is going. laserbrain had no such separation — and
worse, its stopping rules were CONDITIONED on self-report. `abandon` requires `closed <= 0`,
so an agent that types a falling distance is never told to stop, no matter how little it
does. The strongest control verdict in the instrument asked the agent's permission to fire.

THE PROPERTY THIS PINS, and it is one property, stated three ways:

    Hold everything observed fixed. Vary only what was typed. `control` must not move.

That is the entire claim, and it is testable in a way "we thought carefully about the
inputs" is not. If someone later admits `distance` into a control rule — the easiest and
most natural mistake, since every other rule reads it — arm 1 goes red immediately.

WHAT ELSE IS PINNED

  verdict is untouched   the learning decision keeps its rules, thresholds and order.
                         This is an ADDITIVE key; every existing caller reads what it read.
  control is louder      two rules drop a self-report condition their verdict twins carry,
                         so control fires where verdict stays quiet. Arm 3 is that case
                         made concrete: a context four sessions deep, typing a perfect
                         descent, gets `continue` from the verdict and `stop` from control.
                         Where they disagree is where self-report was carrying the decision.
  the dark channel says so
                         most callers never call saw(). Control reports observed=False
                         rather than implying an all-clear it has no evidence for.
  both surfaces          a decision on one front door only is the `unbacked` mistake.
"""
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
HOME = tempfile.mkdtemp(prefix='lb-control-')
os.environ.setdefault('LASERBRAIN_HOME', HOME)
sys.path.insert(0, str(HERE.parent / 'laserbrain-sdk'))

from laserbrain import Calibration, Harness, context_id           # noqa: E402
import laserbrain                                                  # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


GOAL = 'ship the control split'
_n = iter(range(1000))


def run(distances, progresses=None, cal=None, saw=None, goal=None):
    """One run of len(distances) checks. Everything observed is held fixed by the caller;
       `distances` and `progresses` are the self-report and are what the arms below vary.

       EACH RUN GETS ITS OWN GOAL, hence its own context, and that is not cosmetic — the
       first draft of this file reused one goal and the first two arms went red. Every
       Harness() is a new session, sessions accumulate against the context, and by the
       fourth story `prior_sessions` had reached 3 and control was correctly saying stop.
       So the runs differed in something OBSERVED, and the arm was no longer varying
       self-report alone. The code was right and the experiment was confounded, which is
       the same shape as the ARC scoring mistakes: hold fixed what you claim to hold fixed.
    """
    h = Harness(calibration=cal) if cal else Harness()
    g = goal or f'{GOAL} {next(_n)}'
    for i, d in enumerate(distances):
        if saw is not None:
            h.saw('tool', 'pytest', ok=saw[i] if isinstance(saw, list) else saw)
        h.check(g, (progresses[i] if progresses else 'advancing'), d)
    return h.phronesis()


def control_of(p):
    """Decision plus its stated grounds — the whole thing must be invariant, not just the
       word. A rule that reached the same decision by a different route has still moved."""
    return (p['control']['decision'], p['control']['because'])


# ── 1. the property ─────────────────────────────────────────────────────────────────────
print('vary ONLY the self-report; control must not move\n')

stories = {
    'a perfect descent':      [9, 8, 7, 6, 5, 4, 3, 2],
    'dead flat':              [9, 9, 9, 9, 9, 9, 9, 9],
    'going backwards':        [2, 3, 4, 5, 6, 7, 8, 9],
    'thrashing':              [9, 2, 8, 3, 7, 4, 9, 5],
    'already done, honest':   [0, 0, 0, 0, 0, 0, 0, 0],
}
got = {k: control_of(run(v)) for k, v in stories.items()}
base = got['a perfect descent']
for name, c in got.items():
    check(f'{name:24} -> {c[0]}', c == base, '' if c == base else f'differs: {c[0]}')

print()
print('  the same, varying the progress word instead of the number')
words = {w: control_of(run([6] * 8, [w] * 8)) for w in ('advancing', 'stuck', 'circling')}
for w, c in words.items():
    check(f'progress={w:12} -> {c[0]}', c == words['advancing'])

print()
print('  and the verdict DOES move on the same inputs — otherwise this proves nothing')
verdicts = {k: run(v)['verdict'] for k, v in stories.items()}
check('the learning decision is sensitive to self-report',
      len(set(verdicts.values())) > 1, ' / '.join(sorted(set(verdicts.values()))))

# ── 2. what control may read, it does read ──────────────────────────────────────────────
print()
print('the admitted inputs still work — invariance must not be achieved by reading nothing')

b = run([6] * 9, cal=Calibration(max_checks=4))
check('a spent budget stops it', b['control']['decision'] == 'stop', b['control']['because'][:44])

# saw() with a failing outcome: work observed, nothing corroborated.
u = run([9, 8, 7, 6, 5, 4], saw=False)
check('observed work that corroborates nothing -> verify',
      u['control']['decision'] == 'verify', u['control']['because'][:52])

ok = run([9, 8, 7, 6, 5, 4], saw=True)
check('corroborated work -> proceed, and says it is observed',
      ok['control']['decision'] == 'proceed' and ok['control']['observed'] is True,
      f"{ok['control']['decision']} observed={ok['control']['observed']}")

dark = run([6] * 6)
check('nobody called saw() -> observed is False',
      dark['control']['observed'] is False)
check('  and it names the dark channel instead of implying an all-clear',
      'absence of a signal' in dark['control']['because'])

# ── 3. the disagreement, which is the point ─────────────────────────────────────────────
print()
print('where the two decisions part company')

# Seed the store: this context has been opened in four earlier sessions and finished in
# none. Nothing about the CURRENT run's self-report is allowed to answer that.
cid = context_id(GOAL)
store = json.loads(laserbrain.CONTEXTS.read_text()) if laserbrain.CONTEXTS.exists() else {}
store[cid] = {'id': cid, 'tokens': sorted(laserbrain.norm(GOAL)),
              'sessions': ['s1', 's2', 's3', 's4'], 'session_count': 4, 'checks': 40,
              'best_distance': 3, 'outcomes': {}, 'spellings': {}}
laserbrain.CONTEXTS.write_text(json.dumps(store))

p = run([9, 8, 7, 6, 5, 4, 3, 2], goal=GOAL)   # a flawless self-report, fifth session running
check('verdict, reading the typed descent, does not stop it',
      p['verdict'] not in ('abandon', 'over-budget'), p['verdict'])
check('control, reading the session count, does',
      p['control']['decision'] == 'stop', p['control']['because'][:60])
check('  and it says the current run was not consulted',
      'not consulted' in p['control']['because'])

print()
print('a moving goal asks for a reground, not a halt — the decision must stay actionable')
# WHY THIS IS A SEPARATE DECISION, decided on the corpus rather than on taste.
#
# Replaying 231 runs through both decisions (control_vs_verdict.py), EVERY ONE of the 134
# rows where control was louder than the verdict came from the goal-drift arm — the
# recurrence arm produced none, and the budget arm is off by default. So one arm was the
# whole of control's extra reach, and it was answering with the same word as a spent budget.
#
# Control exists to be acted on mechanically. A caller wiring `if decision == 'stop': halt()`
# would have killed all twelve of those runs, and reading them they were working — fixing
# mutate.sh, regenerating a stale fixture, shipping a registry pin. What was wrong was that
# the goal kept moving unannounced: the heaviest ran 40 steps under 37 distinct goals.
#
# So the gate is not "the string changed". It is: a caller may halt on `stop` without
# killing work, which is only true while these two stay distinct.
drifted = Harness()
for g in ('ship the control split', 'rewrite the parser', 'fix the flaky gate',
          'answer an email', 'draw the logo', 'ship the control split again'):
    drifted.check(g, 'advancing', 4)
dp = drifted.phronesis()
check('a goal that keeps moving -> reground', dp['control']['decision'] == 'reground',
      dp['control']['decision'])
check('  and it says the work is not being called worthless',
      'not a judgement that the work is worthless' in dp['control']['because'])
check('  while a spent budget still says stop, so halting on stop stays safe',
      run([6] * 9, cal=Calibration(max_checks=4))['control']['decision'] == 'stop')
check('  and reground is still control SPEAKING, not proceeding',
      dp['control']['decision'] != 'proceed')

print()
print('the reads are published, so a future rule cannot quietly admit a typed input')
allowed = {'checks', 'budget', 'observed_any', 'corroborated',
           'prior_sessions', 'goal_drifts', 'regrounds'}
reads = set(p['control']['reads'])
check('reads exactly the admitted set', reads == allowed,
      ' / '.join(sorted(reads ^ allowed)) or 'exact')

# ── 4. both front doors ─────────────────────────────────────────────────────────────────
print()
print('the server reaches the same decision — one instrument, two front doors')
src = (HERE / 'mcp-server.mjs').read_text()
check('mcp-server.mjs computes control', 'function control(' in src)
check('  and returns it on phronesis', 'control:' in src)
body = src.split('function control(')[1].split('\n}')[0] if 'function control(' in src else 'closed'
check('  and never reads distance to do it', 'closed' not in body and 'dist' not in body)

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — the agent can say anything it likes; the stop decision does not hear it.')
