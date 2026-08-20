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

### From this clone

If you would rather read the source before trusting a registry — the sensible order for
something that installs a hook able to refuse your agent's tool calls:

```bash
git clone https://github.com/degibug-del/laserbrain.git
cd laserbrain

pip install ./python        # same code as PyPI, plus the hooks
laserbrain demo             # six lines: an agent drifts off-goal, and is returned
laserbrain install          # wire it in; verifies the hooks run before reporting success

cd typescript && npm install && npm test    # 276 comparisons against Python
cd ../javascript && node test/parity.mjs    # 138 comparisons, driven over stdio
```

`laserbrain install` backs up `~/.claude/settings.json` first and prints the undo line.
To reverse it, restore `settings.json.before-laserbrain`.

**Hosted MCP**, if you would rather not install anything — needs a free key:

```
https://laserbrain-mcp.degibug.workers.dev/mcp
```

---

## This repository

Three implementations of one grammar, the grammar itself, and the wiring we run ourselves.

| path | language | what it is |
|---|---|---|
| [`python/`](python) | Python | **the reference.** Harness, enforcement hooks, stdio MCP server, tamper-evident audit chain. Published to PyPI as `laserbrain`. |
| [`typescript/`](typescript) | TypeScript | the port, held to vectors generated **from** Python. Published to npm as `laserbrain`. |
| [`javascript/`](javascript) | JavaScript | the local stdio MCP server we run ourselves, and the `grammar.json` every implementation reads. |
| [`json/`](json) | JSON | **the contract.** `grammar.json`, the measured calibration, and the parity vectors. |
| [`infra/`](infra) | — | how it wires into an agent host, and which hosts are known. |

```bash
cd typescript && npm test     # 16 sequences, 276 field comparisons against Python
```

The logic is deliberately re-implemented per language; the **contract** is not. Every
implementation reads the same `grammar.json`, and a parity check fails the build when they
disagree. That is what makes three implementations survivable — and it is also why the
`excursion` gap described below stayed hidden for months.

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
