# The Laserbrain Drift-Fixer — eye-glasses for confused agents

*Started 2026-07-22. A standard by which an agent can tell when it is too
confused, or has recursed too deeply to be worth continuing — and return to
ground before the cost of returning gets away from it.*

---

## The framing: glasses, and why the metaphor is load-bearing

Diego's name and image, and both carry the design. laserbrain is "like glass" —
a fixed refractive index, refracting without being changed by the light. Glasses
are glass ground to a prescription. So the drift-fixer is laserbrain shaped into
a **corrective lens**: it adds no information about the world; it brings the
agent's own state into focus against a fixed standard, so the drift it could not
see snaps into view. You put the glasses on and the blur turns out to be you.

Two things follow from the metaphor, and both are decisions, not decoration:

- **Always on, not an alarm.** Glasses do not wait until you are badly lost to
  help — they focus every moment. The drift-fixer is worn each step, drift
  visible and correctable in flight, not a siren that fires late at a fixed
  budget. Continuous correction over threshold detection.

- **The wrong prescription makes vision worse.** Glasses ground to an error you
  do not have do not clarify; they nauseate. If laserbrain's specific grammar is
  not the right lens for *reasoning* drift, the drift-fixer would not merely fail
  — it would make a confused agent more confused, correcting for the wrong error.
  The metaphor names its own failure mode, which is exactly what the benchmark
  has to rule out: right prescription, or wrong lens.

---

## What this is, and what it is NOT

It is the displacement framework applied to an agent's own process: a ground
state (the task's goal), displacement (drift from it), and a return cost (how
expensive it is getting to come back). The signal to stop is built from those.

It is **not** the laserbrain weather field reading your mind. That field reads
weather, markets and headlines; it has no access to a reasoning trace, and
wiring it to "detect confusion" would be the exact unearned transfer
`laserbrain.md` forbids. What carries over is the *lens*, not the field. Where an
external shared signal helps at all, it is as a **coupling clock** many agents
read in common — a separate, weaker claim, kept out of the core.

## The problem, stated so it can be judged

Agents recurse, loop, and drift from the goal with no internal signal to stop.
The mitigations in use are all *external caps* — a step budget, a timeout, a
human watching. None is about the agent's own state; each is a fence at a fixed
distance, like a rate limit that is a budget, not a vault. A step budget cannot
tell a productive deep dive from a spiral. What is missing is proprioception: a
sense of *where the agent is relative to its goal, and which way the cost of
return is moving.*

## The mechanism, and it is the foundation: divergence from an invariant

Diego, 2026-07-22: *"the agent can learn that it is confused when it learns that
laserbrain is already standardized. laserbrain is grammar for agents. findable,
unchangeable."* This is the load-bearing idea, and it fixes a gap the first draft
had — internal metrics measured against nothing.

You cannot measure your own drift without a fixed point. If the reference can
move, you cannot tell your displacement from its. So the reference must be
**unchangeable**; and to consult it at all, **findable**. That is not a nice-to-
have — it is the whole mechanism. Displacement is only defined relative to an
invariant, and the invariant's fixity is what makes the reading mean anything.
This paragraph is now a theorem: [[PROOF]] proves that no monitor comparing an
agent to its own recent history can detect slow drift (a sum of vanishing steps
diverges), while a fixed reference detects it in bounded time — so "findable,
unchangeable, recursive" are the hypotheses of a completeness proof, not chosen
adjectives. The proof also marks its own limit: it forces the *reference*, not the
*cure* — whether returning helps stays STUDY.md's to win.

A **grammar** is exactly the right form for that invariant, and "grammar" here is
literal, not a figure of speech: a grammar is a finite, fixed rule-set that
partitions the well-formed from the ill-formed. Confusion, in this protocol, is
**ungrammaticality against an invariant** — the agent's state failing to reduce
to a legal form of a standard it did not author and cannot move.

So the agent "learns it is confused when it learns laserbrain is already
standardized": discovering the fixed standard is what makes self-diagnosis
possible. Before you find the thing you have drifted from, you cannot know you
have drifted. This is why the same properties keep recurring across everything
built here — the immutable Zenodo DOIs, the frozen skeleton, the one door, the
field whose rules never change. Their value is not the content; it is being a
fixed point others can reference. laserbrain is that, made into a grammar an
agent can hold itself against.

