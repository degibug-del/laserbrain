"""The enforcement half of laserbrain.

The MCP server is the instrument: it answers when an agent asks. These hooks are the
harness: they record steps, re-ground the reference when the person sends a new message
(the agent's own restatement of the new ask becomes the frozen goal), and guard a short
list of irreversible shell commands. lb_gate, wired only on request, reminds when coverage
lapses and, under LASERBRAIN_GATE_MODE=hard, REFUSES tool calls. Its default since
2026-10-16 is nudge: the step count logs and reminds and never refuses (claims still
refuse; see lb_gate.gate_mode).

They ship inside the package because they are Python and the package is already installed
— and because a hook that travels as a loose file goes stale the moment the package
updates. Wire them with `laserbrain install`; `laserbrain uninstall` takes them out.

WHAT `laserbrain install` WRITES (0.58.0; install.py has the exact commands). Each hook
runs a FILE from this folder with the interpreter that ran install, under -I -S, so the
package __init__, a laserbrain copy in the agent's working directory or a stray module on
PYTHONPATH cannot stand in for it:

    SessionStart                                   a self-test: lb_safety must refuse a
                                                   guarded command, or it warns once
    PreToolUse                                     lb_safety.py, alone
    PostToolUse, PostToolUseFailure,
    UserPromptSubmit                               fast.py lb_coverage (lb_coverage without
                                                   the package __init__; fails open)
    PreToolUse (only with --with-gate)             python3 -P -m laserbrain.hooks.lb_gate

The commands check that the file exists and exit 1, never 2, when it does not (exit 2 on
PreToolUse refuses the call), and fall back to python3 on PATH when the interpreter has
moved. On Windows install writes the 0.57.0 module form (`python -P -m
laserbrain.hooks.<hook>`) instead, which exits 1 when the package is gone. The plugin keeps
the -m form too (test_plugin_manifest pins it); -P (Python 3.11+) keeps the agent's working
folder off sys.path there.

lb_askllm_watch.py and lb_turnwatch.py are not hooks of their own: lb_coverage loads them by
path on a check_state (a helper agent's first one; the main session's first one after a user
message). Their code ships, but it cannot score in an installed wheel: the frozen scorers
(research/eval/) and the frozen blocks that pin them (eval/) are only in a repository
checkout, so each returns 'no-judge' at once and starts no process. In a checkout they make
one `claude -p` (Haiku) call each in a detached process. askllm's default (note) mode turns
a flag into one additionalContext line for the helper and one for its parent; turnwatch is
watch-only.

lb_paths.py and lb_secrets.py are loaded by absolute path from this directory at runtime
rather than imported by name, so they must travel with their siblings. Shipping a chosen
subset is how they were broken on 2026-08-19: the hooks printed "lb_paths.py unavailable",
exited 0, and ran degraded with nothing to show for it.
"""
