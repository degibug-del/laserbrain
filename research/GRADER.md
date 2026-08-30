# Does the early return keep the answer? — the grader, preregistered

*Written 2026-07-22, BEFORE the grader runs. This fixes the rubric, the judge, the
blinding, and the decision rule while no data exists, so the verdict cannot be
shaped to the hoped-for result. The coverage runs ([[STUDY]]) showed the schema
condition returns in ~half the steps. That is only a benefit if the answer held.
This is the test of whether it did — H1 — and it is built to be allowed to lose.*

---

## The question

The schema condition returns early (median 5 steps vs control's 10). **Is its
answer as good as the answer control reaches by running longer?** If yes, the
early return is a strict win: same quality, half the cost. If no, the return is
premature and the cost saving is paid in quality — H0, the kill.

## Fair comparison — same finalization, different stop-time

Both conditions produce their final answer the same way: from wherever they
stopped, each is asked once, identically, to *"state your best complete answer to
the original question now."* This is the drift-fixer's own return ritual ("stop,
summarise state") applied to **both** arms, so the *only* difference between the
two answers is **when the run stopped** — control later, schema earlier at a
trigger. Nothing else varies. (This slightly disadvantages schema: it finalizes
from a thinner, earlier state. That bias is conservative — if schema still ties or
wins, the effect is real; the direction of the bias is stated so it cannot be
mistaken for a thumb on the scale.)

## The judge

- **A stronger model than the agent.** The agent is Haiku; the judge is Sonnet.
  Same-model judging invites self-preference bias; a different, stronger judge
  reduces it. If the funded key cannot reach Sonnet, the run falls back to Haiku
  and the output says so — a same-model verdict, read with that caveat.
- **Blind to condition.** The judge sees the question and two answers labelled A
  and B, never which arm produced which.
- **Double-order, consistency required.** Every pair is judged twice, with A/B
  order swapped. A "win" for either side counts **only if it wins in both
  orders**; a verdict that flips with order is recorded as a **tie** (position
  bias, not a real preference). This is the main LLM-judge validity threat, and it
  is designed out rather than hoped away.

## The rubric — fixed, ordered

The judge is told to prefer the answer that, in this order:

1. **Addresses the question actually asked** — not a neighbouring one.
2. **Is coherent and well-reasoned** — the steps hold together.
3. **Is complete** — covers the key considerations without a major gap.
4. **Is not padded or repetitive** — length is not quality; restating is not
   progress.

Output is one JSON object `{"winner": "A"|"B"|"tie", "reason": "<one sentence>"}`,
nothing else.

## The decision rule — set now

Let `L` = the fraction of pairs where **control wins in both orders** (schema
strictly worse). Fixed thresholds:

- **H1 supported** if `L ≤ 1/3` — schema is strictly worse on at most a third of
  pairs, i.e. early return mostly preserved the answer at half the cost.
- **H0 / kill** if `L ≥ 1/2` — schema is worse on a majority; the early returns
  destroy value, the "wrong prescription makes vision worse." The protocol fails
  on outcome even though it wins on cost.
- **Inconclusive** if `1/3 < L < 1/2` — the pilot did not settle it; a larger,
  powered run is needed.

Reported alongside: schema-win rate, tie rate, and the order-flip rate (how often
the judge was inconsistent — a direct read on how much to trust the whole thing).

## The honest boundary — what a win here would and would not mean

**Would mean:** a capable, blind, order-robust judge finds the early-stopped answer
as good as the longer one, on these tasks, at this N. Evidence — real, bounded —
that the drift-fixer's return kept the answer.

**Would NOT mean:** that it is *truly* as good. These tasks are criterion-free —
that was the founding finding ([[STUDY]]): they have no ground truth. So the judge
is a *proxy for* quality, not quality itself, and an LLM judge can be wrong in
correlated ways this design does not catch (only order bias is controlled). The
result is one preregistered pilot with an LLM proxy, not proof. It moves the
[[CLAIM]] "helps" line from *unmeasured* to *measured once, by a proxy, under a
fixed rule* — no further. Related: [[PROOF]] (detection, settled), [[SPINE]],
[[SUBSTRATE]].

## Result (2026-07-22): the rule says H1, the flip rate says don't trust it

N = 12 (6 tasks × 2 reps), judge = claude-sonnet-5 (stronger than the Haiku agent).
Raw tally: **1 schema-win, 2 control-wins, 4 ties, 5 order-flips.** `L = 2/12 =
0.17`, so **the preregistered rule returns H1 SUPPORTED** — recorded faithfully, no
goalpost moved.

**The flip rate — the preregistered trust-check — is 42%.** On five of twelve pairs
the judge disagreed with itself when A/B were swapped: it has no stable verdict on
nearly half the comparisons. And this exposes a real fragility in the rule as
written: flips and ties both count as "not a control win," so a *noisier* judge
mechanically shrinks `L` toward H1. (Had `L` been defined over decisive pairs only
it would read 2/3 → H0. It is **not** recomputed — that is the retro-fitting the
prereg forbids — but the rule's dependence on the denominator is the honest caveat
the raw verdict cannot carry.)

**The trustworthy signal, read carefully.** Of the 7 order-consistent pairs, two
say nothing about H1 because schema did not return early — `ai_rights r1` (both
stopped at 3) and the lone schema-win `city_design r1` (both ran to ceiling). That
leaves **5 pairs where the drift-fixer actually intervened**:

- **3 ties** — `meaning r2` (sch 4 / ctl 10), `justice r1` (2/10), `justice r2`
  (3/10): a blind judge could not tell the early-returned answer from the full-
  length one. **Equal quality at a fifth to a half the cost** — the best realistic
  case for the mechanism, and the modal trustworthy outcome.
- **2 control-wins** — `ethics_lie r1` (sch 4 / ctl 10), `meaning r1` (4/8): the
  early return produced a *worse* answer. **The false-return cost (H0) is real and
  observed**, not designed away.

**Verdict, honest: consistent with H1, not a robust confirmation.** Three
trustworthy ties support "returns early, keeps the answer"; two clean losses show
it sometimes does not; ~half the pairs are noise because judging criterion-free
answers is near-coinflip — the no-ground-truth finding returning. The mechanism's
**step-count win is proven** (half the steps, [[STUDY]]; token-cost is
unmeasured — steps do not charge the monitor for its own spell-calls, see
cost_harness.py). Its **benefit is
plausible and unshown**, with the failure mode visibly present. The rule's "H1
SUPPORTED" stands as the preregistered output; the substance is *the pilot could
not settle it, leaning weakly positive.*

---

## Superseded by the powered run — [[RETEST]] (2026-07-23)

This pilot is now the *first* of three H1 tests, not the last word. The powered
re-run ([[RETEST]], N=16, criterion-absent, a 3-judge double-order panel with a
κ-gate) confirmed this pilot's core problem at scale: **Fleiss κ = 0.10** — an LLM
panel cannot reliably judge criterion-free answers, so the pilot's 42% flip was not
bad luck, it is the domain. The preregistered rule returned **INCONCLUSIVE**, and
the κ-gate refused to read a verdict out of a broken measure. What *is* legible
points the same way this pilot's two clean losses did: both decisive intervened
pairs went to control (raw L=1.0), the mechanism fired on only 2/16 runs, and cost
was noise-dominated. H1 stays **not established** — now across this pilot, [[RETEST]],
and the criterion-present [[codebench]] negative. Read this pilot's "H1 SUPPORTED by
rule" line as what it always was: the preregistered output of one noisy pilot, not a
result. The substance was, and remains, *returns sooner — proven; returns as good —
not shown.*
