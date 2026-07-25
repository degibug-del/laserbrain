#!/usr/bin/env python3
"""test_kuramoto.py — the gait network, against the things that were actually wrong.

Both faults pinned here were mine, found by running the thing rather than by reading it:

  1. The neck runs at 2ω and a plain sin(θⱼ - θᵢ) coupling cannot lock a 2:1 oscillator to
     a 1:1 one. It drifted forever and pulled the order parameter to 0.68 while every other
     joint was fine — the measurement said "incoherent body" about a broken model.
  2. Wrapping θ into [0,2π) made the neck's reduced phase jump by π once per gait cycle, so
     r flickered between 0.99 and 0.82 for ever. 0.818 is exactly 10/11: ten joints agreeing
     and one pointing backwards.

The most important test in the file is the LAST one, which checks that a network below
critical coupling does NOT lock. Everything above it asserts that things synchronise, and
every one of those assertions would also pass if `coherence()` simply returned 0.99 — so
without a case that legitimately fails, a green run here proves nothing at all.
"""
import math

import kuramoto as k

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def sample(g, n=64, cycles=1):
    """n samples of every joint angle across `cycles` gait cycles."""
    period = k.TAU / g.omega0
    out = {name: [] for name in k.JOINTS}
    for _ in range(n):
        a = g.angles()
        for name in k.JOINTS:
            out[name].append(a[name])
        g.settle(cycles * period / n)
    return out


def corr(xs, ys):
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    num = sum(a * b for a, b in zip(dx, dy))
    den = math.sqrt(sum(a * a for a in dx) * sum(b * b for b in dy))
    return num / den if den else 0.0


# ── it locks at all ─────────────────────────────────────────────────────────
g = k.Gait().settle(20.0)
show('the network phase-locks', g.locked(0.97), f'r = {g.coherence():.4f}')
show('every joint is within a quarter-turn of the collective phase',
     all(abs(e) < math.pi / 2 for e in g.phase_error().values()),
     f'worst {max(abs(e) for e in g.phase_error().values()):.3f} rad')

# ── the harmonic joint — fault 1 ────────────────────────────────────────────
show('the 2:1 neck locks like any other joint',
     abs(g.phase_error()['neck']) < 0.25,
     f"err {g.phase_error()['neck']:+.4f} rad at ω/ω0 = {g.omega['neck'] / g.omega0:.3f}")

# It must run at TWICE gait frequency — locked, but not locked to the WRONG ratio. A neck
# dragged down to 1ω would also report a small phase error and would be wrong.
t0, th0 = g.t, g.theta['neck']
ref0 = g.theta['knee_l']
g.settle(6.0)
neck_turns = (g.theta['neck'] - th0) / k.TAU
knee_turns = (g.theta['knee_l'] - ref0) / k.TAU
show('and it bobs exactly twice per stride',
     abs(neck_turns / knee_turns - 2.0) < 0.02,
     f'{neck_turns:.2f} neck turns per {knee_turns:.2f} knee turns')

# ── r is a stable measurement — fault 2 ─────────────────────────────────────
g2 = k.Gait().settle(15.0)
rs = []
for _ in range(40):
    g2.settle(0.137)          # not a multiple of the gait period, so a flicker cannot hide
    rs.append(g2.coherence())
show('r is steady, not flickering once per cycle',
     max(rs) - min(rs) < 1e-3,
     f'spread {max(rs) - min(rs):.6f} over 40 off-beat samples')

# ── the gait is the RIGHT gait ──────────────────────────────────────────────
# Contralateral swing is the defining feature of bipedal walking: right arm forward with
# left leg. Get this backwards and the robot fights its own yaw every step.
g3 = k.Gait().settle(20.0)
s = sample(g3, n=96)
show('right shoulder swings WITH the left knee',
     corr(s['shoulder_r'], s['knee_l']) > 0.8,
     f"corr {corr(s['shoulder_r'], s['knee_l']):+.3f}")
show('right shoulder swings AGAINST the right knee',
     corr(s['shoulder_r'], s['knee_r']) < -0.8,
     f"corr {corr(s['shoulder_r'], s['knee_r']):+.3f}")
show('the two knees are opposed',
     corr(s['knee_l'], s['knee_r']) < -0.8,
     f"corr {corr(s['knee_l'], s['knee_r']):+.3f}")
show('the two shoulders are opposed',
     corr(s['shoulder_l'], s['shoulder_r']) < -0.8,
     f"corr {corr(s['shoulder_l'], s['shoulder_r']):+.3f}")

# A distal joint must LAG its parent — that lag is what makes a limb behave like a whip
# rather than a stick. Peak of the elbow comes after peak of the shoulder.
def peak_at(series):
    return max(range(len(series)), key=lambda i: series[i])


lag = (peak_at(s['elbow_r']) - peak_at(s['shoulder_r'])) % 96
show('the elbow lags its shoulder', 0 < lag < 48, f'{lag / 96:.2f} of a cycle')
lag = (peak_at(s['ankle_l']) - peak_at(s['knee_l'])) % 96
show('the ankle lags its knee', 0 < lag < 48, f'{lag / 96:.2f} of a cycle')

# ── amplitudes stay where they were specified ───────────────────────────────
bad = [n for n in k.JOINTS
       if max(s[n]) - min(s[n]) > 2.05 * k.JOINTS[n][1] + 0.02]
show('no joint exceeds its commanded range', not bad, ', '.join(bad) or 'all within amplitude')

# ── the case it exists for: a limb slips, and comes back ────────────────────
g4 = k.Gait().settle(20.0)
before = g4.coherence()
g4.theta['knee_l'] += 2.4
hurt = g4.coherence()
show('knocking a knee out drops r', hurt < before - 0.1, f'{before:.3f} → {hurt:.3f}')
show('and phase_error names the joint that moved',
     max(g4.phase_error().items(), key=lambda kv: abs(kv[1]))[0] == 'knee_l',
     f"worst is {max(g4.phase_error().items(), key=lambda kv: abs(kv[1]))[0]}")
g4.settle(4.0)
show('it returns on its own, with nothing supervising it',
     g4.coherence() > before - 0.005,
     f'r back to {g4.coherence():.4f}')

# Recovery must be monotone-ish: a network that oscillated back would be a robot that
# wobbles for several strides after a stumble.
g5 = k.Gait().settle(20.0)
g5.theta['knee_l'] += 2.4
errs = []
for _ in range(12):
    g5.settle(0.25)
    errs.append(abs(g5.phase_error()['knee_l']))
show('and the return does not oscillate',
     all(b <= a + 0.02 for a, b in zip(errs, errs[1:])),
     f'{errs[0]:.3f} → {errs[-1]:.3f} rad, monotone')

# ── the test that can fail ──────────────────────────────────────────────────
# Kuramoto locks only above a critical coupling. Below it the network drifts apart, and
# that is what makes every assertion above meaningful — if this one also passed, the suite
# would be measuring nothing. Wide detuning, almost no coupling.
loose = k.Gait(K=0.05, detune=0.9, seed=3).settle(25.0)
show('a network below critical coupling does NOT lock',
     not loose.locked(0.97),
     f'r = {loose.coherence():.3f} with K=0.05 — the suite can fail')

# And the same body with coupling restored does lock, so the difference is K and not the seed.
tight = k.Gait(K=6.0, detune=0.9, seed=3).settle(25.0)
show('the same detuned body locks once K is restored',
     tight.coherence() > loose.coherence() + 0.2,
     f'r {loose.coherence():.3f} → {tight.coherence():.3f}')

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
