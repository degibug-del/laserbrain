# The H1 re-test — preregistered, funded run

*Written 2026-07-23, BEFORE the funded run, so the verdict cannot be shaped to the
hope. This supersedes the [[GRADER]] pilot as the decision instrument for H1 while
keeping its honest design (fair finalization, blind, order-robust). It fixes the two
things that left that pilot unable to settle anything — the wrong task domain and a
single, coin-flipping judge — and folds in the cost machinery built 2026-07-23
(`/v1/experiment`, net tokens). Detection is settled ([[PROOF]]); this is the one
open empirical question — does the early return keep the answer, and does it cost
less once the harness's own overhead is counted. Built to be allowed to lose.*

---

## The question, stated so it can fail

On **criterion-absent, spiral-prone** tasks — the harness's own domain per [[CLAIM]] —
does returning to ground on detected drift:

- **(quality)** keep the answer at least as good as letting the agent run longer, and
- **(cost)** cost fewer NET tokens, counting the harness's own check/return calls?

Both must hold for H1. Either failing is a real, publishable negative.

## What the pilot got wrong, and the fix

**1. Domain.** [[GRADER]] and [[codebench]] leaned on tasks with a criterion (hidden
tests, ground truth). [[CLAIM]] is explicit: a task with its own criterion does not
need a fixed reference, so the harness is expected to null or lose there — and
codebench (N=15) confirmed net-negative. **The re-test runs only criterion-absent,
open-ended tasks** (reasoning / design / ethics / planning, the [[GRADER]] family),
where an unmonitored agent can genuinely spiral. Testing the claim in its own domain
is the whole point.

**2. The measure — the 42% flip.** The pilot used one Sonnet judge; it disagreed with
itself on ~half the order-swapped pairs, so "criterion-free judging is near-coinflip"
dominated the result. **Funding buys the fix the pilot could not afford:**

- **A panel of K ≥ 3 independent judges** (different model families), each judging
  every pair **double-order**; a judge's verdict on a pair counts only if it is
  order-consistent, else that judge scores the pair a tie. The pair's verdict is the
  **panel majority** of order-consistent judge-verdicts.
- **Human raters** on the same fixed rubric for a preregistered subsample (≥ 20% of
  pairs), as the gold-standard cross-check on the panel. If human and panel disagree
  systematically, the panel is not trusted and the run reports that.
