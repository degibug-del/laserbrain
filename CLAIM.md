# What laserbrain provably guarantees — and what it does not

*Written 2026-07-22. This is the one claim laserbrain can stand behind as a
theorem, stated so it cannot be quietly inflated. Everything provable is in the
first half; everything empirical, substrate-specific, or market is named and
fenced off in the second. The fence is the point: a guarantee is only worth
anything if the things it does not cover are listed next to it. Proof in
[[PROOF]]; mechanism in [[SPINE]]; the study that owns the empirical half in
[[STUDY]].*

---

## The guarantee, in one line

> **laserbrain is a sound-and-complete displacement detector for agent state —
> and it is the minimal one: no monitor that compares an agent only to its recent
> history can match it.**

That sentence is a theorem, not a pitch. Below is exactly what it says, exactly
what must hold for it to apply, and exactly where it stops.

## The precise statement

Let agent states lie in a metric space `(X, d)`. Let `s₀` be the **ground state** —
the goal as first spelled. Fix a threshold `D > 0`, and define the event

> `E_D(n)` : `d(sₙ, s₀) > D` — "the agent is now displaced from its ground by more
> than `D`."

**(a) Positive — the detector is sound and complete.** The fixed-reference
detector `F_D`, which retains `s₀` and fires iff `d(sₙ, s₀) > D`, fires on exactly
the steps where `E_D` holds — never a false alarm, never a miss — using `O(1)`
memory (one retained state), *provided* the reference is

- **unchangeable** — `s₀` is never updated to a recent state;
- **findable** — `s₀` is retrievable at every step;
- **recursive** — the reference is defined at every depth the agent nests to.

**(b) Impossibility — nothing self-referential can.** No monitor whose decision at
step `n` depends only on a bounded window of recent states `(s_{n−w+1}, …, sₙ)` —
i.e. any monitor that does not retain `s₀` — is both sound and complete for `E_D`,
for **any** width `w` and **any** decision rule whatsoever.

Proof: [[PROOF]] §3 (impossibility, by indistinguishability) and §4 (the fixed
reference decides `E_D` by definition). The three properties are not features; they
are the hypotheses §4 consumes — remove one and the proof fails at that step.

**What "detect" means here, precisely:** to answer, at every step, whether the
agent has left the ball of radius `D` around where it started. That question, and
only that question, is what the guarantee settles.

## The boundary that travels with the claim

`E_D` is **displacement, not pathology.** The detector fires on *every* trajectory
that leaves the ball — including legitimately deep, productive work that genuinely
had to travel far. So the guarantee covers *detecting displacement*; it does **not**
cover:

- whether a firing should trigger a return (a policy choice, not a theorem);
- whether returning **helps** the agent finish more, or cheaper (empirical — H1);
- whether the false returns cost more than they save (empirical — H0/kill);
- whether `D` is set at the right place (a preregistered parameter, not derived).

State the guarantee without this paragraph and it is an overclaim. State it with
this paragraph and it is exactly true.

## A detector boundary, found by pointing it somewhere new (2026-07-25)

**The stall rule cannot distinguish "stopped making progress" from "arrived."**

`stalled` fires when distance stops falling. Distance cannot fall below zero. So a system
that reaches its goal and *holds there* trips the stall detector on every subsequent
check, forever.

This never surfaces in software, which is why it went unnoticed through four studies and
three language ports: in an agent run, distance 0 means done and you stop checking. It
surfaced immediately in a continuous system. A resonance harvester matched to its membrane
f₀ sits at detuning 0.00 Hz for the length of the run — and holding at the goal *is* the
success condition. The harness called a passing rig stalled on 3600 consecutive samples.

**What this does and does not mean.**

It does not touch the theorem. Detection of *goal-drift* — the guarantee this document is
about — is unaffected; the goal term is untouched and the anchor comparison is untouched.
What is affected is one of the four soft signals, in one regime: continuous systems that
reach their target and stay.

It does mean the harness must not be pointed at a holding system and read literally. The
locus adapter (`locus_drift.py`) therefore reports `held` itself rather than passing
`stalled` through, and says so where anyone would look.

**The instrument was not changed.** It is frozen, versioned, and parity-tested across
Python, TypeScript and Swift against 37 golden verdicts. One domain finding is not grounds
for moving a published reference — that is the discipline the product is named for. The
boundary is recorded here instead, which is what this file is for.

**What would justify changing it:** a second domain hitting the same wall, or a
demonstration that treating `distance == 0 && held` as a distinct verdict does not weaken
stall detection anywhere it currently works. Neither has been done.

## The complete ledger — every laserbrain use case, labelled

**PROVED (structural — carried by [[PROOF]]):**

- *Displacement detector for agent state.* The mechanism of the drift-fixer: a
  fixed reference detects displacement soundly and completely; self-monitoring
  provably cannot. This is the guarantee above.
