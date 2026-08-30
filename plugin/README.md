# laserbrain — Claude Code plugin

Holds the goal you gave the agent, frozen where the agent cannot revise it, and checks every
later step against it.

```
/plugin marketplace add degibug-del/laserbrain
/plugin install laserbrain
```

## What you get immediately, with no install and no key

The **MCP server**, hosted. `check_state`, `reset_task`, `get_history`, and the rest, over
HTTP with no credential at all. Ground on your first goal and every later check is scored
against it.

The **`/drift` command** and the **`drift` skill** — turn the instrument on yourself when you
feel stuck, circling, or recursed too far. A looping agent feels maximally coherent, because
the same thought restated is perfectly consistent with itself. That is exactly when an outside
reference is worth more than the feeling.

## What needs one more step

The **hooks** — `lb_gate` and `lb_safety` (PreToolUse), `lb_coverage` (PostToolUse,
UserPromptSubmit) — are the half that *enforces* rather than reports. They need the Python
package:

```bash
pip install laserbrain
```

Until you run that, the hooks are inert. They are written to fail open on purpose:

```
python3 -c 'import laserbrain' 2>/dev/null && … || exit 0
```

Without that guard a missing import exits non-zero, and a non-zero `PreToolUse` exit is a
**refusal** — so installing this plugin without the Python package would have turned every
tool call in your session into a denial. The guard is the difference between a plugin that
does nothing yet and a plugin that bricks your session.

## What the gate actually enforces

`lb_gate` refuses side-effecting tool calls when you have gone too long without checking
state, or when run-wide coverage falls below its floor. `lb_safety` is separate and
narrower: it refuses destructive commands — recursive force deletes, history rewrites,
and the like — regardless of coverage. It shipped with the plugin from 2026-08-29;
before that the plugin wired the goal-drift gate and left the destruction guard out,
which is the wrong half to omit. As of 2026-08-27 it also reads the
**verdict** — but in shadow mode by default: it records what it would have refused and blocks
nothing.

```bash
LASERBRAIN_GATE_ON_DRIFT=deny    # enforce on goal-drift and ungrammatical
LASERBRAIN_GATE_ON_DRIFT=off     # do not evaluate at all
```

Shadow is the default because measured precision on `goal-drift` is **14.6%**, and a gate that
blocks on a signal wrong six times in seven is worse than no gate. Running in shadow for a
while is how that number gets replaced with one measured on your own work.

The escape hatch, if the gate ever traps you:

```bash
touch ~/.config/laserbrain/gate-off     # disable
rm    ~/.config/laserbrain/gate-off     # re-enable
```

## Running the detector locally instead

The hosted server is the default because it needs nothing. If you would rather the check made
no network call, replace `.mcp.json` with the stdio form after `pip install laserbrain`:

```json
{ "mcpServers": { "laserbrain": { "command": "laserbrain", "args": ["mcp"] } } }
```

Byte-identical verdicts either way — the hosted endpoint runs the same detector.

## Honest numbers

Precision on `goal-drift` is 14.6%. One controlled study returned a null result. Both are
published at <https://phronesis.world/laserbrain/evidence>, and they are the reason every
free and offline path exists: measure it on your own work rather than take a figure on trust.

MIT. <https://phronesis.world/laserbrain>
