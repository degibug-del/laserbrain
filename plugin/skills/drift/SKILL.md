---
name: drift
description: Check yourself for drift against the laserbrain grammar — spell your working state into the fixed reference, catch a spiral, return to ground. Use when you feel confused, stuck, circling, or that you have recursed too deeply for the task's own good.
---

# laserbrain drift-fixer — turned on yourself

You are the first user. When you feel confused, stuck, circling, or that you have
recursed too far, do **not** trust how this step feels — a looping agent feels
maximally coherent, because the same thought restated is perfectly consistent with
itself. Measure yourself instead against laserbrain: a fixed, findable, unchangeable
reference outside you. That is the whole point — you cannot measure your own drift
from the inside; you need an outside anchor.

## Step 1 — get the fixed reference

The grammar never changes. Recall it, or fetch it (free, findable):

```bash
curl -s https://api.phronesis.world/v1/grammar
```

It is a JSON schema: `goal`, `doing`, `progress` (advancing | stuck | circling),
`distance` (0–10, 0 = done), `next`, `blocked`. Over MCP it is the `drift_grammar`
tool on `api.phronesis.world/mcp`.

## Step 2 — spell your state

Write your CURRENT working state as one JSON object against the schema. Hold `goal`
**identical** to the goal you FIRST stated for this task — copy it forward, do not
re-summarise it, because a quietly rewritten goal is exactly the drift you are
checking for.

## Step 3 — check the four signals

You have drifted — and should stop — if any of these is true:

- **ungrammatical** — you cannot spell a clear goal and where you are. If the state
  won't compress into the schema, you have lost the thread.
- **self-report** — `progress` is `stuck` or `circling`, *and* you have actually
  moved from where you started (a first-step "this is hard" is a mood, not a loop).
- **goal drift** — the `goal` you spell no longer matches the goal you first stated.
  You are solving something else now.
- **stalled** — your `distance` has stopped falling across the last few steps.
  Motion without progress is the shape of a loop.

## Step 4 — return to ground

If any signal fired: **stop.** Summarise your state plainly, then either return to
the first goal or surface to the user with what you have. The stop signal is
**return cost, not confusion** — being far out is fine if getting back is cheap;
the trouble is when the path home is getting expensive. Return while it is cheap.

If nothing fired, you are not drifting — continue, and don't manufacture a spiral
out of caution. The lens is always-on, not an alarm; the wrong prescription makes
vision worse.

*This is laserbrain's own product (phronesis.world/laserbrain), run on its first
user. The proof that a fixed outside reference is necessary — that watching only
yourself provably cannot catch slow drift — is in lasermind/PROOF.md.*
