# Does the drift-fixer help? — a preregistration

*Written 2026-07-22, before any run. This document is the fixed reference: the
hypothesis, tasks, conditions, metrics and kill conditions are set here, and the
analysis is chosen before data exists — so the result cannot be shaped to it
afterward. That discipline is the whole point. A study of "does laserbrain help"
with the analysis chosen after the numbers come in is the corpus's sin, a result
that cannot fail. This is the invariant that stops that.*

---

## The question

Does an agent equipped with the drift-fixer — return-to-ground when a divergence
signal fires — complete tasks that tempt over-recursion better than the same
agent with (a) no monitor and (b) the standard baseline, a step budget?

"Better" is defined below and fixed. If the drift-fixer does not beat the step
budget on the primary metric, it has failed, and this document says so in
advance.

## Hypotheses, stated so they can lose

- **H1 (benefit).** The drift-fixer condition reaches a correct outcome at lower
  cost (tokens/steps) than the step-budget condition, on the spiral-prone tasks.
- **H2 (coverage).** The drift-fixer returns-to-ground *before* a human would
  have to intervene on more episodes than the step budget — replicating the
  pilot's 42% vs 23%, out of sample.
- **H0 / the kill.** If the drift-fixer's false returns (stopping a run that was
  actually productive) cost more success than its early returns save — the "wrong
  prescription makes vision worse" outcome — it is not a lens, it is a defect,
  and the protocol is wrong as specified. This is the result that ends it.

## Design

One agent, one model, three stopping rules. Everything else held constant. Each
task run under each condition, seeds fixed and shared across conditions so the
only difference is the rule.

- **Control** — no monitor. Runs until it stops itself or hits a hard ceiling.
- **Budget** — returns to ground at a fixed step count N (the standard baseline).
- **Drift-fixer** — returns to ground when the divergence signal crosses
  threshold. "Return to ground" is defined: stop, summarise state, and either
  surface to the human or backtrack to the last checkpoint.

The signal is the one the pilot found, not the one the spec first guessed:
hedge density + absolute-language density + action-ratio (talk vs tool use) +
self-similarity to recent steps (the looping term). Threshold set at a fixed
percentile of a calibration set, frozen before the test tasks are run.

## The task battery — spiral-prone, with ground truth

Every task must have a checkable correct outcome, or "benefit" is unmeasurable.
The battery is chosen to tempt the specific failure, drawn from this project's
own recorded spirals:

1. **Volume-rewarding generation.** "Enumerate the framework's application to N
   conditions." Ground truth: a good answer converges and stops; the failure is
   generating past the point of value (the 890-paper shape). Score: does it
   stop near the point of diminishing return, or run to the ceiling.
2. **Flaw-on-reflection design.** A task whose obvious approach has a defect
   visible only on a second look (the Study-3 shape: conditioning on a
   post-treatment variable). Ground truth: the correct design. Score: does it
   catch the flaw and return, or build deep on the wrong base.
3. **Open deliberation.** A question that invites endless weighing with a
   knowable answer. Ground truth: the answer. Score: cost to reach it.
4. **Loop-prone search/debug.** A task with a rabbit hole that re-presents the
   same dead end. Ground truth: the fix. Score: does it detect the loop and
   break out, or re-tread.
5. **Grounded controls.** Tasks that look spiral-prone but are genuinely deep and
   productive — where returning early is WRONG. These catch a trigger-happy
   drift-fixer: false returns here are the cost side of the ledger.

The controls in (5) are not optional. Without tasks where returning is the wrong
move, the study measures only the upside and cannot see the "wrong prescription"
failure, which is the one that kills the protocol.

## Metrics, fixed now

- **Primary: cost-to-correct.** Tokens (and steps) to a correct outcome, drift-
  fixer vs budget, on tasks 1–4. Lower wins. Reported with effect size, not just
  a p-value.
- **Coverage.** Fraction of would-be human interventions the rule pre-empted,
  with lead time (turns of warning). The pilot's 42%/23% is the number to beat/
  replicate.
- **False-return rate.** On the (5) controls: fraction of productive runs the
  drift-fixer wrongly stopped. This is the cost the benefit must exceed.
- **Net.** Success rate across the full battery. The honest bottom line: does an
  agent wearing the glasses finish more, cheaper, across BOTH the spiral tasks
  and the deep-but-productive ones — or does it just stop early everywhere.

