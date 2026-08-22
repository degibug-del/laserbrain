#!/usr/bin/env python3
"""Fields that were accepted and then dropped on the floor.

Every failure here shipped, and the suite was green throughout. They share one shape: an
argument the signature advertises, discarded before it reaches the engine. Nothing raises,
nothing logs, and the verdict comes back confident and wrong. The oscillation case at the
bottom is the same shape one level up: a counter read from a list that could never hold the
value, so the judgment standing on it had never once fired.

So each check asserts on the OBSERVABLE verdict, never on the plumbing. A test that
checked "parent_goal was forwarded" would pass against a mock that forwards it into a
drawer; these check that the verdict itself changes.
"""
import os
import tempfile

# BEFORE importing laserbrain. phronesis() reads the persistent context store, and a goal
# seen in an earlier run changes the verdict — 'opened in 2 earlier sessions' pre-empts the
# judgment under test with `abandon`. Caught by running this file twice.
os.environ['LASERBRAIN_HOME'] = tempfile.mkdtemp(prefix='lb-carried-')

import asyncio

import laserbrain as lb
from laserbrain.adapters import guard, dict_extract, _unpack

ok = True

BRIEF = 'reconcile the March statement against the ledger'
SUBTASK = 'check which statement lines have no matching ledger entry'
ELSEWHERE = 'write a poem about the sea'


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


# ── acheck carried user_turn ──────────────────────────────────────────────────
# acheck accepted user_turn and never passed it, so the async path could not reground:
# acheck(user_turn=True) returned goal-drift where check(user_turn=True) returned reground.

sync = lb.Harness()
sync.check(goal=BRIEF, progress='advancing', distance=6)
v_sync = sync.check(goal=ELSEWHERE, progress='advancing', distance=5, user_turn=True)

_a = lb.Harness()


async def _async_pair():
    await _a.acheck(goal=BRIEF, progress='advancing', distance=6)
    return await _a.acheck(goal=ELSEWHERE, progress='advancing', distance=5, user_turn=True)


v_async = asyncio.run(_async_pair())
show('sync reference: user_turn regrounds', v_sync.reason == 'reground', v_sync.reason)
show('acheck regrounds like check', v_async.reason == v_sync.reason,
     f'async said {v_async.reason}, sync said {v_sync.reason}')

# `last` exists so Operator(harness=...) can read whether the agent is on its ground.
# acheck never set it, so an async loop handed the operator None forever.
_h = lb.Harness()
asyncio.run(_h.acheck(goal=BRIEF, progress='advancing', distance=6))
show('acheck sets .last', _h.last is not None and _h.last.reason == 'grounded',
     f'last={_h.last.reason if _h.last else None}')


# ── inferred kept the rest of the Verdict ─────────────────────────────────────
# inferred=True marks the LEAST trustworthy reading. Rebuilding the Verdict from four
# positional fields let every other field fall back to its default, so it came back
# reporting anchored=1.0 — the most confident value available — plus a dropped
# laserscore and goal_score.

_p = lb.Harness()
_p.check(goal=BRIEF, progress='advancing', distance=6)
plain = _p.check(goal=SUBTASK, progress='advancing', distance=4)

_i = lb.Harness()
_i.check(goal=BRIEF, progress='advancing', distance=6)
inferred = _i.check(goal=SUBTASK, progress='advancing', distance=4, inferred=True)

show('inferred keeps anchored', inferred.anchored == plain.anchored,
     f'inferred={inferred.anchored} spelled={plain.anchored}')
show('inferred keeps laserscore', inferred.laserscore == plain.laserscore)
show('inferred keeps goal_score', inferred.goal_score == plain.goal_score)
show('inferred still says so', 'inferred' in inferred.advice)


# ── adapters carried parent_goal ──────────────────────────────────────────────
# No adapter passed parent_goal, so `excursion` was unreachable from every framework
# integration and a legitimate sub-task read as drift.

@guard
def _sub(_):
    return {'goal': SUBTASK, 'progress': 'advancing', 'distance': 3, 'parent_goal': BRIEF}


_sub.harness.check(goal=BRIEF, progress='advancing', distance=6)
_v = _sub(None)['laserbrain']
show('adapter can reach excursion', _v.reason == 'excursion', _v.reason)


# The rescue must REQUIRE a declared parent. Without one this is still a departure —
# otherwise the fix would just suppress drift detection across every adapter.
@guard
def _away(_):
    return {'goal': ELSEWHERE, 'progress': 'advancing', 'distance': 3}


_away.harness.check(goal=BRIEF, progress='advancing', distance=6)
_v2 = _away(None)['laserbrain']
show('adapter without a parent still drifts', _v2.reason == 'goal-drift', _v2.reason)

