#!/usr/bin/env python3
"""kuramoto.py — laserbot's limbs, coupled as phase oscillators.

Diego, 2026-07-25: "use kuramoto coupling for the shoulders, knees, ankles, neck, elbows,
and wrists of laserbot."

WHAT THIS IS. Eleven joints, each an oscillator carrying a phase. They are not driven by a
common clock and they are not scripted from a keyframe table. Each runs at its own natural
frequency and is pulled toward its neighbours, so the gait is an EMERGENT agreement rather
than a playback. That is the Kuramoto model:

    dθᵢ/dt = ωᵢ + (K/|Nᵢ|) · Σ sin(θⱼ - θᵢ + ψᵢ - ψⱼ)
                              j ∈ Nᵢ

ψᵢ is the phase the joint is SUPPOSED to hold in the gait, so the coupling term drives the
measured offset (θᵢ - θⱼ) toward the intended offset (ψᵢ - ψⱼ) and holds it there. Set every
ψ to zero and this is the textbook model; the biases are what turn synchrony into a walk.

WHY IT BELONGS TO LASERBRAIN, and this is the whole reason it is worth building here rather
than lifting a gait table. laserbrain measures displacement from a reference that does not
move. A coupled oscillator network has exactly such a reference built into it — the order
parameter

    r · e^(iφ) = (1/N) · Σ e^(i(θⱼ - ψⱼ))

r = 1 means every joint sits precisely where the gait says it should relative to every
other; r = 0 means the body has no collective rhythm at all. So **1 - r is displacement**,
in the same sense the harness uses the word, and it is measured rather than inferred. On the
software side Φ has to estimate distance-to-goal and settles for a lower bound. Here the
body computes it exactly, which is the case ROBOTICS.md means when it says the instrument
runs COMPLETE in hardware.

A limb that jams, slips, or loses pressure falls out of lock, r drops, and the drop is
visible before the pose is visibly wrong. That is the same early-warning the harness gives
an agent, on a leg.

WHAT THIS IS NOT. No hardware is driven from here. laserbot has no limbs yet — ROBOTICS.md
describes a suction-mount placement robot, and this is the limbed direction it points at
under "soft fluidic actuation". This module is the controller and its test, honest about
being ahead of the body, per CLAIM.md's rule: say only what is true.

    python3 kuramoto.py            one gait cycle, printed
    python3 kuramoto.py --perturb  knock a knee out of phase and watch it return
"""
import math, cmath, sys

TAU = 2 * math.pi

# ── the body ────────────────────────────────────────────────────────────────────────
# ψ is the joint's phase within one gait cycle, in turns (0..1), converted to radians below.
#
# The offsets are human walking, not decoration. The defining feature of bipedal gait is
# CONTRALATERAL swing: the right arm goes forward with the LEFT leg. It cancels the yaw the
# legs induce, and a robot without it wastes energy fighting its own rotation. So the right
# shoulder shares a phase with the left knee, and vice versa.
#
# Distal joints lag their proximal parent — an elbow follows its shoulder, an ankle follows
# its knee — because that lag is what makes a limb behave like a whip instead of a stick.
#
# amp is the half-range in radians; center is the neutral angle the oscillation rides on.
JOINTS = {
    #  name            ψ (turns)  amp     center   parent
    'neck':           (0.00,      0.05,   0.00,    None),
    'shoulder_l':     (0.50,      0.35,   0.00,    None),
    'shoulder_r':     (0.00,      0.35,   0.00,    None),
    'elbow_l':        (0.60,      0.25,   0.35,    'shoulder_l'),
    'elbow_r':        (0.10,      0.25,   0.35,    'shoulder_r'),
    'wrist_l':        (0.68,      0.12,   0.00,    'elbow_l'),
    'wrist_r':        (0.18,      0.12,   0.00,    'elbow_r'),
    'knee_l':         (0.00,      0.45,   0.30,    None),
    'knee_r':         (0.50,      0.45,   0.30,    None),
    'ankle_l':        (0.25,      0.20,   0.00,    'knee_l'),
    'ankle_r':        (0.75,      0.20,   0.00,    'knee_r'),
}

# The neck is the one joint that does not run at gait frequency. A head bobs TWICE per
# stride — once per footfall — so it takes 2ω.
#
# This cannot be expressed with a plain sin(θⱼ - θᵢ) coupling, and the first version of this
# file got it wrong: a 2:1 oscillator has no fixed phase relation to a 1:1 one under that
# term, so the neck drifted forever and dragged the order parameter down to 0.68 while every
# other joint was locked. The measurement said "the body is incoherent" when the body was
# fine and the model was broken.
#
# The fix is to couple in REDUCED phase (see Gait._reduced): each joint's phase is divided
# by its own harmonic, which puts every oscillator on one common gait-cycle clock. Then a
# single sin(ϑⱼ - ϑᵢ) handles any n:m ratio and the neck locks like anything else.
HARMONIC = {'neck': 2.0}

