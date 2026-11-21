# infra — how it wires into an agent host

The packages are the product. This directory holds the facts about *wiring*, and nothing
that is a copy of code living elsewhere in this repository.

## The two halves

**The instrument** is the MCP server: it answers when an agent asks. `laserbrain mcp` from
the Python package, or [`../javascript/mcp-server.mjs`](../javascript/mcp-server.mjs), which
is the local stdio server we run ourselves.

**The harness** is the hooks, in
[`../python/laserbrain/hooks/`](../python/laserbrain/hooks). They are the half that matters.
An MCP server is a detector an agent calls when it remembers to, and an agent that has
drifted is exactly the one that will not remember.

| hook | event | what it does |
|---|---|---|
| `lb_coverage.py` | `UserPromptSubmit` | captures the first prompt as the frozen goal |
| `lb_coverage.py` | `PostToolUse` | counts steps, logs red test verdicts as catches |
| `lb_coverage.py` | `PostToolUseFailure` | counts a failed call as a step and a catch (Claude Code skips PostToolUse when a call fails) |
| `lb_gate.py` | `PreToolUse` | by default (`nudge`) logs each lapse and reminds the agent without refusing; **refuses tool calls** when coverage lapses only under `LASERBRAIN_GATE_MODE=hard`; claims always refuse |
| `lb_safety.py` | `PreToolUse` | blocks destructive and publish-once actions |

Two AI-graded checks ride on `lb_coverage.py` and need no settings entry of their own. Both
grade with frozen scorers in `research/eval/` (a repository checkout; an installed wheel has
none, so they do nothing there), each with one `claude -p` Haiku call in a detached process,
80 calls a day each, at most 2 at once between them:

| check | when | what it does | off |
|---|---|---|---|
| `lb_askllm_watch.py` | a helper agent's first `check_state` | grades whether its goal covers the user's asks; in `note` mode (default) a flag becomes one additionalContext line for that agent and one for its parent session, never a block. `LASERBRAIN_ASKLLM_MODE=watch` only logs | `LASERBRAIN_ASKLLM_MODE=off` |
| `lb_turnwatch.py` | the main session's first `check_state` after each user message (its PostToolUse, or its PostToolUseFailure when that check failed) | **watch-only**: grades whether the main session set out to do what the user asked (a bare "ok" against the proposal it answered); logs to `turnwatch.jsonl`; bookkeeping in `turnwatch.seen.json` and `turnwatch.calls.json` under `turnwatch.lock` | `LASERBRAIN_TURNWATCH=off` |

Reports: `research/eval/askllm_watch_report.py`, `research/eval/turnwatch_report.py`.
askllm notes wait in `askllm-notes/<session>/`; an agent note expires after 6 h, a parent note
after 24 h, and switching away from `note` mode drops what is pending, so the folder never
outlives its notes.

`lb_gate.py` is the mechanism. Under the old default (now `LASERBRAIN_GATE_MODE=hard`) it
stopped this harness's own author six times in one session and took an unsaved draft with
one of them. Since 2026-10-16 the default is `nudge`: the day-one experiment counted 4,775
step-count blocks, 0 kept by signal mode and 30 of 30 sampled false alarms
(research/DAY-ONE-RESULTS.md).

## Wiring it

```bash
pip install laserbrain
laserbrain install
```

That installs the MCP server and all five hook entries, referenced as **modules** —
`python3 -P -m laserbrain.hooks.lb_gate` — so an upgrade moves them and no settings file goes
stale. It backs up your existing settings, merges rather than overwrites, and verifies the
hooks execute before reporting success. `-P` (Python 3.11+) keeps the folder the agent is
working in off the import path, so a laserbrain checkout there can't stand in for the
installed hooks; leave it out on older Pythons.

By hand, in `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "laserbrain": { "type": "stdio", "command": "laserbrain", "args": ["mcp"] }
  },
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python3 -P -m laserbrain.hooks.lb_coverage" }] }],
    "PostToolUse":      [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python3 -P -m laserbrain.hooks.lb_coverage" }] }],
    "PostToolUseFailure": [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python3 -P -m laserbrain.hooks.lb_coverage" }] }],
    "PreToolUse":       [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python3 -P -m laserbrain.hooks.lb_gate" }] },
                         { "matcher": "*", "hooks": [{ "type": "command", "command": "python3 -P -m laserbrain.hooks.lb_safety" }] }]
  }
}
```

To undo: restore `~/.claude/settings.json.before-laserbrain`.

## Hosts

[`hosts.json`](hosts.json) carries per-host facts — how *this* host names the check tool,
so a coverage denial can tell the agent what to call. It knows two: Claude Code and Grok.

**The harness is model-agnostic by construction; the enforcement is not host-agnostic.**
It scores whatever state an agent spells, so it works with any model — verified across
seven open models from four vendors. Wiring it into a host that is not in `hosts.json`
means writing that integration yourself.

## The contract

`grammar.json`, the calibration and the parity vectors are in [`../json/`](../json), not
here. They are shared by every implementation rather than belonging to the wiring.

## The blind probe

[`BLIND-PROBE.md`](BLIND-PROBE.md) describes it: half of sessions have the verdict
withheld, at random, pre-registered. It is why our own sessions often report
`"blind": true` — the state is recorded and the reading is not returned. Do not analyse
it early.

## What is deliberately not here

Session records, the corpus, traces, and calibration output. `attention.json` is in
`../json/` because it is the published calibration the package ships; the runs behind it
are not in this repository.
