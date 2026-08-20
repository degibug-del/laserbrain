# laserbrain

**A goal-alignment harness for AI agents.**

Your agent states its goal on the first step. That statement is frozen where the agent
cannot revise it, and every later step is checked against it — and the check is *forced*
rather than left to the agent to remember, because an agent that has drifted is exactly
the one that will not remember to check.

No model. No network. No key. A fixed algebraic structure computed locally in single-digit
milliseconds, over one `grammar.json` that every implementation reads.

---

## Install

**Python** — the complete product: harness, enforcement hooks, MCP server, audit chain.

```bash
pip install laserbrain
laserbrain install          # wires the MCP server + hooks into your agent
laserbrain demo             # watch an agent drift off-goal and get returned
```

**TypeScript**

```bash
npm install laserbrain
```

**Hosted MCP**, if you would rather not install anything — needs a free key:

```
https://laserbrain-mcp.degibug.workers.dev/mcp
```

---

## The repositories

| repo | what it is |
|---|---|
| [laserbrain-sdk](https://github.com/degibug-del/laserbrain-sdk) | Python. The reference implementation. |
| [laserbrain-js](https://github.com/degibug-del/laserbrain-js) | TypeScript, parity-checked against the Python vectors. |
| [lasergear](https://github.com/degibug-del/lasergear) | The hooks — the enforcement half. |
| [laserbrain-check](https://github.com/degibug-del/laserbrain-check) | CI gate: catches prose that has quietly stopped being true. |

The Python package ships the hooks, so `pip install laserbrain` is enough on its own.

---

## The nine verdicts

`grounded` `advancing` `reground` `excursion` — carry on
`stalled` `self-report` — warn, then interrupt
`goal-drift` `ungrammatical` — stop
`oscillating` — reads the sequence rather than the step

**Declare `parent_goal` for sub-tasks.** Without it, legitimate sub-work reads as drift.
It is the most common false positive and the first thing to check.

---

## Parity is checked, not claimed

The implementations are held to vectors generated **from** the Python package:

```bash
npm test    # 16 sequences, 276 field comparisons
```

A parity check only covers the behaviour its cases ask for. On 2026-08-20 the TypeScript
path was found to be missing `excursion` entirely — it had shipped eight of the nine
verdicts for months, and the gate had stayed green the whole time because no vector ever
declared a parent goal. The generator now covers it.

---

## Where it does nothing

It measures **execution**, where the goal is fixed before the run starts. On exploration —
figuring out what to build while you build it — it will report drift continuously,
correctly, and to no purpose.

Inside a single agent that can still see its goal, a stated constraint held **36 of 36**
times. That bounds the loss rate near 8% rather than at zero, and it means constraint
retention is a *hand-off* problem. Goal drift is not: it needs only length.

## What the evidence supports

Against errors something else independently caught, precision has a measured lower bound
of **4 of 50 — 8%**, across 24 sessions in which it fired. Recall carries no figure:
everyday runs gate at 20–25% coverage and the scorer needs 50% before a zero-fire result
means anything. Running the harness costs about **17%** of an agent's tool calls.

Where a number would not survive scrutiny, there is no number.

---

Docs and the full evidence: **https://phronesis.world/laserbrain**

MIT.
