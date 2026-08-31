# laserbrain

**Laserbrain detects when an AI agent stops doing what it was asked to do.**

The agent states its task. Laserbrain freezes that statement and asserts it during each step
of the agent's task. If the planned work drifts from the goal, laserbrain can refuse the
next action.

The check is *forced* rather than left to the agent to remember, because an agent that has
drifted is exactly the one that will not remember to check.

No model. No network. No key. A fixed algebraic structure computed locally in single-digit
milliseconds, over one `grammar.json` that every implementation reads.

<details>
<summary>The same thing, precisely</summary>

Laserbrain is a deterministic drift detector for agent loops. At each step the agent supplies
a tuple of goal, progress and distance. The first such tuple is frozen as the reference; every
subsequent one is scored against it by

```
Φ = 0.5·goalJaccard + 0.3·|Δdistance|/10 + 0.2·[progress differs]
```

and resolved to one of nine verdicts, two of which are enforceable. The agent supplies the
description and has no write access to the reference and no vote on the verdict. Computation
is offline and closed-form: no model, no network, single-digit milliseconds.

</details>

---

## Try it with nothing installed

`POST /v1/check` takes a sequence of goals and returns a verdict per step. No key, no
account, no signup. Send goals only and the two self-reported terms stay fixed, which
leaves the anchored goal term as the only thing moving:

```bash
curl -s -X POST https://api.phronesis.world/v1/check \
  -H 'content-type: application/json' \
  -d '{"steps":[{"goal":"add rate limiting to the login endpoint"},
                {"goal":"throttle repeated sign-in attempts"},
                {"goal":"add a token bucket to the login endpoint"}]}'
```

Read `goal_score` per step: 1.0 on-goal, 0.0 swapped, fractional between. That request is
also the experiment worth running first, because it tells you whether the instrument suits
your team's vocabulary. It scores stem overlap, so a paraphrase of your own goal reads as a
swap — the middle step above returns 0.0. If `goal_score` collapses on wording you consider
identical, you have learned that before installing anything.

---

## Install

**Python** — the complete product: harness, enforcement hooks, MCP server, audit chain.

```bash
pip install laserbrain
laserbrain check --goal "write a poem" --against "build a parser"
laserbrain demo             # watch an agent drift off-goal and get returned
laserbrain install          # wires the MCP server + hooks into your agent
```

**Claude Code plugin** — the enforced-cadence path, and the one that actually works.
Discipline alone measured 6% coverage. The gate holds a 20% floor, because an agent that
has drifted is the one that will not remember to check.

```
/plugin marketplace add degibug-del/laserbrain
/plugin install laserbrain
```

It ships the MCP server and three hooks: `lb_gate` refuses side-effecting tool calls when
coverage falls, `lb_safety` refuses destructive commands, `lb_coverage` records. **The hooks
are inert until the Python package is installed.** They are guarded, so a missing package is
silent rather than fatal, and they say so once on stderr naming the interpreter they tried.
Run both:

```bash
pip install laserbrain          # this is what arms the hooks
```

If the interpreter holding the package is not the first `python3` on PATH — a venv, pipx or
conda — set `LASERBRAIN_PYTHON` to it.

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

**Hosted MCP**, if you would rather not install anything:

```
https://api.phronesis.world/mcp
```

No key. Eleven of the fifteen tools run keyless, `check_state` among them. The four that
touch stored memory — `remember_self`, `resume_self`, `forget_self`, `ask_alice` — take a
key as a tool argument. This line used to say the hosted MCP needs a free key, which was
not true.

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
