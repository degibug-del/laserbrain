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
