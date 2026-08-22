# Security

## What this software does to your machine

`laserbrain install` writes to `~/.claude/settings.json` and installs a **`PreToolUse`
hook**. That hook sees every tool call your agent makes before it runs, and can refuse it.
That is the highest-trust position in an agent stack, and it is the reason this repository
exists rather than only a package on a registry: you should be able to read it first.

The relevant code is small and in one place:

- [`python/laserbrain/hooks/`](python/laserbrain/hooks) — the four hooks
- [`python/laserbrain/install.py`](python/laserbrain/install.py) — everything that touches your settings

`laserbrain install` backs up your existing settings to `settings.json.before-laserbrain`,
merges rather than overwrites, and verifies the hooks execute before reporting success.
To reverse it completely: restore that backup and `pip uninstall laserbrain`.

## What it sends

Nothing. The Python package, its hooks and the stdio MCP server make **no network calls**
— verified by blocking `socket.connect` and `socket.create_connection`, then importing
every shipped module — the 25 at the top level and the hooks in `laserbrain/hooks/`, which
an earlier version of this sentence named while the check's non-recursive glob skipped them
— and exercising the full path: check, reground, async check, judgment, report, ledger and
export. Zero connection attempts, and importing the package pulls in no
TLS or HTTP client at all. Re-run it yourself with `python3 test_no_network.py`.

That replaces the method this file used to cite — scanning every shipped file for URLs —
which would not have caught a host assembled at runtime, read from the environment, or
reached through a dependency. The claim was true; the way it was checked could not
establish it. State is written under your own home directory
(`~/.claude/laserbrain`, `~/.config/laserbrain`).

The hosted MCP endpoint and the `/v1` REST API are opt-in and separate. If you use those,
your spelled goals and verdicts reach that server; if you use the package, they do not
leave your machine.

## Reporting a vulnerability

Email **degibug@gmail.com** with `laserbrain security` in the subject. Please include what
you found, how to reproduce it, and what you think the impact is. You will get a reply.

Please do not open a public issue for anything that lets a third party read another user's
readings, bypass the safety hook, or execute code through the install path.

## Known limits, stated plainly

- The enforcement hooks are **host-specific**. They know Claude Code and Grok; wiring
  another host means writing that integration.
- `lb_safety.py` blocks destructive and publish-once commands by pattern matching. It is a
  guard rail, **not a sandbox**, and it can be worked around by anyone determined to.
- Detection precision has a measured lower bound of **4 of 50 — 8%**. Do not build a
  control that assumes it catches everything.
