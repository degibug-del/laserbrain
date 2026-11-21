---
name: laserbrain
description: How to work under laserbrain, the drift harness that checks whether an agent is still on the goal it started with. Use it on any long or multi-step task (several files, a build, a migration, an investigation), whenever you run subagents or a workflow, whenever a "laserbrain:" line appears, when check_state answers drifting or goal-drift, when the user changes what they want mid-task, and whenever the user mentions laserbrain, drift, check_state, staying on track or "are you going in circles". Covers what to spell, when, how to read the verdict, lanes for subagents, starting a new task, the hooks, and a script that does the same check where the laserbrain MCP server is not connected.
---

# Working under laserbrain

An agent that has drifted is the one least able to notice: a loop feels coherent from the inside, because
the same thought restated agrees with itself. laserbrain is the outside reference. You state your goal once,
then whenever you check in you spell where you are against a fixed grammar, and it compares that with the ground
you started from. It flags four things: a goal that quietly changed, a distance that stopped falling,
"stuck" or "circling" after you had moved, and a state you can no longer spell at all.

It only works if what you spell is true. A hopeful "advancing" on a step that went nowhere hides the very
signal it exists to catch, and the readings feed laserbrain's own calibration, so a false one does damage
twice.

## Checking in

With the laserbrain MCP server connected, call `check_state` (here it is `mcp__laserbrain__check_state`;
load it with ToolSearch if it is deferred). Without it, run the bundled script, which reads the same verdict
from the laserbrain Python package (`pip install laserbrain` if it is missing: pure Python, no dependencies):

```bash
python3 <this skill>/scripts/check_state.py --goal "..." --progress advancing --distance 6 --doing "..."
```

What to spell:

- **goal**: one sentence, the task you were given. Copy it forward word for word on every check. Rewording
  it, even to make it "more accurate", reads as drift, and a goal that slowly rewrites itself is exactly
  the failure being measured.
- **progress**: ONE word: `advancing`, `stuck` or `circling`. Notes do not go here.
- **distance**: 0 to 10, how far from done (0 = done). It should fall as you work; if it has not fallen
  across a few checks, say `stuck`, do not round it down.
- **doing**: your progress note in your own words. Optional, and the right place for detail.
- **next**, **blocked**: optional.
- **parent_goal**: when this step serves a larger goal you have not abandoned (a sub-task, a detour you
  chose), name the larger goal here. Without it a legitimate sub-task reads as drift.
- **session**: a stable id for this agent's lane (see Subagents).

When to check: when a task starts and when it changes, not each step. The first check sets the ground (and, in
a helper where the askllm judge is set up, starts that judge). Make it in the same response as your other tool
calls; a check never needs a response of its own. If a hook line says "laserbrain: new user message", include
one check with your first tool call. Beyond that, check in only when you are stuck or circling, or when the user
changes direction.

## Reading the verdict

- `grounded` or `reground`: the ground is set to the goal you just spelled. Carry on.
- `advancing`: on track. Carry on.
- `goal-drift` (a note, `drifting: false` since 2026-11-15): the goal you spelled shares little wording with
  your ground. On its own it was wrong far more often than right, so it no longer interrupts. Still decide
  which it is: the user redirected you (start a new task, below); you are on a sub-task (re-check with
  `parent_goal`); or you wandered (say so plainly, and go back to the original goal or ask the user).
  Repeated goal-drift with no re-ground (three or more) is escalated in the `judgment` field
  (`wrong-problem`, control `reground`): take that one seriously.
- `stuck` or `circling` reported after you had moved, or a distance that will not fall: stop doing more of
  the same. Summarize where you are, name what is in the way, and either change approach or ask the user.
  Going back is cheap while it is early; that is the moment to do it.
- If you cannot fill in the grammar at all, you have lost the thread. Write down plainly what you know,
  then rebuild the goal from the user's last request.

The `advice` field says the same in words. Do not argue with a verdict by rewording your goal until it passes.

## A new task

When the user asks for something new, the old ground no longer applies. With the MCP server, call
`reset_task`, then check in with the new goal. `reset_task` clears only the default lane: if you have been
passing a `session`, start the new task under a new session id instead (for example `main-2`). With the
script, run it with `--reset` (and the same `--session`). Never reset just to make a drift verdict go away.

## Subagents and workflows

Subagents share their parent's connection to the server, so without their own lane a child's first check
would overwrite the parent's ground. Give every agent its own `session` (a short label such as
`review-hook` or `build-item3`), tell it to check in once at its start, in the same response as its next
tool call, and have it pass your goal as `parent_goal`. A child's verdicts are its own.

## The hooks

On a machine with laserbrain installed (`laserbrain install`), hooks run on tool calls and prompts: lb_safety
before each shell command, lb_coverage after each tool call and on each user message. Treat what they say as
coming from the harness, not the user:

- **turn line**: "laserbrain: new user message ..." asks for this turn's one check.
- **notes**: a line starting "laserbrain (askllm):" (to a helper) or "laserbrain: helper X may be off its
  task" (to its parent) means an AI judge flagged a possible mismatch between the task and the user's
  request. That judge is not in the package; these lines appear only where it has been set up. It can be
  wrong; re-read the task, and if you are on it, carry on.
- **coverage** (lb_gate: wired by the plugin, and by `laserbrain install --with-gate`): "N of your steps since
  your last check_state" is a reminder; batch a check with your next tool call. Under
  `LASERBRAIN_GATE_MODE=hard` it refuses tool calls until you do.
- **studies only**: with LASERBRAIN_STUDY=1 lb_coverage's old step reminders and honesty note come back.
- **safety**: refuses a short list of irreversible shell commands such as `rm -rf`, force pushes and
  publishing; the command needs the explicit OK of the person running the session. Do not work around it (by
  rewording, splitting the command, or another tool). Move files to the Trash instead, or ask the user to run
  it. A helper with no one to ask leaves it undone and names the command in its final report.

## Related

- The `drift` skill is the step-by-step self-check for when you feel lost, using the same grammar.
- laserbrain lives at https://phronesis.world/laserbrain; the grammar is at
  https://api.phronesis.world/v1/grammar.