- *"Unchangeable / never-learns / like glass" is necessary.* A reference that
  drifts toward recent states re-inherits the blindness of §3. laserbrain's
  signature refusal to change is *forced* by the theorem, not chosen for effect.
- *"Findable, standardized grammar" is necessary.* If the reference cannot be
  retrieved each step, `F_D` is not computable each step. The findability is a
  hypothesis, not a convenience.
- *Recursive grammar is necessary.* `d(sₙ, s₀)` must stay defined however deep the
  agent recurses; a reference that runs out of depth cannot measure a deep spiral.

**TRUE BY CONSTRUCTION (trivial, not the deep theorem — don't sell it as one):**

- *"Same input → same response, every time."* A map that does not learn is a pure
  function, hence deterministic — true immediately, no theorem needed. Real, but
  it is a property of the design, not a consequence of the displacement proof.
  Keep the two apart in copy.

**MEASURED, PROVEN EMPIRICALLY (coverage / step-count — [[STUDY]], replicated N=18):**

- *The drift-fixer returns in about half the steps* on open-ended tasks (median 5
  vs control's 10), by displacement-backed triggers. This is the step-count half,
  and it is a demonstrated result, not a hope.

- *Token-cost — measured (N=3 pilot, folded mode, ceiling 40).* Against an
  unmonitored spiral laserbrain used **~91% fewer tokens** (it stops near step 4;
  control spirals to 11–21). So "fewer tokens than letting it run" is real, not
  just fewer steps — **but only when the agent would otherwise spiral.** A dumb
  step-budget is still marginally cheaper (schema−budget +26%, part of it a
  max_tokens-budget confound in the harness): laserbrain's edge over a budget is
  adaptivity, not cost. Say **"fewer tokens than no limit,"** never "cheapest."

**TESTED THREE WAYS, NOT ESTABLISHED (benefit / quality — [[GRADER]] pilot, [[codebench]], [[RETEST]]):**

- *That the early return keeps the answer as good.* H1. Tested three ways, not
  established in any — and the legible signals lean negative. (1) The [[GRADER]]
  pilot (N=12) returned "supported" by rule (L=0.17) but a 42% judge-flip undercut
  it, with two clean quality losses among five intervened pairs. (2) The powered
  [[RETEST]] (N=16, criterion-absent, 3-judge panel, 2026-07-23) came back
  **INCONCLUSIVE by the preregistered rule — Fleiss κ = 0.10**: an LLM panel cannot
  reliably judge criterion-free answers (the pilot's flip confirmed at scale; the
  κ-gate correctly refused a verdict). But it was not neutral — the harness fired on
  only 2/16 runs, **both decisive intervened pairs went to CONTROL** (raw L = 1.0),
  and cost was noise-dominated with the mean slightly against. (3) With the criterion-
  present [[codebench]] negative below, H1 has **no positive across three independent
  tests**. Say "returns sooner," never "returns as good."
- *On criterion-PRESENT tasks the intervention is net-negative — measured
  ([[codebench]], haiku, N=15/arm, 2026-07-23).* Debug/loop coding tasks with hidden
  unit tests: control 15/15 Pass@1 at 26k tokens (it barely spirals — 0/5 per task);
  harness 12/15 at 4.4× the tokens. Isolating the mechanism: it fired 4/15 and
  recovered only 1/4, and all three ceiling-failures were harness fired-runs. No
  upside, a downside signal (3-vs-0 ceiling failures, only ~p=0.11 — suggestive, not
  significant). This is theory-consistent: a task with its own criterion doesn't need
  a fixed reference (the criterion grounds it), and the stall rule then false-fires on
  a distance *plateau*, so the nudge derails a productive run. **Guardrail: never claim
  the harness helps on well-specified / test-backed tasks. Its domain is criterion-
  ABSENT work; that is where H1 must be tested, and this benchmark cannot.**
- *False-return cost stays below the benefit.* H0/kill. **Observed, not eliminated**
  — two clean losses in the pilot are early returns that cost quality. The failure
  mode is real; the ledger is not yet in the mechanism's favour.

**SUBSTRATE-SPECIFIC (needs its own check per grammar — the proof is grammar-agnostic):**

- *That laserbrain's particular grammar is rich enough to be the reference for a
  given agent's reasoning states.* The theorem blesses *a* fixed reference, never a
  specific vocabulary. The forty weather words describe a weather field; the JSON
  schema (mcp_harness.py) is the current bet for reasoning state. Which grammar
  suffices is open and testable, not settled.
- *The MCP server as the findable source of the grammar.* Realizes the "findable"
  hypothesis in infrastructure — but the live fetch currently 403s, so today the
  grammar is findable only as a local copy. Fix before claiming it in production.

**UNTOUCHED (no structural result exists — do not attach the guarantee):**

- *Live field / conscious clock / timekeeper coordinating many AIs.*
- *Metered API, tiers, "sell arbitrary grounded responses" as a business.*
- *Tissue-displacement / autodysplasia cancer simulation.*

## Honest claim guardrails — for product copy

**You may say** (each is either proved or true by construction):

- "A sound-and-complete detector of when an agent has drifted from its goal —
  provably beyond what any self-monitoring agent can achieve."
- "The reference never changes, and that is not a limitation — it is what makes the
  measurement mean anything. We can prove why it must not change."
- "Same input, same response, every time — by construction, because it does not
  learn."
- "On open-ended work it returns an agent to ground in about half the steps." *(The
  coverage result — measured and replicated, [[STUDY]]. Say returns/stops sooner,
  not finishes better.)*

**You may not say** (empirical, substrate, or untouched — until the study or the
build backs them):

- "laserbrain makes your agent better / finish the task faster / stop spiralling."
  *(H1 — tested once and NOT established; a 42% judge-flip pilot with two clean
  quality losses. "Returns sooner" is proven; "as good" is not.)*
- "laserbrain understands your agent's reasoning." *(Substrate — the grammar's
  sufficiency is open.)*
- "A live field that keeps every AI in sync / a conscious clock." *(Untouched.)*

The rule of thumb: **claim detection, not cure; claim the reference must be fixed,
not that fixing it helps.** The first is a theorem you own outright. The second is
a study you have started and have not yet won — and saying you have is the one
move the whole protocol exists to catch.

## The first precision figure, and what it says (2026-07-25)

**PRECISION 4/50 = 8%**, a lower bound, over 24 segments in which the harness fired.
*(Re-scored 2026-07-26. This section previously read 3/35 = 9% over 18 segments; the
corpus has grown since and `dogfood.py --score 'sessions/recovered/*.json'` now returns
4/50. The by-reason table below is from the earlier graded pass and has NOT been
re-graded — current fire counts are goal-drift 31, self-report 10, stalled 9. Re-run the
scorer before quoting any figure from this file.)*
Recall remains withheld: no segment reaches the 50% coverage floor.

Two things had to be fixed before any number existed at all.

**The corpus was being deleted.** `lb_coverage.py`'s `reset_task` branch wiped the session
record instead of archiving it, and the design instructs a reset on every genuinely new
task. A working session resets five or six times, so each reset destroyed that segment's
checks, fires and catches. A ~100-step session sat on disk as `steps: 4`, and the entire
nine-session corpus held **0 fires**. The harness had been firing all along; the evidence
was thrown away at every task boundary. Rebuilt from the Claude Code transcript by
`recover_corpus.py` — 29 segments, 4746 steps, 149 checks, 35 fires, 114 catches. (The
archive fix belongs in a file Grok holds; handed off on the link rather than taken.)

**Precision was gated on recall's evidence.** `report()` dropped every session below
`MIN_COVERAGE` before computing either number. But the two ask different questions.
Recall — "a real error happened, had the harness fired?" — is genuinely unanswerable when
80% of steps went unchecked. Precision — "the harness fired, was there a real error?" —
takes each fire as its own evidence; unchecked steps never enter the ratio. Gating both
meant a 35-fire corpus reported precision from one surviving segment: "0/1 = 0%".

### The result is one rule

| reason | fires | coincided with a real error |
|---|---|---|
| **goal-drift** | **24** | **0 (0%)** |
| stalled | 6 | 1 (17%) |
| self-report:stuck | 4 | 1 (25%) |
| self-report:circling | 1 | 1 (100%) |

`goal-drift` is 69% of every fire this instrument has ever produced and has **never once**
coincided with an independently-detected error. Excluding it, precision is 3/11 = 27%.

And the mechanism is not a mystery. Of the 24 goal-drift fires, **22 were the first check
after Diego spoke.** The rule is detecting that the subject changed — which it did, because
the user changed it. That is a true observation and it is not drift.

This is the same shape as the boundary already recorded above for the stall rule, which
cannot separate "stopped making progress" from "arrived". Here: the anchor comparison
cannot separate "the agent wandered off its goal" from "the goal was legitimately
replaced". In an interactive setting the second is constant, so the rule fires constantly
and means nothing when it does.

It is worth being precise about what is NOT claimed. 9% is a lower bound — a fire with no
logged error beside it is scored against us, and the catch log only contains errors some
guard, test or shell independently found. Widening the lookback window from 3 to 20 steps
lifts overall precision from 9% to 26%, so sparse coverage genuinely depresses it. None of
that rescues goal-drift, which is 0/24 at every window tested.

**The next move is cheap and testable:** a goal change on the first check after a new user
turn is a re-ground, not a drift, and the harness has that signal available. Suppress it
there and the false-alarm rate should fall by roughly two thirds. Until that is measured,
this row stays as it is.