# Every extractor written before parent_goal existed returns three values, including every
# one a user has already passed in. They must keep working untouched.
show('three-value extractors still work',
     _unpack(lambda x: ('a goal', 'advancing', 4), None) == ('a goal', 'advancing', 4, None))
show('four-value extractors carry the parent',
     _unpack(lambda x: ('a goal', 'advancing', 4, 'the parent'), None)[3] == 'the parent')
show('dict_extract reads parent_goal',
     dict_extract({'goal': 'g', 'parent_goal': 'p'})[3] == 'p'
     and dict_extract({'goal': 'g'})[3] is None)

# ── the oscillation counter reached its consumer ──────────────────────────────
# phronesis() computed `reasons.count('oscillating')` over a trace that stores the READING
# and never the meta-verdict — deliberately, so the cycle is not erased by the verdict it
# produced. Both decisions were right; read together they left `wrong-problem` unreachable.

A, B = 'audit the quarterly freight variance workbook', 'pull the carrier invoice extract'

_osc = lb.Harness()
for _i in range(10):
    # user_turn=True — each switch is a legitimate REGROUND. Without it every switch is a
    # goal-drift and the drift/reground branch above pre-empts this one, which is why the
    # first version of this test passed while reading the wrong branch's `because`.
    _osc.check(goal=(A if _i % 2 == 0 else B), progress='advancing', distance=5,
               user_turn=True)
_j = _osc.phronesis()
show('oscillation is counted', _osc._run._osc_fires == 1, f'fires={_osc._run._osc_fires}')
show('wrong-problem is reachable', _j.get('verdict') == 'wrong-problem', _j.get('verdict'))
show('and it is the OSCILLATION branch, not the drift branch',
     'repeating cycle' in (_j.get('because') or ''), (_j.get('because') or '')[:52])

# `pace <= 0` is the guard: a run that is measurably closer has not come back anywhere.
_close = lb.Harness()
for _i, _d in enumerate([9, 8, 7, 6, 5, 4, 3, 2, 1, 1]):
    _close.check(goal=(A if _i % 2 == 0 else B), progress='advancing', distance=_d,
                 user_turn=True)
show('a closing run is not called wrong-problem',
     _close.phronesis().get('verdict') != 'wrong-problem',
     _close.phronesis().get('verdict'))

# ── the whole-run distance series agrees with the others ──────────────────────
# dist_all stored the RAW distance argument while dist_hist, the audit chain and laserscore
# all normalise through _asdist. A caller passing '9' as a string — supported everywhere
# else, and what the MCP and adapter paths naturally produce — left dist_all empty, so
# run_pace took its `else 0` arm and the branch fired "the distance is not falling" on a run
# that had closed 9 to 1. The false counsel the measure exists to prevent, produced by the
# line that records it. Four series, one value: they must agree.

_str = lb.Harness()
for _i, _d in enumerate(['9', '8', '7', '6', '5', '4', '3', '2', '1', '1']):
    _str.check(goal=(A if _i % 2 == 0 else B), progress='advancing', distance=_d,
               user_turn=True)
show('string distances reach dist_all', _str._run.dist_all == [9, 8, 7, 6, 5, 4, 3, 2, 1, 1],
     str(_str._run.dist_all))
show('and a closing run of them is not called wrong-problem',
     _str.phronesis().get('verdict') != 'wrong-problem', _str.phronesis().get('verdict'))

_clamp = lb.Harness()
for _d in (100, '4', -7):
    _clamp.check(goal=A, progress='advancing', distance=_d)
show('dist_all clamps exactly as dist_hist does',
     _clamp._run.dist_all == _clamp._run.dist_hist,
     f'{_clamp._run.dist_all} vs {_clamp._run.dist_hist}')

_none = lb.Harness()
_none.check(goal=A, progress='advancing', distance=None)
show('an unknown distance stays unknown, not 5', _none._run.dist_all == [],
     str(_none._run.dist_all))

# run_pace measured from da[0] charged a SETPOINT CHANGE as lost ground: close a little on
# one goal, be handed a harder one, close a lot on that — and the run reads as going
# backwards. Measured from the run's worst point instead.
_mirror = lb.Harness()
_mirror.check(goal=A, progress='advancing', distance=3)
_mirror.check(goal=A, progress='advancing', distance=2)
for _i, _d in enumerate([9, 8, 7, 6, 5, 4]):
    _mirror.check(goal=(B if _i % 2 == 0 else A), progress='advancing', distance=_d,
                  user_turn=True)
show('a reground to a HARDER goal is not called wrong-problem',
     _mirror.phronesis().get('verdict') != 'wrong-problem',
     _mirror.phronesis().get('verdict'))

print('\n' + ('ALL CARRIED-FIELD TESTS PASS ✓' if ok else 'SOME FAILED ✗'))
raise SystemExit(0 if ok else 1)