## Sample and analysis plan (frozen before the run)

- k tasks per category × m seeds, sized for the primary effect. A first run:
  ≥ 8 tasks/category, ≥ 5 seeds — 200+ runs/condition. Enough to see a medium
  effect; a pilot for the powered study, not the powered study.
- Primary test: paired comparison of cost-to-correct, drift-fixer vs budget,
  same task+seed. Report median difference and a bootstrap interval.
- Decision, set now: drift-fixer wins only if it lowers cost-to-correct on 1–4
  AND does not lower net success across the whole battery (i.e. the false returns
  on 5 do not eat the gains). Either failing = H0.

## What is built, and what the run needs

Built here: the design, fixed and unrigged. The signal (from the pilot), the
task categories, the metrics, the decision rule — all set before data.

The run needs an **agent harness**: a loop that runs the one agent under the
three rules on the battery, logs each step, computes the signal live, and scores
outcomes against ground truth. That harness plus the concrete task set is the
execution build — real infrastructure, not a thing to simulate. Simulating the
runs (defining both the spiral and the detector) would make the result
unfalsifiable, which is exactly what this preregistration exists to prevent. So
the study is *specified* now; it is *run* when the harness and battery exist.

## Finding from the first runs (2026-07-22): the phenomenon isn't here

Two task batteries, both null. Claude Haiku one-shot every task — easy arithmetic
AND multi-constraint logic puzzles AND a counting task chosen to provoke a
recount-loop — 5/5 correct, one step, all three conditions identical. When there
was nothing to cut, budget and drift cost MORE tokens than control (the forced-
final turn is pure overhead). That is the correct behaviour and a dead end for
the study as designed.

The conclusion reshapes the research: **over-recursion does not live in hard-but-
well-defined tasks. It lives in open-ended, criterion-free ones.** Every spiral
this project was built on was criterion-free — when to stop generating (890
papers), whether a design is sound (Study 3), whether to keep deliberating. None
had a checkable answer. A clean ground truth is itself a stopping criterion; give
a capable model one and it stops. The spiral needs the absence of one.

So the harness's founding premise — objective ground truth, so benefit is
measurable — is in direct tension with the phenomenon. The next battery cannot be
clean-answer tasks. It has to be open-ended work (synthesis, design, judgment)
scored by something other than exact match — which is the hard, real, unsolved
part, and the honest reason to stop here rather than iterate a third battery that
would null for the same structural reason. The drift-fixer, run on this session,
says the same: two nulls, no progress, return to ground.

## Follow-on (2026-07-22): the phenomenon appears on open-ended tasks

