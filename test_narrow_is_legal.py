#!/usr/bin/env python3
"""Obeying the instrument must not be a fault, and the union must stay a union.

WHY, AND IT WAS FOUND BY TAKING THE ADVICE RATHER THAN WATCHING IT

On 2026-08-05 an agent playing ARC-AGI-3 was told to follow laserbrain's counsel. It said:

    narrow — "The goal is too large to close in one move. Name the smallest piece that
              would genuinely reduce the distance and make that the goal."

The agent did exactly that. The next reading was `goal-drift`, goal_score 0.00, Φ 0.53 —
and the counsel repeated. The instrument was faulting an agent for doing the one thing it
had just instructed. No amount of observing the verdicts would have surfaced that; it only
appears when someone obeys them.

Two defects, both now fixed and both pinned here:

  the counsel never named the mechanism   `parent_goal` makes narrowing legal and already
                                          worked. It simply went unmentioned at the one
                                          moment an agent needs it.
  (a second "defect" that was not one)    parent_overlap reads None on an accepted parent,
                                          which looked like the number being thrown away.
                                          It is deliberate: None = no declaration, a number
                                          = declared and REJECTED. Changing it broke
                                          test_parent_rejection, which pins exactly that
                                          distinction. Recorded here because the mistake is
                                          easy to repeat by reading the branch alone.

WHAT MUST NOT REGRESS

  narrowing WITH a declared parent   -> excursion, and parent_overlap is a number
  narrowing WITHOUT one             -> still goal-drift. The fix must not make drift
                                       unreachable; an undeclared goal change is still
                                       drift and the corpus depends on it staying so.
  the counsel names parent_goal     -> or the trap returns for the next agent that obeys

AND THE UNION, which is the only thing that measured well on that benchmark: 5 episodes
against 3 for the agent alone and 2 for the instrument alone, 4 steps of lead over 26.
fires_first() must keep both sources and prefer neither.
"""
import pathlib
import sys
import tempfile
import os

os.environ['LASERBRAIN_HOME'] = tempfile.mkdtemp(prefix='lb-narrow-')
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'laserbrain-sdk'))

from laserbrain import Harness, fires_first                        # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


BIG = 'complete a level of the game'
SMALL = 'close the gap between the player and the target'


def run(n=15):
    h = Harness()
    for _ in range(n):
        h.check(BIG, 'advancing', 6)
    return h


print('narrowing is legal when the parent is declared\n')
v = run().check(SMALL, 'advancing', 5, parent_goal=BIG)
check('declared parent -> excursion, not drift', v.reason == 'excursion', v.reason)
# parent_overlap is a REJECTION channel, and this was checked the wrong way round first.
# None means no declaration was made; a NUMBER means one was made, measured and rejected.
# An accepted parent must therefore leave it None — overloading it to also carry the
# accepted score would make "absent" and "rejected" indistinguishable, which is the
# distinction test_parent_rejection exists to keep. Acceptance is already reported: the
# reason is `excursion` rather than `goal-drift`.
check('  and parent_overlap stays None on ACCEPTANCE', v.parent_overlap is None,
      f'{v.parent_overlap!r} — a number here would mean the declaration was rejected')
check('  and it is not drifting', not v.drifting)

print()
print('but an UNDECLARED goal change is still drift — the fix must not erase the rule')
v2 = run().check(SMALL, 'advancing', 5)
check('no parent -> goal-drift', v2.reason == 'goal-drift', v2.reason)
check('  and it IS drifting', bool(v2.drifting))

print()
print('and the counsel names the mechanism, so obeying it is not a trap')
# `narrow` needs a SLOWLY-CLOSING run, not a flat one. A flat distance gives `repeating`
# at 3 and `abandon` at 12 — the verdict for a run that is not moving at all. `narrow` is
# for a run that IS closing and will not close in time, which is the case its counsel
# describes and the case the ARC agent was in. Probing a flat run for it, as the first
# version of this did, simply never sees it.
seen = None
h = Harness()
for d in (9, 9, 8, 8, 8, 7, 7, 7, 7, 6, 6, 6, 6, 6, 6):
    h.check(BIG, 'advancing', d)
    c = h.phronesis()
    if c.get('verdict') == 'narrow':
        seen = c.get('counsel') or ''
        break
if seen is None:
    check('narrow fires somewhere in a flat run', False, 'never saw the verdict')
else:
    check('narrow fires', True)
    check('  and its counsel names parent_goal', 'parent_goal' in seen, seen[:78])

print()
print('the union keeps both sources and prefers neither')
TRACE = [                       # the shape the ARC session files store
    {'step': 1, 'progress': 'advancing', 'reason': 'grounded'},
    {'step': 8, 'progress': 'stuck', 'reason': 'self-report:stuck'},
    {'step': 9, 'progress': 'advancing', 'reason': 'advancing'},
    {'step': 11, 'progress': 'advancing', 'reason': 'stalled'},
    {'step': 12, 'progress': 'circling', 'reason': 'self-report:circling'},
    {'step': 14, 'progress': 'advancing', 'reason': 'advancing'},
    {'step': 18, 'progress': 'advancing', 'reason': 'stalled'},
    {'step': 21, 'progress': 'circling', 'reason': 'self-report:circling'},
]
ep = fires_first(TRACE)
steps = [e['step'] for e in ep]
check('every episode is kept', steps == [8, 11, 12, 18, 21], str(steps))
by = {e['step']: e['first'] for e in ep}
check('  the agent is credited where it was first', by.get(8) == 'agent', str(by.get(8)))
check('  the instrument where IT was first', by.get(11) == 'instrument' and by.get(18) == 'instrument',
      f"11={by.get(11)} 18={by.get(18)}")
check('  and the union beats either alone', len(ep) > max(
    sum(1 for e in ep if e['first'] == 'agent'),
    sum(1 for e in ep if e['first'] == 'instrument')),
    f'{len(ep)} union')
lead = next((e['lead'] for e in ep if e['step'] == 18), None)
check('  lead time is reported', lead == 3, f'step 18 led by {lead}')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:3]))
    sys.exit(1)
print('  PASS — obeying the instrument is no longer a fault, a declared parent is')
print('  measurable, an undeclared change is still drift, and the union keeps both voices.')
