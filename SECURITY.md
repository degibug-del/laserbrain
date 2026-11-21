# Security

## What this software does to your machine

`laserbrain install` writes to `~/.claude/settings.json` and installs a **`PreToolUse`
hook**, `lb_safety`. That hook sees every tool call your agent makes before it runs, and can
refuse a shell command. That is the highest-trust position in an agent stack, and it is the
reason this repository exists rather than only a package on a registry: you should be able to
read it first. It also wires `lb_coverage` after each tool call and on each message. It
records steps and refuses nothing; on each new user message it adds one line to the agent's
context asking for that turn's check (`LASERBRAIN_TURN_LINE=off` silences it). `lb_gate`,
which can refuse other calls, is wired only with `--with-gate`.

The offline stdio MCP server (`laserbrain mcp`) is registered in Claude Code's own server
list, through `claude mcp add --scope user`; when `claude` is not on PATH, install prints
that line instead of running it. Claude Code does not read MCP servers from `settings.json`,
so install no longer writes one there.

The relevant code is small and in one place:

- [`python/laserbrain/hooks/`](python/laserbrain/hooks) — the hooks and the modules they load
- [`python/laserbrain/install.py`](python/laserbrain/install.py) — everything that touches your settings

`laserbrain install` backs up your existing settings to `settings.json.before-laserbrain`,
merges rather than overwrites, and verifies the hooks execute before reporting success. Where
you already run lb_safety from your own entry, install leaves it alone and says it did not
verify it. `laserbrain uninstall` takes out what install added (and runs `claude mcp remove
--scope user laserbrain` only for the server entry install registers); then `pip uninstall
laserbrain`.

### The safety hook's one config file

`lb_safety` reads one optional file, `~/.config/laserbrain/safety.json`
(`$LASERBRAIN_HOME/config/safety.json` when that variable is set), and only after a command
has matched a deny rule:

```json
{"allow_worker_deploys": ["my-worker"]}
```

Each name lets a `wrangler deploy` run when the same command names that Worker (by `cd` or
`--config`).

Read what an allowance does before you add one. Any command that contains an allowed name
and `wrangler deploy` anywhere skips **every** rule, including one that also force-pushes or
deletes. The name is matched as plain text, case-insensitively, anywhere in the command, so
`my-worker` also allows `my-worker-2`, and a short or common name (`x`, `npx`, `workers`)
matches nearly every deploy. Only allow a distinctive name, for a Worker you would let an
agent deploy unattended.

A missing, unreadable, oversized or malformed file allows nothing, and so does anything at
that path that is not a regular file. A name that is not a plain path fragment (so `""` or
`.*`) is skipped. An agent with file tools could write this file, so treat a change to it
like a change to `settings.json`. Until 0.58.0 one Worker name was built into the hook
itself.

## What it sends

The check, the hooks and the stdio MCP server (`laserbrain mcp`) make **no network calls**
— verified by blocking `socket.connect` and `socket.create_connection`, then importing
every shipped module, the hooks in `laserbrain/hooks/` included, and exercising the full
path: check, reground, async check, judgment, report, ledger and export. Zero connection
attempts, and importing the package pulls in no TLS or HTTP client at all. Re-run it
yourself with `python3 test_no_network.py`.

Some features you call or opt into do reach a server: `laserbrain key` and
`Harness(key=...)` (which mirrors readings to the hosted API), the field helpers
(`read_field` reads `https://phronesis.world/api/laserbrain` by default), the link-service
helpers in `services.py`, and `Operator.http`. None of them runs unless you call it.

That replaces the method this file used to cite — scanning every shipped file for URLs —
which would not have caught a host assembled at runtime, read from the environment, or
reached through a dependency. The claim was true; the way it was checked could not
establish it. State is written under your own home directory
(`~/.claude/laserbrain`, `~/.config/laserbrain`).

**One exception, in a repository checkout only.** Two checks that lb_coverage loads,
`lb_askllm_watch.py` (a helper agent's first check_state) and `lb_turnwatch.py` (the main
session's first check_state after each user message), grade with frozen scorers that live in
`research/eval/`, which is not in the wheel. Where that folder exists they start a detached
process that runs your own `claude -p` once (Haiku; no settings, hooks, tools or MCP servers),
sending excerpts of the transcript (the user's recent messages, the task or goal, the agent's
first words) after the `lb_secrets` patterns have redacted them; a text that cannot be redacted
is dropped. The token is your Claude Code login, or the Keychain item `claude-oauth-token`,
passed only in that child's environment and never logged. The detached process first cuts its
environment to an allowlist (PATH, HOME, USER, LOGNAME, SHELL, TMPDIR, TZ, LANG, `LC_*`, proxy
and CA settings, `CLAUDE_CONFIG_DIR`, `LASERBRAIN_*`), so nothing else the host session set
reaches `claude -p`; the kept names, never values, are logged. Before turnwatch sends anything it
checks the sha256 of every `research/eval` file its judge loads, refuses any unpinned one, and
checks that a synthetic secret still comes back redacted. Each is capped at 80 calls a day.
Switch them off with `LASERBRAIN_ASKLLM_MODE=off` and `LASERBRAIN_TURNWATCH=off` (or the files
`askllm-watch.off` and `turnwatch.off` in the state directory). In an installed package their
code is present but finds no frozen scorer, so they start no process and send nothing;
`test_no_network.py` covers the package as installed.

The hosted MCP endpoint and the `/v1` REST API are opt-in and separate. If you use those,
your spelled goals and verdicts reach that server. The Claude Code plugin connects the hosted
MCP endpoint, so with the plugin they reach it too. With the check, the hooks and
`laserbrain mcp`, they do not leave your machine.

## Reporting a vulnerability

Email **degibug@gmail.com** with `laserbrain security` in the subject. Please include what
you found, how to reproduce it, and what you think the impact is. You will get a reply.

Please do not open a public issue for anything that lets a third party read another user's
readings, bypass the safety hook, or execute code through the install path.

## Known limits, stated plainly

- The hooks are **host-specific**. `laserbrain install` sets up Claude Code only; wiring
  another host means writing that integration.
- `lb_safety.py` blocks destructive and publish-once commands by pattern matching. It is a
  guard rail, **not a sandbox**, and it can be worked around by anyone determined to.
  Since 0.58.0 a command that only mentions a guarded phrase (it only prints or searches,
  and writes nothing that can run) is let through, tested on 72 real cases; any doubt
  blocks.
  A script written with a file tool and run in a later call was never visible to it.
- The drift check is not a control. In a month of labelled real use on one machine, the
  live check caught 1 of 16 drifted helper agents, and 2 of its 21 live alarms were real
  (live · one session · AI-labelled). Do not build anything that relies on it noticing.
