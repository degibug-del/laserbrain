#!/usr/bin/env python3
"""test_frozen.py — pins the published instrument's NUMBERS, not just its behaviour.

WHY. On 2026-07-24 the existing suite was mutation-tested. Two mutations passed it
untouched:

    goal-drift threshold  0.30 -> 0.45     0 suites went red
    metric weights  0.5/0.3/0.2 -> 0.2/0.3/0.5   0 suites went red

Only disabling detection outright turned anything red. So the suite could tell that the
detector was broken, and could not tell that it had been RECALIBRATED — which is the one
change the product forbids. laserbrain's whole claim is a reference that does not move;
"Agents learn. laserbrain does not." An instrument whose calibration can drift silently
through a green build is not a fixed reference, it is an unfixed one nobody is watching.

WHAT THIS IS. A characterisation test. The constants below were read off the
implementation as it stands at v0.3.4, not derived from theory — that is the point. It
does not argue the numbers are correct. It argues they are DELIBERATE: change them and
this test goes red, so the change has to be made on purpose, versioned, and explained.
That is the same discipline drift.ts carries at 6b483de7.

If you are here because this test failed: you changed the published instrument. Either
put it back, or change these constants too and re-version — and say so in CHANGELOG.md.
"""
from laserbrain import _displacement, _GOAL_MIN, _ECHO_MIN, _PROG_WIN, Calibration, PUBLISHED

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


# ── the published calibration, pinned ────────────────────────────────────────
# v0.4.0 made these settable. That is the point of the object, and it is exactly why
# they still have to be pinned: `Calibration()` with no arguments must keep meaning the
# instrument that was published, or "dynamic" quietly becomes "drifted".
show('the default calibration IS the published one', PUBLISHED.is_published, repr(PUBLISHED))
show('goal_min default is 0.30', PUBLISHED.goal_min == 0.30)
show('self_report_min default is 0.15', PUBLISHED.self_report_min == 0.15)
show('stall_window default is 4', PUBLISHED.stall_window == 4)
show('weights default to 0.5/0.3/0.2',
     (PUBLISHED.w_goal, PUBLISHED.w_distance, PUBLISHED.w_progress) == (0.5, 0.3, 0.2))

# and the dynamism is real, not decorative
alt = Calibration(goal_min=0.9)
show('a custom calibration is NOT the published one', not alt.is_published)
show('a custom calibration actually changes Φ',
     abs(_displacement('refactor parser', 'advancing', 5,
                       {'goal': 'ship billboard', 'dist': 5.0, 'progress': 'advancing'},
                       cal=Calibration(w_goal=0.8, w_distance=0.1, w_progress=0.1)) - 0.8) < 1e-9)
try:
    Calibration(w_goal=0.9, w_distance=0.9, w_progress=0.9)
    show('weights that do not sum to 1 are rejected', False)
except ValueError:
    show('weights that do not sum to 1 are rejected', True)

# ── the legacy module constants, pinned ──────────────────────────────────────
show('goal-drift anchor threshold is 0.30', _GOAL_MIN == 0.30, f'_GOAL_MIN={_GOAL_MIN}')
show('echo floor is 0.25', _ECHO_MIN == 0.25, f'_ECHO_MIN={_ECHO_MIN}')
show('progress window is 3', _PROG_WIN == 3, f'_PROG_WIN={_PROG_WIN}')

# ── the weights, pinned through golden Φ values ──────────────────────────────
# Each case isolates one term, so a reweighting cannot cancel out across them.
G = {'goal': 'ship the billboard', 'dist': 5.0, 'progress': 'advancing'}

cases = [
    # (name, goal, progress, distance, expected Φ, what it isolates)
    ('identical state scores 0',
     'ship the billboard', 'advancing', 5, 0.0, 'the origin'),
    ('distance term alone: |5-0|/10 * 0.3',
     'ship the billboard', 'advancing', 0, 0.15, 'the 0.3 distance weight'),
    ('progress term alone',
     'ship the billboard', 'stuck', 5, 0.2, 'the 0.2 progress weight'),
    ('goal term alone: disjoint goal, jac=1',
     'refactor the parser', 'advancing', 5, 0.5, 'the 0.5 goal weight'),
    ('all three at once',
     'refactor the parser', 'stuck', 0, 0.85, 'that the terms sum, not max'),
]
for name, goal, prog, dist, want, isolates in cases:
    got = _displacement(goal, prog, dist, G)
    show(name, abs(got - want) < 1e-9, f'Φ={got:.4f} (want {want}) — {isolates}')

# ── the boundary itself flips the verdict ────────────────────────────────────
# Straddle _GOAL_MIN rather than trusting that a constant is merely present: a
# threshold that is defined but never compared against would pass the checks above.
from laserbrain import Harness