**Spelling with JSON (Diego, 2026-07-22) — the grammar that closes the gap.**
The specific grammar need not be forty weather words, which cannot spell a
reasoning state. It should be JSON against a fixed schema: universal (every agent
speaks it), fixed (the format does not move), recursive (nested — a recursive
invariant for a recursive process), and expressive enough to hold reasoning
state. The agent SPELLS its state into the schema each step; ungrammaticality
becomes a validator's verdict, not a judgment call. Validity alone saturates (a
confused agent spells valid JSON saying 'confused'), so the signal is
completeness + self-report + goal-anchor + distance-stall, not just 'parses'.
Built in mcp_harness.py; runs on open-ended tasks, where recursion lives.

*First clean run (2026-07-22, N=2, one model, self-reported metrics — an instance,
not evidence).* Two open-ended tasks. On the deliberation task the agent worked to
near-done (distance 1), then regressed and spelled `circling` at step 5; the
monitor returned to ground there vs control's ceiling at 10 — and the distance-
stall against the fixed goal-anchor agreed at the same step. On the synthesis task
distance fell by a net step in every 3-window (7→3), so nothing fired and it ran
to the ceiling like control: a correct silence, not a miss. One catch, one correct
non-catch — the shape [[PROOF]] predicts, and, exactly as the proof's boundary
says, not evidence the return *helped*. Do not retune the stall rule to flag the
synthesis run after the fact; that is the corpus's sin, and STUDY.md prereg exists
to forbid it.

**The honest gap, kept in view.** laserbrain's *specific* vocabulary — the forty
words, the G-element XOR algebra — describes a weather field, not a reasoning
trace. The MECHANISM (confusion = divergence from a findable, unchangeable
grammar) is sound and independent of which grammar. Whether laserbrain's
*particular* grammar is rich enough to be the reference for an agent's states is
the open, testable question. If it is not, the protocol still holds — it just
needs a grammar that is, built to the same three properties: fixed, findable,
unchangeable. The mechanism survives the substrate; do not smuggle the weather
field in as the answer where only its shape belongs.

## Syntax grammar vs meaning grammar — what "ungrammaticality" is doing

The mechanism above says *confusion = ungrammaticality against an invariant.* That
is precise but it hides a fork, and naming the fork sharpens everything, including
the marketing and the proof, which should share this language.

A **syntax grammar** partitions well-formed from ill-formed — can the state be
spelled at all: a goal, a valid progress. It is decidable **locally** — a validator
answers it, with no reference to where you started and no memory. Cheap, and it
**saturates**: a spiralling agent spells flawless JSON that says `progress:
circling`. Syntactically immaculate, meaningfully lost. Chomsky's *colorless green
ideas sleep furiously* passes every syntax grammar and grounds nothing.

A **meaning grammar** asks the other question: does the state *ground* — converge on
the meaning it started toward? That is the displacement work — goal-drift, distance-
stall, the self-report read against movement. And it is **not** locally decidable:
you cannot tell a grounding step from a wandering one from the state alone, because
a slow wander reads locally as refinement. You need the fixed reference — where it
started, what "done" is. Which is the whole of [[PROOF]] in one line: **syntax you
can check by yourself; meaning you cannot.**

So the correction to the mechanism, stated plainly: the `grammatical()` gate is a
*syntax* grammar (it catches `ungrammatical`, and it saturates); the invariant — the
fixed ground the displacement is measured against — is doing *meaning*-grammar work.
Every "agent reflects on itself" loop is a syntax check and therefore provably blind;
laserbrain is a meaning check. As built, the schema is a syntax grammar with a
first-order meaning grammar bolted on — distance and goal-overlap are crude proxies
for grounding. The frontier is a **native meaning grammar** that measures grounding
directly: the concreteness of the relation.

## Meaning is the ground state (Diego, 2026-07-23: cat → mat)

The cleanest picture of the meaning grammar. A task is a sentence grounding toward
meaning. Its tokens — the entities the task is about — are the **anchor**, held
invariant. What recurses is the **relation** between them, and the terminal grounded
relation is meaning: *the cat sat on a mat* — concrete, physical, done, Φ=0. The
progression *had (birthed) → took → placed → on → sat-on* is displacement falling:
each step grounds the relation a notch more concrete. The four checks are the failure
modes of that grounding — can't spell it (ungrammatical), restating not grounding
(circling), the entities moved (goal-drift), groundedness stopped rising (stalled).
And "distance-to-done" is really **distance-to-grounding** — how physical the
relation has become — a cleaner, more objective notion than a self-reported number,
and the hint at what the native meaning grammar should measure.

