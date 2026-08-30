# laserbrain robotics — the adaptive placement robot

*Started 2026-07-23, kept open as the concept evolves (Diego is designing it live).
One robot, many jobs: it puts things where they should be, and keeps them there as
the world moves. This is laserbrain's displacement logic — ground state, scan,
displacement, reposition — built into hardware. "active, adaptive, dynamic."*

**Honest status: prototype and concept, not shipped hardware.** The interactive
prototype (phone mode) is real and demoable; the physical product is ahead. The
site keeps robotics as prototype/roadmap and does not claim shipped hardware.

## The one mechanism (why it's all one robot)

Every mode is the same loop — the drift-fixer, in the physical world:

- **0 · ground state** — the ideal spot for the job (facing you; best light + VPD).
- **1 · scan** — sense what matters: where you are, where the sun is, the humidity.
- **2 · displacement** — how far is the object from its ideal spot right now.
- **3 · reposition** — drive/tilt to close the gap; hold there as things move.

The object never has to be right where you left it — the robot returns it to its
ideal, continuously. Same proof idea: it measures against a fixed target (the ideal
spot), not against its own last position.

## How it attaches and moves

- **MagSafe magnet** — clips onto an iPhone (or any MagSafe target) with no cradle.
- **Suction** — mounts to smooth surfaces, including walls, to place itself where a
  wheeled base can't sit.
- **Motorized base** — drives across a surface to the target position.
- **Tilt** — aims: angles the screen to your eyeline, or a plant's leaves to the sun.

## Sensing

- **You** — position/where you are, so the screen stays on you.
- **Sun** — sun angle relative to your space, to find a plant's best light.
- **Humidity / VPD** — vapor-pressure-deficit, the real horticulture metric for plant
  health; the robot places a plant where light *and* VPD are best, not just bright.

## Modes (use cases)

- **Phone mode.** MagSafe-clips your iPhone and keeps the screen facing you at a
  comfortable distance, hands-free, as you move. *(Prototype: live.)*
- **Camera mode.** A MagSafe stand that *silently* turns, tilts and rotates the
  phone to frame a shot — by soft fluidic (VPD/pressure) actuation, not motors, so
  there is no whine or shake on the footage. The "silent" differentiator ties the
  actuation to the fascial-driven soft-robot direction. *(Prototype.)*
- **Plant mode.** Given your space and the sun, finds and holds the best spot for a
  plant — optimal light and VPD — and re-finds it as the sun moves through the day.
- **General.** Place anything in its optimal spot and keep it there: a light, a
  camera, a speaker aimed at the room.

## What the motor does — and the "only laserbrain" line

**The one differentiator: it holds an *ideal*, it doesn't *track* a target.** Every
motorized mount on the market points (face-trackers) or rotates (plant turntables).
None *relocate* an object to its optimal spot and hold it, moving only when
displacement is real. That's the drift-fixer in hardware: measure against a fixed
reference (the ideal spot), act on displacement, return to ground, then stop. So it
is **calm by proof** — decisive when the world moves, still otherwise, where
trackers jitter.

Capabilities (design goals for the prototype line, not shipped claims):

- **Move** — drive to any point (2-D placement, not pan/tilt in place); tilt + pan
  to aim; climb off the floor by suction to walls/smooth surfaces.
- **Attach** — MagSafe magnet (iPhone, no cradle); suction (plant pot, light, camera).
- **Sense** — you (keep the screen on you); sun angle + light through the day;
  humidity/VPD (real plant-health metric); obstacles and edges.
- **Decide (the laserbrain part)** — compute the *ideal* spot for the job (ergonomic
  viewing; light-AND-VPD optimum), not "point at the target"; reposition only when
  displacement crosses a threshold, then hold; re-optimize as conditions change;
  return to a dock to charge when idle.

Why it isn't trivially copyable: placement not pointing; an ideal not a target;
VPD-aware plant placement + relocation (nothing consumer does this); and calm-by-
construction — the same fixed-reference logic that stops a spiraling agent stops a
twitchy motor, which we've already proved ([[PROOF]]).

## Where it sits in the brand