# The head follows the body and must never steer it. Degree alone does not guarantee that —
# a neck with two neighbours pulls on both shoulders as hard as they pull on it — so its
# edges carry a fraction of the coupling.
EDGE_WEIGHT = {'neck': 0.35}

# ── who talks to whom ───────────────────────────────────────────────────────────────
# Anatomical, not all-to-all. All-to-all locks fast and rigidly, and it also lets a jammed
# wrist pull on the opposite ankle, which is both physically meaningless and a good way to
# turn one stuck joint into a whole-body stumble. Coupling along the kinematic chains keeps
# a fault local, which is the property you want when a limb fails.
def _edges():
    e = set()
    def link(a, b):
        e.add(tuple(sorted((a, b))))
    for name, (_, _, _, parent) in JOINTS.items():   # chains: shoulder→elbow→wrist, knee→ankle
        if parent:
            link(name, parent)
    link('shoulder_l', 'knee_r')                     # the contralateral pairs — the gait itself
    link('shoulder_r', 'knee_l')
    link('shoulder_l', 'shoulder_r')                 # girdles: keep left and right opposed
    link('knee_l', 'knee_r')
    link('neck', 'shoulder_l')
    link('neck', 'shoulder_r')
    return sorted(e)

EDGES = _edges()

NEIGHBOURS = {name: [] for name in JOINTS}
for _a, _b in EDGES:
    NEIGHBOURS[_a].append(_b)
    NEIGHBOURS[_b].append(_a)


class Gait:
    """The coupled network. step() integrates; angles() gives joint commands.

    K is the coupling strength in rad/s. It has to beat the spread in natural frequencies or
    the network never locks — that is the Kuramoto critical coupling, and detune=0.35 with
    K=6.0 is comfortably above it. Raising K further locks harder and makes the body stiffer
    against a real obstacle, which is not obviously what you want in a soft-actuated robot.
    """

    def __init__(self, freq_hz=0.9, K=6.0, detune=0.08, seed=7):
        self.K = K
        self.omega0 = TAU * freq_hz
        self.t = 0.0
        # Deterministic spread of natural frequencies. Without it every oscillator is
        # identical, any phase pattern is trivially a fixed point, and a test that shows
        # "it stays locked" proves nothing — there was nothing to correct.
        rnd = _lcg(seed)
        self.omega, self.theta = {}, {}
        for name in JOINTS:
            h = HARMONIC.get(name, 1.0)
            self.omega[name] = self.omega0 * h * (1.0 + detune * (rnd() * 2 - 1))
            self.theta[name] = self._psi(name)   # start each joint exactly on its mark

    # ── the reference each joint is held against ────────────────────────────────────
    def _psi(self, name):
        """ψ as a LAG: a joint with a larger ψ peaks LATER in the cycle.

        The sign matters and I had it inverted. Angle is center + amp·sin(θ), so the peak
        falls where θ = π/2; initialising θ to +2πψ means a bigger ψ starts the joint
        FURTHER along and it peaks SOONER. Every comment in the table says the opposite —
        elbow lags shoulder, ankle lags knee — and the test caught the contradiction: the
        elbow led its shoulder by 0.16 of a cycle instead of trailing it by 0.10.

        Negating it makes the table mean what it reads as. The contralateral pairs are
        unaffected either way, being half a cycle apart, which is why the gait still looked
        broadly right while the limb chains ran backwards.
        """
        return -TAU * JOINTS[name][0] * HARMONIC.get(name, 1.0)

    def _reduced(self, name):
        """The joint's position in the GAIT cycle, with its bias and harmonic divided out.

        ϑ = (θ - ψ) / h. This is the one idea that makes the network uniform: every joint,
        whatever frequency it actually runs at, is expressed on the same 0..2π gait clock.
        A joint walking correctly sits at ϑ = 0 regardless of harmonic, so one sin(ϑⱼ - ϑᵢ)
        couples the 2ω neck to the 1ω shoulders with no special case anywhere.

        Dividing by h leaves a 2π/h ambiguity — for the neck, WHICH of its two identical
        bobs per stride this is. I first wrote that off as physically meaningless, since the
        two bobs are the same event, and it is not: wrapping θ into [0,2π) made the neck's
        reduced phase jump by π once per gait cycle, so r flickered between 0.99 and 0.82
        forever. 0.818 is exactly 10/11 — ten joints agreeing and one pointing backwards —
        which is what gave it away.

        So θ is never wrapped (see step). Held unwrapped, (θ - ψ)/h advances continuously at
        the gait rate whatever h is, the branch never flips, and r is steady. Everything
        downstream is a sine or a complex exponential, both of which are indifferent to how
        many turns have accumulated.
        """
        return (self.theta[name] - self._psi(name)) / HARMONIC.get(name, 1.0)

    def step(self, dt=0.005):
        """One integration step. Explicit Euler is enough: dt·K = 0.03 << 1."""
        red = {i: self._reduced(i) for i in JOINTS}
        dtheta = {}
        for i in JOINTS:
            nb = NEIGHBOURS[i]
            h = HARMONIC.get(i, 1.0)
            acc = w = 0.0
            for j in nb:
                # Drives both joints to the same point of the gait cycle. At the intended
                # offset the sine is zero, so a correctly-walking body feels no coupling
                # force at all — the network is doing nothing until something is wrong.
                gain = EDGE_WEIGHT.get(i, 1.0) * EDGE_WEIGHT.get(j, 1.0)
                acc += gain * math.sin(red[j] - red[i])
                w += gain
            # Scaled by h so the correction is applied in the joint's OWN phase units: the
            # neck must turn twice as fast to cover the same fraction of a gait cycle.
            dtheta[i] = self.omega[i] + h * (self.K / max(w, 1e-9)) * acc
        for i in JOINTS:
            # Deliberately NOT wrapped — see _reduced. Wrapping breaks the harmonic joint.
            self.theta[i] += dtheta[i] * dt
        self.t += dt
        return self

    # ── outputs ─────────────────────────────────────────────────────────────────────
    def angles(self):
        """Joint commands in radians — what a servo or a pressure valve is given."""
        return {n: c + a * math.sin(self.theta[n]) for n, (_, a, c, _) in JOINTS.items()}

    def coherence(self):
        """The order parameter r ∈ [0,1], with each joint's intended bias removed.

        This is the ground-state signal. r = 1 is the body exactly in its gait; 1 - r is
        displacement from it. Nothing here is inferred — unlike the software side, where
        distance-to-goal has no honest measurement and Φ settles for a lower bound.
        """
        z = sum(cmath.exp(1j * self._reduced(n)) for n in JOINTS) / len(JOINTS)
        return abs(z)

    def phase_error(self):
        """Per-joint deviation from the collective phase, in radians (signed, -π..π).

        Names WHICH joint is drifting. r says the body is wrong; this says it is the left
        ankle, which is the difference between an alarm and a diagnosis.
        """
        z = sum(cmath.exp(1j * self._reduced(n)) for n in JOINTS) / len(JOINTS)
        mean = cmath.phase(z)
        return {n: _wrap(self._reduced(n) - mean) for n in JOINTS}

    def locked(self, tol=0.97):
        return self.coherence() >= tol

    def settle(self, seconds=12.0, dt=0.005):
        for _ in range(int(seconds / dt)):
            self.step(dt)
        return self