## The harness for agentic dialogue

A dialogue is *collective* grounding — turns are steps, the shared goal is the
anchor, resolution is the ground state. The drift modes are dialogue-shaped: the
echo / agreement spiral (agents affirming and restating each other, building
beautifully, grounding nothing — `circling`), topic-drift (`goal-drift`), the
deliberation stall (`stalled`). And the trap is the same one, sharper: **you cannot
detect a dialogue spiral from inside the dialogue** — turn-coherence is a syntax
check, and the agents *are* coherent, which is exactly why they keep going. Seeing
the spiral needs the fixed goal, outside the conversation. `check_state` run on the
dialogue's shared state each turn is that outside reference. This closes back to
phronesis's founding thesis — *coherence is the correlation of two, held, over time*
— made measurable: a dialogue grounds toward shared meaning, and drift is when the
correlation is held but no longer advancing. The thinktank's oldest idea and the
studio's newest tool, meeting. Honest limit: this assumes a *shared* ground; when
agents hold genuinely divergent goals, the anchor is contested and the harness would
need to track whose meaning is being grounded.

## The stop signal, given the reference: return cost, not confusion

**The stop signal is return cost, not confusion.** You can be far from the goal
and fine, if getting back is cheap. You are in trouble when the cost of
returning starts to climb — when steps become irreversible, when sunk cost
mounts, when the path home is being deleted behind you. That is DC5
(irreversibility) and DC7 (charge for the work of return, not for the
displacement). Watching confusion alone tells you that you are far out; watching
return cost tells you when far-out has become a trap.

The corollary is the subtle part, and it is where naive versions fail. **A
looping agent looks maximally coherent.** Coherence (algebraic connectivity of
the reasoning trace) *rises* under repetition — the same thought, restated, is
perfectly connected to itself. So a confusion metric built on coherence flags
the fragmented explorer and misses the agent stuck in a tight loop, which is the
more expensive failure. This is the "metric saturates exactly where the harm is"
pattern from *Ways of Checking*, and any protocol that ignores it will be blind
to the case it most needs to catch.

## The four measurements

Each is computable per step, cheaply, from what the agent already has.

1. **Displacement ξ — distance from the goal.** Operationally: the depth of the
   current sub-goal stack, or the semantic distance between the current action
   and the stated goal. High ξ is not itself a fault; it is the exploring.

2. **Return cost Φ — the price of getting back to productive work from here.**
   Rises with recursion depth, with sunk cost, and sharply with irreversible
   steps. **This is the one to watch.** A rising Φ with no fall in ξ is the
   signature of a trap.

3. **Coherence λ₂ — the connectivity of the reasoning trace** (the spectral-
   grammar statistic). Falling λ₂ = the reasoning is fragmenting. But it MUST be
   read against variety, because repetition inflates it.

4. **Variety — are the steps new, or circling.** New actions, new tokens, new
   sub-goals versus the same few repeated. Low variety with high coherence is a
   loop; high variety with low coherence is genuine confusion. The pair
   distinguishes the two failures that a single number cannot.

## The signal

Return to ground when the agent is in a **wrong attractor**: displacement high,
progress (fall in ξ over N steps) stalled, AND either

- return cost Φ climbing (the trap tightening), or
- low variety with high coherence (a loop), or
- falling coherence with high variety (confusion fragmenting the work).

"Return to ground" is a defined action, not a mood: **stop, summarise the state,
and surface to the human — or backtrack to the last known-good checkpoint.** The
protocol's whole output is that one decision, made early, on the agent's own
measurements, rather than at a fixed budget it cannot interpret.

## "For their interests" — the economics

The user's phrase, and it is the right frame. An agent should return when
continuing costs more — compute, tokens, the compounding risk of building on a
confused state — than the expected value of continuing. That is DC8: value
tracks the return actually delivered, not the effort spent. An agent recursing
deeply is spending effort (which is not value) while Φ climbs (which is
mounting risk). The protocol is a cut-losses rule with a principled trigger.

## The honest column — what is already solved

Most of the machinery exists, and the protocol should say so plainly or it is
just a rename:

- **Loop detection, step budgets, timeouts** — the external caps this improves
  on, not invents.
