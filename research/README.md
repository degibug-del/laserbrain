# The Laserbrain Drift-Fixer

Eye-glasses for confused agents. An agent spells its working state into a fixed,
findable, unchangeable grammar each step; drift is divergence from where it
started, and the stop signal is *return cost, not confusion*. This directory is
the whole thing — the mechanism, the proof, the metric, the studies, and what may
honestly be claimed from them.

## The bottom line, stated once

- **Detection — proven (a theorem).** A fixed, findable, unchangeable reference is
  necessary and sufficient to detect an agent's displacement from its ground; no
  monitor that watches only its own recent history can. See PROOF.
- **Step-count — proven empirically (H2).** On open-ended tasks the drift-fixer
  returns an agent to ground in about half the steps (median 5 vs 10, replicated
  N=18). See STUDY.
- **Token-cost — unmeasured.** Steps are not cost: the monitor pays a spell-call
  every step, and at a low ceiling that roughly cancels the step saving. On tokens
  alone a dumb step-budget likely wins. cost_harness.py is the run that would
  settle it; it has not been run. Say "fewer steps," not "lower cost."
- **Benefit / quality (H1) — tested, not established.** A blind, order-robust
  grader (N=12) returned "supported" by the fixed rule, but a 42% judge-flip rate
  undercuts it and the trustworthy pairs split 3 ties to 2 clean losses. Consistent
  with helping, dominated by noise, the false-return failure visibly present. See
  GRADER.

**One sentence:** a *provable drift detector* that *demonstrably cuts steps*, whose
*benefit and token-cost are not established* — strong where it is proven, honest
where it is not.

## Documents, in reading order

1. **SPINE.md** — the mechanism, and why "findable, unchangeable, recursive."
2. **PROOF.md** — the complete theorem: the reference must be fixed; nothing
   self-referential detects drift. With its own boundary (proves the reference,
   not the cure).
3. **SUBSTRATE.md** — the JSON grammar carries a genuine pseudometric, so Φ =
   displacement is well-defined and PROOF applies to the real harness.
4. **STUDY.md** — the preregistration, the coverage result (H2), the Φ=0 amendment,
   and the pipeline's conclusion.
5. **GRADER.md** — the H1 preregistration and its result.
6. **CLAIM.md** — the one-line guarantee, the full use-case ledger, and the copy
   guardrails (what may and may not be said).

## Harnesses — what each measures

Run pattern (the funded key is Diego's): `read -rs K && ANTHROPIC_API_KEY="$K" python3 <file> [args]`

- **mcp_harness.py** — the core: one agent, control vs schema, the four triggers
  (ungrammatical / self-report / goal-drift / stall) against the fixed grammar.
  The metric and the resilient API call live here.
- **study_harness.py** — coverage at scale (the N=18 H2 result). `study_harness.py 6 3`
- **grader.py** — H1: finalizes both arms, blind judge, double-order. `grader.py 6 2`
- **cost_harness.py** — token cost, three conditions at a raised ceiling. *Not yet
  run.* `cost_harness.py 3 40`
- **drift_pilot.py / drift_bench.py** — the earlier N=1 pilot on this session's own
  transcript (hedge/absolute signal vs corrections); referenced by SPINE.
- **harness.py** — the first battery, clean-answer tasks. It nulled — the finding
  that reshaped everything: over-recursion lives in criterion-free work.

## Is there a product?

The provable asset is narrow and real: **a drift detector with a completeness
proof, that cuts an agent's steps in half on open-ended work, reachable today** (a
findable grammar at `/api/laserbrain/grammar`, an MCP endpoint). The honest product
is *an adaptive stop for agents — fewer steps than no limit, no budget to tune,
with a proof it detects drift where self-monitoring can't.* Its viability is a
**market** question (do agent-builders find that worth the integration), not
another study: the token-saving-vs-no-limit is real and each user can measure it on
their own workload. The unproven part is whether stopping *helps* (H1) and whether
it beats a tuned budget on tokens — so the pitch leads with what is proven
(detection, fewer steps, the theorem) and the honesty itself is the moat, because
the JSON schema is trivial to copy but the proof and the drawn boundary are not.