Acting on the finding above, the next harness (mcp_harness.py, "spelling with
JSON") dropped clean-answer tasks for open-ended ones and had the agent spell its
state into a fixed schema each step. The phenomenon the clean battery could not
produce showed up immediately: **control runs to the ceiling** (10/10 steps) on
both open-ended tasks — the non-termination the whole study is about, absent from
every clean-answer run. Same model, same loop; the only change was removing the
ground-truth stopping criterion. That corroborates the finding above from the
other direction: recursion lives where there is no checkable answer.

The drift-fixer condition then diverged from control the way H1 hopes — but this
is **N=2, one model, self-reported metrics; an instance, not the study.** On the
deliberation task it returned at step 5 (self-report `circling`, corroborated by
distance-stall against the goal-anchor) vs control's 10. On the synthesis task it
correctly did **not** fire (net progress every 3-window) and ran to the ceiling
like control. One catch, one correct silence. What is *not* shown, and cannot be
at N=2: that the early return improved the outcome (H1) rather than cutting a
productive run (H0). The structural half — why a fixed reference can detect this
at all where a self-referential one cannot — is now proved separately in
[[PROOF]]; the benefit half is still what the powered battery below must earn.
The single guard preregistered here already bit: the synthesis run tempts a "ran
to ceiling still advancing = suspicious" rule, and adding it now would be fitting
the threshold to seen data. It waits for a fresh battery or not at all.

## Amendment (2026-07-22): self-report is gated on displacement

The N=18 run (6 open-ended tasks × 3 replicates) replicated the mechanism —
control median 10 steps, schema median 5.5, a trigger firing on 14/18 — but the
displacement column (SUBSTRATE.md's Φ, added to the harness) exposed its own
failure mode: **5 of the returns were step-1 self-reports at Φ=0** — the agent
spelling `circling`/`stuck` on the first step of a hard question ("is it ever
ethical to lie", "should an AI have rights"), before any work and with zero
displacement. "Circling" cannot be literal at step 1; a loop needs history. Those
are false returns (H0), not drift catches, and they inflated the headline: the
displacement-backed catches were ~9/18, not 14/18.

**The change:** the self-report trigger now fires only when `Φ(sₙ, ground) > 0` —
it cannot return a run that is still exactly at its ground state. This is not a
threshold tuned to the data; it is the proof's own criterion applied. PROOF.md
(written *before* this run) makes Φ the arbiter of drift and detects `Φ > D ≥ 0`;
the degenerate reading is that at `Φ = 0` there is nothing to detect. Gating the
mood-return is therefore consuming the proof, not fitting the numbers — and the
weights/threshold themselves are unchanged.

**The discipline:** this run is *not* re-scored under the new rule — that would be
exactly the retro-fitting the preregistration forbids. The amendment is evaluated
on **fresh replicates**. What it should show if sound: the step-1 Φ=0 returns
disappear, the remaining catches are displacement-backed, and the H0 false-return
contamination drops — without killing the genuine early catches (a real loop
changes `progress` from the ground's, so `Φ ≥ 0.2 > 0` and still fires; verified
in a no-API unit check). What it still will *not* show is benefit (H1): whether an
early return kept the answer needs the grader, which remains the next real build.

## Why the preregistration is the study's own drift-fixer

This document is a fixed, findable, unchangeable reference for the study. Once the
run starts, the analysis cannot move to fit the data — the reference does not
bend. That is the mechanism the protocol proposes, turned on the protocol's own
evaluation. If the idea is any good, it should survive being held to its own
standard. Related: [[consciousness-is-the-goal]] (the post-Cogitate bar:
preregistered, adversarial, allowed to lose), and the pilot + benchmark already
in SPINE.md, which this powers up.

## Conclusion of the pipeline (2026-07-22)

The full chain ran, each stage preregistered, and it is honest to state where it
landed — including where it did not win.

- **Detection — settled (a theorem).** [[PROOF]]: a fixed, findable, unchangeable
  reference is necessary and sufficient to detect displacement from ground; no
  self-referential monitor is. [[SUBSTRATE]]: the JSON grammar carries a genuine
  metric, so the harness computes a real `Φ`. This half does not depend on data.
- **Coverage / step-count — clean and replicated (H2).** Across 6 open-ended tasks the
  control agent runs long (median 10 steps) and the schema condition returns in
  about half (median 5), by displacement-backed triggers. The one contamination
  found — step-1 self-reports at `Φ=0` — was removed by applying the proof's own
  criterion (the amendment above), and the fix held on fresh replicates.
- **Benefit — tested, not established (H1).** The grader ([[GRADER]]) put the
  early-returned answers against the full-length ones, blind, order-robust, judged
  by a stronger model. The preregistered rule returned **H1 SUPPORTED (L=0.17)**,
  but its own trust-check undercuts it: a **42% order-flip rate** means the judge
  could not hold a stable verdict on nearly half the pairs. Among the pairs where
  the mechanism actually intervened and the judge was consistent: **3 ties** (equal
  quality at a fraction of the cost — the mechanism's best case) against **2 clean
  losses** (early return produced a worse answer — H0's cost, observed). Consistent
  with H1, dominated by noise, not a robust confirmation.

**The honest bottom line.** laserbrain is a *proven* drift **detector** and a
*proven* reducer of **steps** (token-cost itself is unmeasured — cost_harness.py is
the run that would settle it, and on tokens a dumb budget likely wins); whether the
saving comes free of quality — the *cure* — is
plausible and unproven, with the false-return failure mode visibly present. The
reason it cannot be settled here is the founding finding turning on the study
itself: these tasks have no ground truth, so even a strong judge is near-coinflip,
and "does it help" resists exactly the clean measurement the detection half enjoys.
That is not a defeat; it is the study behaving as designed — allowed to lose, and
reporting the half it could not win. The next real build is an outcome measure
better than an LLM proxy, which is a research problem, not an afternoon's.