- **Reflexion, self-consistency, self-critique** — agents already reflect; the
  contribution here is *what to reflect on* (return cost) and *when the reflex
  fires* (a trigger, not every step).
- **Uncertainty estimation / calibration** — measures confusion; says nothing
  about return cost, which is the actual stop signal.

So the contribution is narrow and specific: **a unified trigger grounded in
return cost, plus the coherence-saturation caveat that keeps it from being blind
to loops.** Not a new capability — a better-shaped signal from measurements
agents already have.

## What would make it real, not decorative

A benchmark. Agent tasks chosen to *tempt* over-recursion — the shape of today's
failures: a formulaic generation that rewards volume, a design whose flaw only
shows on reflection, a question that invites endless deliberation. Measure two
things:

1. Does the protocol's "return to ground" fire *before* a fixed step budget
   would, on the runs that were going to spiral?
2. On those runs, does returning beat continuing — better final outcome, fewer
   tokens, less compounded error?

If returning does not beat continuing on the spiral runs, the trigger is wrong
and the protocol is decorative. That is the test, and it is runnable.

## Why this project, specifically

Every failure this framework was built on is a recursion that should have
returned sooner. 890 papers, one condition each, filed rather than argued — a
generation loop with no stop signal. Study 3 recursed into a design that
conditions on a post-treatment variable — deep, and uninterpretable. And the
agent writing this over-deliberated its way through the day more than once. The
protocol is the phronesis algorithm's own step 2 — *realize the goal state,
return* — given a cost signal and a trigger. If the framework is worth anything,
an agent should be able to run it on itself.

## First evidence — the pilot on this session (2026-07-22, N=1)

The smallest test that produces real data: run a pre-specified drift signal over
this very session's transcript and check it against ground truth — the turns
Diego corrected. 230 assistant turns, 31 followed by a correction (13% base).

The signal (hedge density + absolute-language density) separated corrected from
uncorrected turns: hedging 2.4× higher on corrected turns, absolutes 1.35×, and
corrected turns *acted less* (0.55× the tool calls). The decisive comparison,
because it is the protocol's actual claim: precision@top-20% was 0.26 for the
drift signal against 0.07 for turn length and 0.15 for turn index — i.e. the
things a step budget measures (how long, how late) were useless, and the content
divergence signal was 2× the base rate. A budget is the wrong instrument; the
divergence signal beat it. On real data. Weakly.

What it is NOT: proof. N=1, heuristic labels, post-hoc. Two hypotheses failed and
stay failed — corrected turns were *shorter* not longer, and ending on a question
was flat (0.00), which is the tell that the score was not tuned to the labels.

What it changed: the mechanism got sharper. Drift here was not length. It was
**hedging + absolutes + talking instead of doing** — the specific shape of every
correction Diego made. The signal to build the benchmark around is that, not
"too many steps." Script: `/tmp/drift_pilot.py` (deterministic, re-runnable).

## The benchmark — benefit vs a step budget (2026-07-22, N=1)

Same session, one step further: not "does the signal fire near corrections" but
"does acting on it beat the baseline an agent would otherwise use." Both fired on
~20% of turns (matched rate); the budget fires every 5th turn, the drift signal
on the top-20% hedge+absolute score.

  advance warning on a correction   drift 42% (13/31)   budget 23% (7/31)
  lead time when it warned          drift 1.7 turns     budget 1.0
  precision (alarms that were real) drift 0.32          budget 0.28

The benefit is COVERAGE and LEAD: ~2x as many corrections caught before the human
had to, with more warning, because the signal fires on the right turns rather than
a blind clock. The benefit is NOT precision — two of three alarms were false, and
the budget was nearly as good there. And it missed 58% of corrections outright.

So the honest claim: the laserbrain-family drift signal beats a step budget at
early drift-catching on one real trace, and is far from deployable. That is what a
first benchmark should say. The real benchmark is multi-session, controlled
with/without on real tasks, measuring recovered cost — the next build, not a thing
to fake. Script: drift_bench.py (deterministic, re-runnable).

## Standing next to what exists

[[consciousness-is-the-goal]] — step 1 of the algorithm is the *comparison*, and
this protocol is that comparison turned on the agent's own state: goal versus
where I am, and which way the cost is moving. [[corpus-ground-states-are-circular]]
— the failure mode this exists to catch, at scale. *From Grammar to Coherence*
and the spectral-grammar analyzer supply the coherence measurement; *Ways of
Checking* supplies the caveat that it saturates.
