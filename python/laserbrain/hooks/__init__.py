"""The enforcement half of laserbrain.

The MCP server is the instrument: it answers when an agent asks. These hooks are the
harness: they capture the first prompt as the frozen goal, count steps, and REFUSE tool
calls when coverage lapses. An agent that has drifted is exactly the one that will not
remember to check, so the check cannot be left to it.

They ship inside the package because they are Python and the package is already installed
— and because a hook that travels as a loose file goes stale the moment the package
updates. Wire them with `laserbrain install`.

Each is invoked as a module so no absolute path is ever written into a settings file:

    python3 -m laserbrain.hooks.lb_coverage      UserPromptSubmit, PostToolUse
    python3 -m laserbrain.hooks.lb_gate          PreToolUse
    python3 -m laserbrain.hooks.lb_safety        PreToolUse

lb_paths.py and lb_secrets.py are loaded by absolute path from this directory at runtime
rather than imported by name, so they must travel with their siblings. Shipping a chosen
subset is how they were broken on 2026-08-19: the hooks printed "lb_paths.py unavailable",
exited 0, and ran degraded with nothing to show for it.
"""
