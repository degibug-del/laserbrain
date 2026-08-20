# infra — the wiring we actually run

The published packages are the product. This is the setup on our own machines, kept here
so it can be read and copied rather than described.

## The two halves

**`lasermind/mcp-server.mjs`** — a stdio MCP server. This is what answers our own
`check_state` calls. It reads `grammar.json` from this directory, so the server and the
Python package score against the same file.

**`lasergear/`** — the hooks. These are the enforcement, and they are the half that
matters. The MCP server is a detector an agent calls when it remembers to; an agent that
has drifted is exactly the one that will not remember.

| hook | event | what it does |
|---|---|---|
| `lb_coverage.py` | `UserPromptSubmit` | captures the first prompt as the frozen goal |
| `lb_coverage.py` | `PostToolUse` | counts steps, logs failed commands as catches |
| `lb_gate.py` | `PreToolUse` | **refuses tool calls** when coverage lapses |
| `lb_safety.py` | `PreToolUse` | blocks destructive and publish-once actions |

`lb_gate.py` is the mechanism. It stopped this harness's own author six times in one
session and took an unsaved draft with one of them.

## Wiring it

The supported way is the package:

```bash
pip install laserbrain
laserbrain install
```

That installs the same hooks from inside the package, referenced as modules
(`python -m laserbrain.hooks.lb_gate`), so an upgrade moves them and no settings file goes
stale. **Prefer it.** The copies here are for reading, and for hosts the installer does
not know about.

By hand, in `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "laserbrain": { "type": "stdio", "command": "laserbrain", "args": ["mcp"] }
  },
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python3 -m laserbrain.hooks.lb_coverage" }] }],
    "PostToolUse":      [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python3 -m laserbrain.hooks.lb_coverage" }] }],
    "PreToolUse":       [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python3 -m laserbrain.hooks.lb_gate" }] },
                         { "matcher": "*", "hooks": [{ "type": "command", "command": "python3 -m laserbrain.hooks.lb_safety" }] }]
  }
}
```

## Hosts

`lasergear/hosts.json` carries per-host facts — how *this* host names the check tool, so a
coverage denial can tell the agent what to call. It knows two: Claude Code and Grok.
The harness is model-agnostic by construction; the enforcement is not host-agnostic.

## What is deliberately not here

Session records, the corpus, traces and calibration output. `attention.json` is included
because it is the published calibration the package ships; the runs behind it are not.

## The blind probe

`lasergear/BLIND-PROBE.md` describes it: half of sessions have the verdict withheld, at
random, pre-registered. It is why our own sessions often show `"blind": true` — the state
is recorded and the reading is not returned. Do not analyse it early.
