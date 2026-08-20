# javascript — the local stdio MCP server

This is what answers our own `check_state` calls. It is the server behind the
`mcp__laserbrain__*` tools in the session that built most of this repository, so it is here
because showing what we actually run is more honest than describing it.

## Run it

```bash
node mcp-server.mjs
```

It speaks MCP over stdin/stdout. Offline, no key, no network. To wire it into an agent host
directly:

```json
{ "mcpServers": {
    "laserbrain": { "type": "stdio", "command": "node",
                    "args": ["/absolute/path/to/javascript/mcp-server.mjs"] } } }
```

**Prefer `laserbrain mcp` from the Python package** for anything you intend to keep. It
needs no absolute path, updates with `pip install --upgrade`, and ships the enforcement
hooks alongside. This server exposes a wider internal toolset — 28 tools against the
package's 11 — which is useful for development and more than most users need.

## Files

| file | |
|---|---|
| `mcp-server.mjs` | the server |
| `lb_paths.mjs` | resolves the state directory. **Required** — the server will not start without it |
| `hooks/` | host-side helpers |
| `SPINE.md` | the design note: when an agent is too confused, or has recursed too deep, to be worth continuing |
| `calibrate_attention.py`, `test_*.py` | the calibration tooling that produces `../json/attention.json` |

`lb_paths.mjs` is listed first among the required files deliberately: it was left out of
the initial copy here, and a fresh clone died with `ERR_MODULE_NOT_FOUND` on the first run.

## The grammar

Read from [`../json/grammar.json`](../json/grammar.json) — the same file the Python package
and the hosted Worker read. The logic is deliberately re-implemented per language; the
contract is not.

## What this is not

Not the published package. npm's `laserbrain` is the TypeScript library in
[`../typescript/`](../typescript), which is parity-checked against Python. This server is
infrastructure, and it has no parity suite of its own.
