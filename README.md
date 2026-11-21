# laserbrain

laserbrain is a small drift check for AI agents. We measured it over 60 days of real use on
one machine: the old every-step check caught 1 of 16 drifted helpers and cost about a tenth of
the agents' responses. What it is, what it is not, and every number:
[phronesis.world/laserbrain](https://phronesis.world/laserbrain).

Drift is an agent's goal separating from the one it was given, one reasonable step at a time,
leading to work nobody asked for.

The agent states its goal when a task starts. laserbrain freezes that statement as the
reference and scores each later check-in against it. If the two have separated far enough,
the verdict says so (reason `goal-drift`, a note with `drifting: false`). A drift verdict is a
note, not a block.

Check in when a task starts and when it changes, not after every action. Most checks score
as grounded and the answer is to continue.

The agent cannot edit the reference. It is replaced only by a deliberate `reset_task`, or,
with the hooks installed, by the agent's own restatement of the new ask at the first check
after the person sends a new message.

What it is not:

- It does not check whether the work is right. An agent doing the wrong thing well and an
  agent doing the right thing badly score the same.
- It compares words, so a paraphrase of the same goal can read as a change.
- Everything it scores is self-reported. The frozen statement is the one thing the agent
  cannot revise, and that is the whole of what it adds.

The core check needs no model and no key. It is computed locally in milliseconds, over one
`grammar.json` that every implementation reads, and it gives the same verdict for the same
input.

<details>
<summary>The same thing, precisely</summary>

At each check the agent supplies a tuple of goal, progress and distance. The first such tuple
is frozen as the reference; every later one is scored against it by

```
Φ = 0.5·goalJaccard + 0.3·|Δdistance|/10 + 0.2·[progress differs]
```

and resolved to one of nine verdicts. The agent supplies the description and has no write
access to the reference and no vote on the verdict. Computation is offline and closed-form:
no model, no network.

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

This goes to the hosted API, so the goals you send leave your machine. The package below
does not send them anywhere.

---

## Install

**Python** — the check, the hooks, the stdio MCP server and the audit chain.

```bash
pip install laserbrain
laserbrain check --goal "write a poem" --against "build a parser"
laserbrain demo             # an agent drifts off-goal and is returned
laserbrain install          # wires Claude Code: the MCP server and two hooks
laserbrain uninstall        # takes out what install added
```

`laserbrain install` sets up Claude Code only. It backs up `~/.claude/settings.json` first,
merges rather than overwrites, and checks that the hooks run before it reports success. It
wires:

- **the MCP server**: the offline stdio server (`laserbrain mcp`). It shows the agent three
  tools by default: `check_state`, `reset_task` and `get_history`. `LASERBRAIN_TOOLS=all`
  shows the rest.
- **`lb_safety`** on `PreToolUse`: a small guard that refuses a short fixed list of shell
  commands: three force-push forms, a hard reset, a recursive force delete, an unguarded
  Workers deploy, and package publishing. It reads shell tools only and lets the call
  through if it errors. It is not a sandbox. Its refusal says the command needs the explicit
  OK of the person running the session.
- **`lb_coverage`** after each tool call, through a small launcher (`fast.py`) that skips the
  package import. It records steps and, when the person sends a new message, marks the next
  check as a re-ground. It refuses nothing.

`lb_gate` is not wired unless you pass `--with-gate`. With it, the gate reminds the agent to
check in when its coverage falls and refuses edits inside another agent's claimed scope. It
refuses on the step count only under `LASERBRAIN_GATE_MODE=hard`, and on a verdict only under
`LASERBRAIN_GATE_ON_DRIFT=deny` or `LASERBRAIN_GATE_MODE=signal`. (Until 2026-10-16 the step
count refused by default; in a replay of the logs, 30 of 30 sampled refusals were false
alarms, so the repository made blocking opt-in. Releases up to 0.57.0 still block by
default.)

If the interpreter holding the package is not the first `python3` on PATH — a venv, pipx or
conda — set `LASERBRAIN_PYTHON` to it.

**Allowing one Worker deploy.** `lb_safety` reads one optional file,
`~/.config/laserbrain/safety.json` (`$LASERBRAIN_HOME/config/safety.json` when that is set):

```json
{"allow_worker_deploys": ["my-worker"]}
```

A `wrangler deploy` whose command also names `my-worker` (by `cd` or `--config`) then runs.
An allowance covers the whole command it matches: a command that contains the allowed name and
`wrangler deploy` anywhere skips every rule, including one that would also force-push or
delete. So allow only a distinctive name, for a Worker you would let an agent deploy
unattended (SECURITY.md has the details). A missing, unreadable or malformed file allows
nothing. To switch the guard off entirely, set `LASERBRAIN_SAFETY_OFF=1` where
the agent host is launched; a prefix on the command does nothing.

**Claude Code plugin** — a separate path, not changed in this release.

```
/plugin marketplace add degibug-del/laserbrain
/plugin install laserbrain
```

The plugin connects the **hosted** MCP server (`https://api.phronesis.world/mcp`), so the
goals your agent spells reach that server. It also wires `lb_gate` and `lb_safety` on
`PreToolUse` and `lb_coverage` after each call and on each message. The hooks are inert until
the Python package is installed (`pip install laserbrain`); they fail open and say so once on
stderr, naming the interpreter they tried.

**TypeScript** — the check only, held to vectors generated from Python.

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
laserbrain demo
laserbrain install          # wire it in; verifies the hooks run before reporting success

cd typescript && npm install && npm test    # the TypeScript port against Python's vectors
cd ../javascript && node test/parity.mjs    # the Node server against the same vectors, over stdio
```

**Hosted MCP**, if you would rather not install anything:

```
https://api.phronesis.world/mcp
```

No key. Eleven of the fifteen tools run keyless, `check_state` among them. The four that
touch stored memory — `remember_self`, `resume_self`, `forget_self`, `ask_alice` — take a
key as a tool argument. Whatever you send it leaves your machine.

---

## This repository

Three implementations of one grammar, the grammar itself, and the wiring.

| path | language | what it is |
|---|---|---|
| [`python/`](python) | Python | **the reference.** The check, the hooks, the stdio MCP server, a tamper-evident audit chain. Published to PyPI as `laserbrain`. |
| [`typescript/`](typescript) | TypeScript | the port, held to vectors generated **from** Python. Published to npm as `laserbrain`. |
| [`javascript/`](javascript) | JavaScript | the Node stdio MCP server, and the `grammar.json` every implementation reads. |
| [`json/`](json) | JSON | **the contract.** `grammar.json`, the measured calibration, and the parity vectors. |
| [`infra/`](infra) | — | how it wires into an agent host, and which hosts are known. |

The logic is deliberately re-implemented per language; the **contract** is not. Every
implementation reads the same `grammar.json`, and a parity check fails the build when they
disagree. That is what makes three implementations survivable — and it is also why the
`excursion` gap described below stayed hidden for months.

## The nine verdicts

`grounded` `advancing` `reground` `excursion` — carry on
`stalled` `self-report` — a warning first, then drifting
`ungrammatical` — drifting at once: the state could not be spelled
`goal-drift` — a note, not an interrupt (since 2026-11-15: on real sessions the wording signal
alone was a redirect far more often than a wander); three in a row with no re-ground escalate
in `judgment` as `wrong-problem`
`oscillating` — reads the sequence rather than the step

A verdict refuses nothing by itself. Only the gate, when wired and set to refuse, turns a
drifting verdict into a refused call.

**Declare `parent_goal` for sub-tasks.** Without it, legitimate sub-work reads as drift.
It is the most common false positive and the first thing to check.

---

## Parity is checked, not claimed

The implementations are held to vectors generated **from** the Python package:

```bash
cd typescript && npm test
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

## What was measured

Each number carries its grade: where it was measured, how, and by whom.

- In a month of labelled real use, the live check caught 1 of 16 drifted helper agents (12
  had left their task; 4 were handed a task that missed the ask). *Live · one session ·
  AI-labelled.*
- Of its 21 live alarms that month, 2 were real. *Live · one session · AI-labelled.*
- Under the old every-step design, about 10% of the agents' model responses only made a
  check. *Live · one machine · 60 days.*
- On 18 open-ended tasks it stopped runs in about half the steps (median 5 against 10). A
  better result was tested three ways and **not established**. *Offline.*

Where a number would not survive scrutiny, there is no number.

---

Docs and the full evidence: **https://phronesis.world/laserbrain**

MIT.
