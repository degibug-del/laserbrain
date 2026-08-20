#!/usr/bin/env python3
"""test_behaviour.py — the calibration, watched by what it DOES.

`./mutate.sh --deep` asked the sharp question on 2026-07-25 and got a bad answer: with
test_frozen.py excluded, five of six mutations survived. Move goal_min from 0.30 to 0.45,
reweight Φ, raise the self-report floor, widen the stall window, deafen the echo detector
— every one of those changed real behaviour and NO test noticed. The entire protection was
one file asserting the numbers by value.

Pinning a constant and testing what it does are different guarantees. A pin says "this is
0.30". This file says "at 0.30 THIS input reads as advancing and THAT one reads as drift",
so the boundary cannot move without a verdict changing somewhere a test is looking.

Every case below straddles a boundary deliberately, with the straddling value measured
rather than guessed. That was the exact hole in the first cross-language parity vectors:
they had no case between 0.30 and 0.45, so the threshold could move anywhere inside that
band undetected.
"""
from laserbrain import Harness, Team, Calibration

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def verdict(first, later, cal=None, progress='advancing', distance=5):
    h = Harness(calibration=cal)
    h.check(goal=first, progress='advancing', distance=5)
    return h.check(goal=later, progress=progress, distance=distance)


# ── goal_min = 0.30 ──────────────────────────────────────────────────────────
# 'ship sky parser' shares 2 stems with the ground of 5 in union: anchor 0.400 (measured).
# Above 0.30, below 0.45 — advancing at the published threshold, drift at 0.45.
BASE = 'ship the sky billboard today'
STRADDLE = 'ship sky parser'

show('at the published goal_min, an anchor of 0.40 is NOT drift',
     verdict(BASE, STRADDLE).reason != 'goal-drift',
     f'reason={verdict(BASE, STRADDLE).reason}')
show('raise goal_min to 0.45 and the SAME input becomes drift',
     verdict(BASE, STRADDLE, Calibration(goal_min=0.45)).reason == 'goal-drift',
     'this is the mutation no behavioural test caught before')
show('a wholly different goal is drift at either setting',
     verdict(BASE, 'refactor parser internals').reason == 'goal-drift')

# ── the Φ weights = 0.5 / 0.3 / 0.2 ──────────────────────────────────────────
h = Harness()
h.check(goal='ship it', progress='advancing', distance=5)
phi_pub = h.check(goal='ship it', progress='stuck', distance=5).phi

h2 = Harness(calibration=Calibration(w_goal=0.2, w_distance=0.3, w_progress=0.5))
h2.check(goal='ship it', progress='advancing', distance=5)
phi_alt = h2.check(goal='ship it', progress='stuck', distance=5).phi

show('the progress term is worth exactly 0.20 of Φ', phi_pub == 0.2, f'Φ={phi_pub}')
show('reshuffling the weights changes that Φ', phi_alt != phi_pub, f'{phi_pub} -> {phi_alt}')

# ── self_report_min = 0.15 ───────────────────────────────────────────────────
# Reporting stuck on the same goal gives Φ=0.20, just above the 0.15 floor, so it fires.
# Raise the floor past 0.20 and the agent's own report is silently ignored.
show('a stuck report at Φ=0.20 is honoured at the published floor',
     verdict('ship it', 'ship it', progress='stuck').reason.startswith('self-report'),
     f"reason={verdict('ship it', 'ship it', progress='stuck').reason}")
show('raise the floor to 0.40 and the same stuck report is IGNORED',
     not verdict('ship it', 'ship it', cal=Calibration(self_report_min=0.40),
                 progress='stuck').reason.startswith('self-report'),
     'the agent says stuck and the harness says nothing')

# ── stall_window = 4 ─────────────────────────────────────────────────────────
def stall_step(window):
    """Which step a flat distance run is first called stalled, or None."""
    h = Harness(calibration=Calibration(stall_window=window))
    h.check(goal='a b c d', progress='advancing', distance=9)
    for i in range(6):
        v = h.check(goal='a b c d', progress='advancing', distance=9)
        if v.reason == 'stalled':
            return i + 2
    return None


show('at window 4, a flat distance stalls on step 5', stall_step(4) == 5, f'step {stall_step(4)}')
show('at window 9, the same flat run never stalls', stall_step(9) is None,
     'a wider window reports the stall far later, or never')

# ── echo_min = 0.25, on teams ────────────────────────────────────────────────
def team_reason(echo_min):
    t = Team('deep-search', 'ship the sky billboard',
             calibration=Calibration(echo_min=echo_min))
    t._dlg.step('a', 'ship the sky billboard now', 5)
    v = None
    for _ in range(5):
        v = t._dlg.step('b', 'ship the sky billboard now', 5)
    return v['reason']


show('at the published echo floor a repeating team reads as echo-spiral',
     team_reason(0.25) == 'echo-spiral', f'reason={team_reason(0.25)}')
show('raise it to 0.90 and echo-spiral is never reported',
     team_reason(0.90) != 'echo-spiral',
     'teams stop detecting the thing teams exist to detect')

# Every other section above reaches PUBLISHED through cal=None. This one never did — both
# cases construct Calibration(echo_min=echo_min) with a literal the TEST chose, so if the
# shipped default itself moved, nothing here would notice; team_reason(0.25) would keep
# passing 0.25 by hand regardless of what PUBLISHED actually held. Proved live: this was
# the one mutation ./mutate.sh caught only via test_frozen.py, never behaviourally.
def default_team_reason():
    t = Team('deep-search', 'ship the sky billboard')          # no calibration kwarg
    t._dlg.step('a', 'ship the sky billboard now', 5)
    v = None
    for _ in range(5):
        v = t._dlg.step('b', 'ship the sky billboard now', 5)
    return v['reason']


show('the UNCONFIGURED default also reads a repeating team as echo-spiral',
     default_team_reason() == 'echo-spiral', f'reason={default_team_reason()}')

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
