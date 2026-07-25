# RECYCLE — does resuming through a compressed ground cost fewer tokens?

*Preregistered 2026-07-24, before any run. Written in the shape of [[RETEST]] and
[[M1]], and for a specific reason: this is the first claim in the programme with a
**criterion**. Four studies died asking judges to score work that had no right answer
([[MEASURE]]). Tokens are counted, not judged. This one can be settled.*

## The claim, and why the theorem predicts it

[[PROOF]] §3 is about **bounded windows**: a monitor whose decision depends only on
the last *w* states cannot detect drift, because after *w* steps the ground has
scrolled out of memory. A context window is a bounded window. The same argument
applies to an agent resuming a task across sessions — send it the tail of its history
and the goal it started from is gone.

The prescription follows: **re-inject the ground, not the history.** laserbrain's
continuity layer already does this — `remember_self` persists a compressed
`ground` / `now` / `mind`; `resume_self` reads it back and reports identity
displacement. A ground is a few hundred tokens. A history is thousands.

So the claim is not "the harness makes agents smarter." It is narrower and mechanical:

> **Resuming a task through a compressed persisted ground reaches completion in fewer
> NET tokens than resuming by re-sending accumulated context.**

Net, not gross: the harness's own calls are charged against it. That distinction is
why the cost accounting was built ([[STUDY]]'s "H1 cost thing") — step count flattered
the harness by not billing the monitor for its own overhead, and this study must not
repeat that.

## Arms

Same tasks, same model, same task order, differing in one thing only.

| arm | how the agent resumes each session |
|---|---|
| **A — history** | the accumulated transcript (or its tail, if it exceeds the window) |
| **B — recycled ground** | `resume_self`: the persisted ground, now and mind — history discarded |

Both arms run **multi-session** tasks, because that is where the claim lives. A task
completed in one sitting never resumes and cannot test this.

## The measure

- **Primary: net tokens to completion**, summed across all sessions of a task, input +
  output, **including every token the harness itself spends** (`resume_self`,
  `remember_self`, and any `check_state`). Read from `/v1/cost`, which already reports
  `tokens`, `work_tokens`, `overhead_tokens`, `overhead_fraction` per account and
  per run — the instrument exists and is not being built for this study.
- **Secondary, and a gate: did it finish.** Tokens saved by an agent that never
  completes the task are not savings. Any task not completed in an arm is counted as a
  **failure for that arm**, not dropped.

## The decision rule — set now

- **Supported** iff arm B's median net tokens is **≥ 20% lower** than arm A's, *and*
  B's completion rate is **not lower** than A's.
- **Null** iff the medians differ by less than 20% either way.
- **Negative** iff B costs more, or completes less often. Say so plainly; the
  continuity layer would then be a feature that costs tokens rather than saving them,
  and the site must stop implying otherwise.

The 20% floor is chosen before data because a saving smaller than that is not worth a
claim on a public page, whatever its p-value.

## Threats, named before they can be excuses

- **The ground is a summary, and summaries lose things.** If B completes less often,
  that is the real cost of compression and it is exactly what the completion gate is
  for. Do not report a token saving without the completion rate beside it.
- **Task length decides the outcome.** A short task favours A (no history to resend);
  a long one favours B trivially. Fix the session count **before** running — three
  sessions per task — and do not tune it afterwards.
- **Window overflow is not a fair comparison.** If A's history exceeds the context
  window it must be truncated, and truncation is itself the failure the theorem
  describes. Record how often A truncates; a win for B that only appears after
  truncation is a *different* result — say which.
- **We wrote both the harness and the study.** The arms differ only in the resume
  mechanism; nothing else may be tuned per-arm, and the prompt is identical.

## What a result means, and what it does not

**Supported:** laserbrain may say *"token recycling improves efficiency"* on the site
as a **measured** claim, with the number and the completion rate attached. It would be
the programme's first positive empirical result about benefit rather than detection.

**It would still not mean** the harness makes an agent better, or that returning
improves answers. Those are [[RETEST]]'s question and remain unestablished. Efficiency
and quality are different claims and must not be blurred — the temptation to blur them
is precisely how the corpus's problems began.

**Null or negative:** the claim comes off the site and stays off. Detection remains the
only proven thing, and the honest line is unchanged.

## Running it

```bash
python3 recycle.py --smoke                      # pipeline check, no key
read -rs K && ANTHROPIC_API_KEY="$K" python3 recycle.py --live --tasks 8 --sessions 3 \
    --out retest_out/recycle.json
```

Every session's token counts, completion flag and truncation flag are written to the
out file, so the result is re-scorable without re-running any model.

## Result

_(to be filled after the funded run — leave empty until then)_

---

## Result — 2026-07-24, N=8 tasks × 3 sessions × 2 arms, claude-haiku-4-5

**NULL by the preregistered rule.** Arm B did not come in 20% cheaper; it came in
**8.4% more expensive**.

| | median net tokens | completed | truncated |
|---|---|---|---|
| A — history | 7,491 | 0/8 | 0/8 |
| B — recycled | 8,118 | 0/8 | — |

The floor was 20% and the observed difference is −8.4%, so this is NULL, not NEGATIVE:
the rule as written treats anything inside ±20% as no result, and I am holding to that.

### What this run does not show

It does not test the hypothesis, and that is my error in the design, not a reading of
the data after the fact.

**A never truncated — 0 of 8.** §Threats says a win for B that appears only after
truncation is a different result. The inverse case was not written down and is the one
that happened: A's transcript never came near the 120,000-character window, so the cost
recycling exists to avoid never accrued. Three sessions at 1,200 max output tokens is
roughly 3.6k tokens of history — about 3% of the window. Arm A was carrying almost
nothing, so there was almost nothing to save.

What the 8.4% therefore measures is just B's compression call, billed to B as the
protocol requires, with no offsetting saving available. It is the overhead term alone.

**Both arms completed 0 of 8.** The completion gate ("B completes no less often") was
satisfied trivially — neither arm finished anything, so the gate discriminated nothing.
Two arms that both fail are not a comparison of how well they work.

### What a real test needs

A re-run is a NEW preregistration, not a reinterpretation of this one. This result stands
as recorded. The next one must create the condition this one lacked:

- sessions long enough that A's history approaches the window — many more sessions, or a
  far larger per-call budget, chosen so A truncates in a *majority* of runs;
- a completion rate above zero in at least one arm before token medians mean anything,
  which likely means shorter tasks or more sessions;
- both of the above fixed and written down before the run, since tuning either one after
  seeing a result is how a floor stops being a floor.

Filed as a null. The honest one-line version: *recycling was tested under conditions
where it had nothing to recycle.*