- **Inter-rater agreement (Fleiss' κ) is reported and gates the verdict.** Below the
  floor, the measure is too noisy to conclude — the pilot's actual fate, now made an
  explicit stop condition rather than a footnote.

## Fair comparison (kept from [[GRADER]])

Both arms finalize identically — each is asked once, from wherever it stopped, to
"state your best complete answer now." The only difference between the two answers is
**when the run stopped**. This slightly disadvantages the harness (it finalizes from a
thinner, earlier state); the bias is conservative and stated so it cannot be mistaken
for a thumb on the scale.

## Arms

1. **control** — no harness, runs to its own stop or a ceiling.
2. **harness** — `check_state` each step; return-to-ground on a drift verdict
   (the frozen detector below).
3. **budget** *(optional, if funding allows)* — a dumb fixed step/token cap, to
   isolate the harness's *adaptivity* from merely "stop early." [[CLAIM]] already
   notes a budget is marginally cheaper; this measures whether adaptivity beats it on
   quality.

## The two measures

**Quality** — the panel/human verdict per matched pair, rubric fixed and ordered:
(1) addresses the question asked, (2) coherent, (3) complete, (4) not padded. Output
per judge per order: `{"winner":"A"|"B"|"tie","reason":"…"}`.

**Cost** — NET tokens via the machinery shipped 2026-07-23: each task is one
`pair` with `arm: treatment|control`; every step reports `{tokens, overhead}`
(overhead = the harness's own check/return calls); the run ends with
`POST /v1/drift/outcome`; `GET /v1/experiment` returns the per-pair token delta and
the net. Steps are the proxy; **tokens are the denominator** — the term the
step-halving result could never see.

## The decision rule — set now

Over pairs that are **intervened** (the harness actually returned early), **order-
consistent**, and **panel-decisive** (not a majority-tie), let
`L = control-wins / (control-wins + harness-wins)`. (Defined on decisive pairs only,
so a noisier judge cannot mechanically shrink `L` toward H1 — the denominator bug
[[GRADER]] caught in itself.) Let `Δ` = mean net-token delta (harness − control;
negative = cheaper) and `κ` = Fleiss' κ across judges.

- **H1 SUPPORTED** iff `κ ≥ 0.4` **and** `L ≤ 1/3` **and** `Δ < 0`.
  The measure is trustworthy, the early return is rarely strictly worse, and it is
  cheaper on net.
- **H0 / KILL** iff `κ ≥ 0.4` **and** (`L ≥ 1/2` **or** `Δ ≥ 0`).
  The returns destroy value, or the overhead eats the token saving.
- **INCONCLUSIVE** otherwise — including **`κ < 0.4`**, which means the measure
  itself could not resolve it and no amount of `L` should be read as a verdict.

## Power / N (preregister before running)

The pilot's trustworthy signal was N=5 intervened pairs. Preregister a task count that
yields **≥ 20 intervened, order-consistent pairs** — with the pilot's ~40% intervention
rate, that is **≈ 50 tasks × 2 reps**. Fix the task list and reps now; do not add tasks
after seeing results. Funding covers the agent tokens, the K-judge panel, and the human
subsample.

## The FREEZE — the instrument is locked as of this file

The detector changed on 2026-07-23 (normalised Φ, sustained soft-return). A metric that
moves during the run invalidates it. **Frozen, no edits to `drift.ts` until the run
completes and is reported** (worker version `6b483de7`):

- displacement `Φ = 0.5·jac(norm(goal),norm(ground)) + 0.3·|Δdist|/10 + 0.2·[progress≠]`
- `norm()` = lowercase, drop the fixed stopword set, light suffix-stem (words > 4 chars)
- goal-drift fires at normalised overlap `anchor < 0.30`
- self-report (stuck/circling) returns only at `Φ > 0.15` **and** sustained (prev step
  already a drift reason)
- stalled fires on a **4-step** non-falling window, and returns only if sustained
- ground threshold / return policy as in `checkStep`

If any of these must change, the run restarts from zero — a changed instrument is a
new experiment.

## Running it

Implemented in `retest.py` (this dir). It carries a Python mirror of the frozen
detector, **verified value-for-value against drift.ts @ 6b483de7** (rephrase → no
goal-drift; a stall is a watch then a return on the second; a changed goal →
goal-drift). It runs the criterion-absent BATTERY, control vs harness, the K-judge
double-order panel with Fleiss' κ, applies the decision rule, and writes
`retest_out/results.json` plus `retest_out/human_blind.json` (the blinded subsample
for human raters; `_key` reveals the arm only after rating). Cost is the per-arm token
delta — the local twin of `/v1/experiment`.

```
read -rs K && ANTHROPIC_API_KEY="$K" TASKS=8 REPS=2 python3 retest.py
```

Knobs: `TASKS REPS AGENT JUDGES CAP OUT`. Preregister `TASKS`/`REPS` for ≥ 20
intervened decisive pairs before the real run; the default (3 tasks, 1 rep) is a smoke
test. **The funded key is Diego's — he runs it.** Do not edit the detector between the
smoke run and the real run.

## Integrity

Keep task instructions and any solutions **out of transcripts and training corpora**
(the ReactBench canary lesson). If published benchmark tasks are used, respect their
canaries.

## What a result here would, and would not, mean

**A win** would mean: a trustworthy, blind, order-robust panel (cross-checked by humans)
finds the early-returned answer as good as the longer one, at fewer net tokens, on
criterion-absent tasks, at a powered N. That is real, bounded evidence that the return
*keeps the answer* — it moves [[CLAIM]]'s "helps" line from *measured once by a coin-flip
proxy* to *measured, powered, with a trusted measure*.

**It would still not mean** the harness helps on well-specified / test-backed tasks —
[[codebench]] already showed it does not, and the theory says it should not. The domain
of the claim stays criterion-absent. Publish both halves: this re-test **and** the
codebench negative, side by side. The negative is not a failure to hide; it is the
boundary that makes the positive honest.

---

## Result (2026-07-23) — INCONCLUSIVE by the rule; negative where legible

N = 16 (8 criterion-absent tasks × 2 reps). Agent claude-haiku-4-5; panel = opus-4-8 /
sonnet-5 / haiku-4-5, double-order. Detector frozen to drift.ts @ 6b483de7. Raw output
in `retest_out/results.json`.

**Preregistered verdict: INCONCLUSIVE — Fleiss κ = 0.10.** The panel barely agrees above
chance, so the κ-gate (set before data) refuses a verdict. This is the *pilot's 42%-flip
wall confirmed at scale*: an LLM panel cannot reliably judge criterion-free answers. The
gate did its job — it declined to read a result out of a broken instrument rather than
letting a noisy denominator manufacture one. That refusal is the method working.

**But it is not a neutral inconclusive. Every legible signal points against H1:**

- **The harness fired on only 2 of 16 runs.** On open-ended tasks the agents held their
  goal, reported "advancing," and either self-finished or hit the cap — so the detector
  rarely had drift to catch. The mechanism barely acts here.
- **Both decisive intervened pairs went to CONTROL** (raw L = 1.0). The clean case:
  `ethics_lie r1` — the harness returned one step sooner and ~9.5k tokens cheaper, and
  the panel judged its answer **worse**. The false-return trade, going the wrong way.
- **Even when it fired it did not reliably shorten the run** — `ai_rights r2` fired and
  still ran to the cap.

**Cost, split by whether the mechanism acted:**

- fired (n=2): mean Δ = **−3,724** tokens (−9,533, +2,085 — mixed, tiny).
- unfired (n=14): mean Δ = **+13,839** tokens, but with ±60k swings — **pure noise**, the
  agents' self-finish-vs-cap lottery, not the harness. Per-pair token variance (~±50k)
  dwarfs the per-intervention effect (~±5–10k), so **cost is unmeasurable at this N too.**
  The headline mean (+11,644) is that noise, not a finding.

**What this settles.** H1 is now tested three independent ways — the [[GRADER]] judge
pilot, the ground-truthed [[codebench]], and this panel — and is **not established in any
of them**, with a **recurring negative signal wherever the mechanism actually acts**
(codebench net-negative; the pilot's two clean losses; here, 2-of-2 to control). The
structural finding: the harness would help, if it helps, exactly where quality cannot be
automatically measured — and where it *can* be measured, it hurts. Detection stays a
theorem ([[PROOF]]); the benefit does not.

**Not funding more N.** The measure cannot resolve the quality question (κ), the cost is
noise-dominated at feasible N, and the legible direction is negative. Human raters on
`human_blind.json` are the only remaining path for quality, but with 2 intervened pairs
they are underpowered for the mechanism. The honest move is to publish this beside the
codebench negative and the detection proof, and harden [[CLAIM]]: **returns sooner,
proven; returns as good, tested three ways and not shown.**