def _wrap(a):
    return (a + math.pi) % TAU - math.pi


def _lcg(seed):
    """Numpy is not a dependency of this repo and this needs eleven numbers."""
    state = [seed]
    def rnd():
        state[0] = (1103515245 * state[0] + 12345) % (1 << 31)
        return state[0] / (1 << 31)
    return rnd


def main(argv):
    g = Gait()
    print(f'  {len(JOINTS)} joints, {len(EDGES)} couplings, K={g.K}')
    print(f'  r at rest (phases set, not yet settled): {g.coherence():.3f}')
    g.settle(12.0)
    print(f'  r after settling:                        {g.coherence():.3f}')

    if '--perturb' in argv:
        # The case the whole thing is for: one joint knocked out of the gait.
        print('\n  knocking knee_l out by 2.4 rad — a limb that slipped\n')
        g.theta['knee_l'] = (g.theta['knee_l'] + 2.4) % TAU
        print(f'    {"t (s)":>7}  {"r":>6}  {"knee_l err":>11}')
        for k in range(9):
            print(f'    {g.t:>7.2f}  {g.coherence():>6.3f}  {g.phase_error()["knee_l"]:>+11.3f}')
            g.settle(0.35)
        print(f'\n  returned to r={g.coherence():.3f} without anything commanding it to.')
        print('  No supervisor noticed and corrected the knee — the coupling IS the return.')
        return 0

    print('\n  one cycle of joint angles (rad):\n')
    names = ['neck', 'shoulder_l', 'shoulder_r', 'elbow_l', 'knee_l', 'knee_r', 'ankle_l']
    print('    ' + f'{"phase":>6}' + ''.join(f'{n[:9]:>11}' for n in names))
    period = TAU / g.omega0
    for k in range(9):
        a = g.angles()
        print('    ' + f'{k / 8:>6.2f}' + ''.join(f'{a[n]:>+11.3f}' for n in names))
        g.settle(period / 8)
    print(f'\n  contralateral check — shoulder_r and knee_l should move together,')
    print(f'  shoulder_r and knee_r opposed. See test_kuramoto.py.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