phronesis (studio + thinktank, "AI, tailored") → **laserbrain** (subbrand, "active,
adaptive, dynamic") → robotics → the adaptive placement robot. Alongside the
software line (the drift-fixer, the redtooth agent coupler). See [[IDEAS]] for the
full roadmap, [[REVENUE]] for how the software monetizes, [[PROOF]] for the
displacement logic this hardware embodies.

## Research direction: fascial-driven robots

The deeper vision the line is built toward (Diego, 2026-07-23) — **fascial-driven
robots**: soft robots that move the way a body does, driven by fascia-like tissue
that stores and releases force, rather than rigid motors and gears. Grown, not
milled. Same control idea — hold an ideal, return to it — but in a body that bends
instead of a base that drives. Grows out of laserbrain's tissue-displacement work.
**Honest status: a research direction, not shipped hardware.** On the site it is
stated as exactly that (`/laserbrain/robotics`, "Where it's heading"); do not let it
drift into a product claim. A **tensegrity / wire-driven concept demo is built** — a
soft tentacle of rigid ribs held in tension wires that curls when a wire contracts
(Verlet + position-based dynamics, symmetric solve verified). It makes "moves by
tension, not gears" tangible without claiming a shipped robot.

**Architecture note — robots that plug into the phone (Diego, 2026-07-23):** the
phone is the brain. The robot plugs into the iPhone and borrows its camera, sensors
and compute, so the robot itself is just muscle — cheap, and it inherits the phone's
capability. On the site as a "why only laserbrain" point.

## Open (Diego's calls)

- Which mode leads the marketing — phone (mass-market, MagSafe) or plant (novel,
  VPD, a clearer "only laserbrain does this")?
- Build the **plant-mode demo** next (sun sweep + VPD map → best spot), or bank the
  phone-mode prototype and spec for now?

## The limbed direction — Kuramoto coupling (2026-07-25)

*Diego: "use kuramoto coupling for the shoulders, knees, ankles, neck, elbows, and
wrists of laserbot." Built and tested in `kuramoto.py` / `test_kuramoto.py`.
**No hardware. laserbot has no limbs — this is the controller, ahead of the body.***

Eleven joints — neck, both shoulders, elbows, wrists, knees and ankles — each a phase
oscillator running at its own natural frequency and pulled toward its neighbours:

    dθᵢ/dt = ωᵢ + (K/|Nᵢ|) · Σ sin(ϑⱼ - ϑᵢ)

The gait is not a keyframe table played back. It is an agreement the joints reach, and
that difference is the whole reason to use it here.

**Why it belongs to laserbrain, and not merely near it.** A coupled network carries its
own fixed reference — the order parameter

    r · e^(iφ) = (1/N) · Σ e^(iϑⱼ)

r = 1 is every joint exactly where the gait says it should be relative to every other.
So **1 − r is displacement**, in the harness's own sense of the word, and here it is
*measured* rather than inferred. That is the case [[PROOF]] and this file both mean by
"the instrument runs COMPLETE in hardware": on the software side Φ has no honest signal
for distance-to-goal and settles for a lower bound; a body computes it exactly.

A limb that jams, slips or loses pressure falls out of lock. r drops before the pose is
visibly wrong, and `phase_error()` names *which* joint moved — an alarm and a diagnosis,
not just an alarm. Recovery needs no supervisor: knock a knee 2.4 rad out of phase and it
returns monotonically to r = 0.990 because the coupling *is* the correction. Nothing
observes the fault and commands a fix.

Coupling is anatomical, not all-to-all: chains along shoulder→elbow→wrist and knee→ankle,
contralateral shoulder↔knee (right arm with left leg — the thing that cancels the yaw the
legs induce), girdle links, and the neck coupled weakly to both shoulders so the head
follows the body and never steers it. All-to-all would lock harder and let a jammed wrist
pull on the opposite ankle, turning one stuck joint into a whole-body stumble.

**Three faults found by running it, all mine, all now pinned by tests:**

- The neck bobs twice per stride, and a plain `sin(θⱼ − θᵢ)` cannot lock a 2:1 oscillator
  to a 1:1 one. It drifted forever and dragged r to 0.68 while every other joint was fine
  — the measurement reported an incoherent *body* when what was broken was the *model*.
  Fixed by coupling in reduced phase, ϑ = (θ − ψ)/h, which puts every joint on one gait
  clock and handles any ratio without a special case.
- Wrapping θ into [0, 2π) made the neck's reduced phase jump by π once per cycle, so r
  flickered between 0.99 and 0.82 forever. 0.818 is exactly 10/11 — ten joints agreeing
  and one pointing backwards — which is what gave it away. θ is now never wrapped.
- ψ was inverted: a larger ψ made a joint peak *earlier*, so every "distal lags proximal"
  comment in the table described the reverse of what ran. The contralateral pairs are half
  a cycle apart and so looked right either way, which is exactly why it survived reading
  and needed a test.

The suite's most important case is that a network below critical coupling does **not**
lock (r = 0.135 at K = 0.05). Every other assertion says things synchronise, and all of
them would pass just as well if `coherence()` returned 0.99 unconditionally.
