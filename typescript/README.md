# laserbrain

**A goal-alignment harness for AI agents.** Your agent states its goal on the first step;
that statement is frozen where the agent cannot revise it, and every later step is checked
against it.

No model, no network, no key. A fixed algebraic structure computed locally in single-digit
milliseconds — the same grammar the Python package and the hosted API read.

```bash
npm install laserbrain
```

## Which laserbrain is this

This package and `pip install laserbrain` share a name and a grammar, and they are **not the
same size**. Said plainly here because the version numbers suggest the opposite — this one is
2.x and the Python one is 0.x, and the Python one is roughly seven times larger.

|  | this package | `pip install laserbrain` |
|---|---|---|
| the detector — `checkStep`, the nine verdicts, Φ, `laserscore` | yes | yes |
| runs offline, no key, no network | yes | yes |
| `Operator` — refuses an irreversible act taken off-ground | — | yes |
| `PreToolUse` hook that gates a real agent loop | — | yes |
| LangGraph / CrewAI adapters, middleware | — | yes |
| context store, dialogue, teams, the hosted client | — | yes |

If you want the thing that **stops** an agent, you want the Python package or the hosted API.
If you want the thing that **scores** a step, in TypeScript, with no dependencies and no
network, this is it — and it is byte-identical to the detector the hosted endpoint runs.

The two version lines are independent on purpose: these are different surfaces at different
maturity, and forcing them to agree would only make the number meaningless.

```ts
import { Harness } from 'laserbrain'

const h = new Harness()
h.check('add a CSV importer to the admin panel', 'advancing', 8)   // grounded

const v = h.check('refactor the ORM base class', 'advancing', 5)
v.drifting   // true
v.reason     // 'goal-drift'
v.ground     // 'add a CSV importer to the admin panel'  ← the frozen goal, handed back
```

## Sub-tasks

A legitimate sub-task reads as drift unless you declare its parent. This is the most
common false positive:

```ts
h.check('validate CSV columns', 'advancing', 6)                    // goal-drift  (wrong)
h.check('validate CSV columns', 'advancing', 6, { parentGoal: G }) // excursion   (right)
```

## The nine verdicts

`grounded` `advancing` `reground` `excursion` — carry on ·
`stalled` `self-report` — warn, then interrupt ·
`goal-drift` `ungrammatical` — stop ·
`oscillating` — reads the sequence rather than the step

## Parity

This is not a re-implementation that behaves similarly. It is checked step-for-step against
vectors generated **from** the Python package, which is the reference:

```bash
npm test    # 16 sequences, 276 field comparisons
```

If a field disagrees with Python, the test fails. Regenerate the vendored source with
`node vendor.mjs` after any grammar change.

## Where it does nothing

It measures **execution**, where the goal is fixed before the run starts. On exploration —
figuring out what to build while building it — it will report drift continuously,
correctly, and to no purpose.

## Also available

- **Python**: `pip install laserbrain` — adds the enforcement hooks and a stdio MCP server
  (`laserbrain install`), plus a tamper-evident audit chain.
- **Hosted MCP**: `https://api.phronesis.world/mcp`
- Docs: https://phronesis.world/laserbrain

MIT.