def anchor_of(first, later):
    """The verdict for `later` against a ground of `first`."""
    h = Harness()
    h.check(goal=first, progress='advancing', distance=5)
    return h.check(goal=later, progress='advancing', distance=5)

# 4 shared words of 5+5-4=6 union -> jaccard 0.667, comfortably above 0.30
near = anchor_of('build the sky billboard now', 'build the sky billboard today')
# no shared vocabulary at all -> anchor 0.0, below 0.30
far = anchor_of('build the sky billboard now', 'refactor parser internals entirely')

show('a goal restated near its ground does NOT read as goal-drift',
     not (near.reason == 'goal-drift'), f'reason={near.reason}')
show('a goal replaced wholesale DOES read as goal-drift',
     far.reason == 'goal-drift', f'reason={far.reason}')

# ── a ground survives somebody ELSE's reset ──────────────────────────────────
#
# Found by dogfooding on 2026-08-16, in a session that spawned subagents. In-process
# subagents share one MCP server process, so they share one `_state` and therefore one
# ground. Every agent is also told by its own instructions to call reset_task when it
# begins a genuinely new task — and a subagent's task is always new. reset_task deleted
# the live ground unconditionally, so a child wiped its PARENT's reference, and the
# parent's next check with a BYTE-IDENTICAL goal string came back goal-drift at 0.02,
# then escalated to `wrong-problem` and told a correctly-working agent to stop.
#
# This belongs in test_frozen.py rather than test_mcp_server.py because it is not an MCP
# detail: PROOF's three adjectives are fixed, findable and UNCHANGEABLE, and an
# unauthenticated delete of another agent's ground fails the third one. The published
# claim is "Agents learn. laserbrain does not" — a reference any caller can destroy is
# not a reference.
#
# THIS CAN FAIL: restore the one-line `_state['harness'] = None` body of _reset_task and
# the first assertion below goes red, reproducing the original 0.02 exactly.
from laserbrain import mcp as _mcp                                          # noqa: E402

_PARENT = 'Restore the paid laserbrain tiers: Group $29 and Pro $400, rekey PAYMENT_LINKS'
_CHILD = 'Sweep the workers directory for every price constant and tier definition'
_OTHER = 'Write the employee handbook and index it'


def _fresh():
    _mcp._state['harness'] = None
    _mcp._state['checks'] = []
    _mcp._state['suspended'] = []


_fresh()
_mcp._check_state({'goal': _PARENT, 'distance': 7})       # parent grounds
_mcp._reset_task({})                                      # a CHILD starts new work
_child = _mcp._check_state({'goal': _CHILD, 'distance': 5})
_back = _mcp._check_state({'goal': _PARENT, 'distance': 6})

show("a child's reset_task does not destroy the parent's ground",
     _back['reason'] != 'goal-drift', f"reason={_back['reason']} score={_back['ground_score']}")
show('the parent is told its ground was resumed, not moved silently',
     _back.get('resumed_ground') == _PARENT)
show('the child still gets a ground of its own',
     _child['reason'] == 'grounded', f"reason={_child['reason']}")

# The child must be able to come back to ITS ground too, or the fix has merely moved the
# theft one level down.
_childback = _mcp._check_state({'goal': _CHILD, 'distance': 4})
show('the child reclaims its own ground in turn',
     _childback['reason'] != 'goal-drift', f"reason={_childback['reason']}")

# Resume is a COMPARISON, not a threshold: an unrelated new task after a reset must still
# open a fresh ground rather than being handed whichever suspended one it least mismatches.
_fresh()
_mcp._check_state({'goal': _PARENT, 'distance': 7})
_mcp._reset_task({})
_new = _mcp._check_state({'goal': _OTHER, 'distance': 8})
show('a genuine redirect still grounds fresh, not resumed',
     _new['reason'] == 'grounded' and 'resumed_ground' not in _new,
     f"reason={_new['reason']}")

# And the suspended list must stay bounded, or a long session leaks harnesses.
_fresh()
for _i in range(_mcp.MAX_SUSPENDED + 5):
    _mcp._check_state({'goal': f'task number {_i} doing thing {_i}', 'distance': 5})
    _mcp._reset_task({})
show('suspended grounds stay bounded',
     len(_mcp._state['suspended']) <= _mcp.MAX_SUSPENDED,
     f"held={len(_mcp._state['suspended'])} max={_mcp.MAX_SUSPENDED}")
_fresh()

print('\n  ' + ('PASS — the instrument is where it was published.' if ok else
                'FAIL — the published instrument moved. Re-version it deliberately or put it back.'))
raise SystemExit(0 if ok else 1)
