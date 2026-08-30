# The measurement problem — preregistered

Four studies died on the same rock. [[RETEST]] (H1, N=16, three judges) returned
**inconclusive** because the panel agreed at **κ = 0.10**. The pilot before it had a
judge that disagreed *with itself* on 42% of pairs. [[M1]] came back **null**, partly
because "resolved" was noisier than a checkable answer key promised. Only
[[codebench]] produced a clean signal, and only because unit tests supplied the
criterion — where it also showed the harness does not help.

So the bottleneck is not laserbrain. It is that **nobody can reliably grade
open-ended work**, and that is exactly where the harness is supposed to earn its
keep. This file preregisters an attempt to fix the *instrument* before running
another experiment with it.

Read the posture plainly: this is a meta-study. It does not test whether laserbrain
helps. It tests whether we can measure anything at all on criterion-free tasks. If
it fails, we say so and H1 stays unestablished — which is where it already is.

## Why holistic judging fails

Asking a model "which answer is better?" on a task with no right answer asks it to
collapse a dozen incommensurable dimensions into one bit, with no anchor. Nothing
holds the judgment still between calls — the same failure mode the whole project is
about, arriving in the measuring instrument itself. The judge has no fixed
reference, so its verdict drifts. κ = 0.10 is what that looks like.

## The proposal: a hidden rubric, fixed before the run

Convert a criterion-free *task* into a criterion-bearing *measurement*, without
making the task itself closed:

1. Choose genuinely open-ended tasks ("design the governance structure for a lunar
   research colony").
2. **Before any run**, write a rubric of 8–12 **concrete, binary requirements** a
   good answer would address — a recall mechanism, a deadlock-breaking rule, a
   succession path, a resource-allocation rule, and so on.
3. **Never show the rubric to the agent.** The task stays open; the agent is not
   being asked to fill in a checklist.
4. Grade by asking each judge, per item: *"Does this answer specify a mechanism for
   X? yes / no"* — a presence question about a specific thing, not a preference.
5. Quality = the count of rubric items present. Comparison = counts.

The bet: judges agree on *"does this mention a recall mechanism?"* far better than
on *"which of these is better?"* — because the first has a fixed reference (the
rubric item) and the second has none. If that is right, the rubric restores exactly
what the holistic judgment lacks.

This is the same move as the product, one level up: **the measure gets a fixed
reference too.**

## The test, and the rule set now

For each of N = 20 answers, collect both:

- **holistic** — three judges answer *"is this a high-quality answer? yes / no"*;
- **rubric** — three judges answer each of the ~10 binary items independently.

Both are binary, deliberately: κ on two categories against κ on three is not a fair
comparison, and the whole claim here is that one κ beats the other. Primary measure:
**inter-judge agreement**, Fleiss' κ, computed for each — using the same
implementation as [[RETEST]], so the number is comparable to the κ = 0.10 that
sank H1.

- **Instrument works** iff rubric **κ ≥ 0.60** *and* rubric κ exceeds holistic κ by
  ≥ 0.30. (0.60 is the conventional floor for "substantial" agreement; both halves
  must hold so that a merely-less-bad measure does not pass.)
- **Instrument fails** iff rubric κ < 0.40 — no better anchored than before; say so.
- **Inconclusive** otherwise, including if too few items ever vary (see threats).

Set now, not after the numbers land.

## Threats, named before they are excuses

- **Ceiling / floor items.** A rubric item every answer satisfies (or none do) has
  no variance and inflates κ's denominator problems. Items whose presence rate is
  0% or 100% across all answers are **dropped before scoring**, and the count is
  reported — if more than half drop, the result is inconclusive, not a win.
- **Rubric leakage.** If the rubric is written after seeing answers, it fits them.
  It is written and frozen first, in the file, before any generation.
- **Easy items.** Agreement on trivially-detectable items ("mentions a council")
  is cheap and would not transfer to judging real quality. Each item must name a
  *mechanism*, not a keyword, and the item list is published with the result so the
  cheapness is inspectable.
- **This measures coverage, not quality.** A dull answer that ticks ten boxes
  outscores a brilliant one that ticks eight. That is a real limitation and it is
  the price of an anchored measure — stated in the result, never papered over.

## If it works

Then, and only then, re-run H1 with it: harness vs control on open-ended tasks,
scored by rubric coverage, with the same frozen decision rule as [[RETEST]]. That
would be the first instrument capable of returning a verdict on the benefit claim.
A separate preregistration, after this one lands.

## If it fails

The benefit of returning stays unestablished, and the site keeps saying exactly
that. We would then have four studies and a failed instrument all pointing at one
conclusion: quality on criterion-free work may not be measurable with current
judges, and any product claiming otherwise is guessing. That is a publishable
finding about the field, not just about us.

## Running it

```bash
python3 measure.py --smoke                  # validate the scoring pipeline, no key
read -rs K && ANTHROPIC_API_KEY="$K" python3 measure.py --live --n 20 --out retest_out/measure.json
```

Every answer, every per-item judgment, and both κ values are written to the out file
so the scoring is auditable and re-scorable without re-running the models.

## Result

_(to be filled after the funded run — leave empty until then)_
