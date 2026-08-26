#!/usr/bin/env python3
"""The MCP server's door into the Python SDK.

Reads one JSON object on stdin, writes one JSON object on stdout. Nothing else — no
banner, no logging to stdout, because the caller parses the whole stream.

WHY A BRIDGE AND NOT A REIMPLEMENTATION
---------------------------------------
Supercode, Search, Writer and the six catches are Python. The MCP server is JavaScript.
The tempting move is to port them, and this session is a catalogue of what that costs:
three hand-kept copies of the logo that had already drifted, a verdict set that shipped
nine in the SDK and eight on the site, four separate resolvers for one log path. Every one
of those was two copies of a thing that had to agree and no mechanism making them.

So: one implementation, reached over a pipe. A port would be a seventh copy.

WHICH SDK
---------
`import laserbrain` resolves to site-packages, which is the PUBLISHED build and lags the
working tree — on 2026-07-27 the installed 0.7.0 was missing three catches from __all__
and the whole tandem->link rename. A bridge that silently called the stale copy would be
the same drift wearing a different hat, so the source tree wins when it is present and the
answer says which one it used. Override with LASERBRAIN_SDK.

WHAT CANNOT COME THROUGH
------------------------
`stale_gate(gate, mutate, sample)` takes two callables — a gate to run and a mutation to
apply. Those are code, not data, and there is no honest way to send them through a JSON
tool boundary. It stays a Python-only function and `capabilities` reports it as such
rather than pretending.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

# ── resolve the SDK before importing it ──────────────────────────────────────────
# TWO SOURCE TREES, IN PRECEDENCE ORDER. This named only the working tree's
# laserbrain-sdk/ path, which does not exist in the published repo — where the SDK sits in
# python/, one directory up from this file. Vendored here 2026-08-21; the reorg carried
# mcp-server.mjs across and left the bridge it calls behind, so BRIDGE pointed at nothing.
_CANDIDATES = [
    os.environ.get('LASERBRAIN_SDK'),
    # TWO candidates for "this repo", because this file is byte-identical in two places at
    # different depths — python/laserbrain/sdk_bridge.py and javascript/sdk_bridge.py — and
    # test_server_parity.py asserts they match. One relative expression cannot be right from
    # both. The old single line, parent.parent/'python', resolved correctly from javascript/
    # and pointed at python/python from the other, so on this machine the bridge fell through
    # to the RETIRED 0.53.0 iCloud tree while sitting inside the 0.55.0 one. Found 2026-08-25
    # by a collaborator running the tree on Windows, where candidate 3 does not exist either
    # and nothing resolved at all.
    str(Path(__file__).resolve().parent.parent),                    # from python/laserbrain/
    str(Path(__file__).resolve().parent.parent / 'python'),         # from javascript/
    str(Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis/laserbrain-sdk'),
]
_SRC = next((c for c in _CANDIDATES
             if c and (Path(c) / 'laserbrain' / '__init__.py').exists()),
            _CANDIDATES[1])
if (Path(_SRC) / 'laserbrain' / '__init__.py').exists():
    sys.path.insert(0, _SRC)

import laserbrain as lb                                            # noqa: E402

# Report the file that actually got imported, not the mechanism that found it. The first
# version said 'installed' or 'source:<path>' based on which branch ran — which went wrong
# the moment the package was installed editable, because then 'installed' AND 'source' are
# the same files and the label implied a difference that no longer existed. A path cannot
# be wrong in that way.
_resolved = Path(lb.__file__).resolve().parent.parent
_origin = str(_resolved)
_editable = str(_resolved) == str(Path(_SRC).resolve())
# `laserbrain.catches` the FUNCTION shadows `laserbrain.catches` the MODULE, so the six
# catch helpers are unreachable as attributes of the package. importlib gets the module.
_catches = importlib.import_module('laserbrain.catches')


# ── the operations ───────────────────────────────────────────────────────────────
# THE OPS MOVED INTO THE PACKAGE, 2026-08-22, and this imports them rather than holding a
# second copy. They were defined here, which meant the offline server in that same package
# could not serve them: `laserbrain mcp` shipped 11 tools while this bridge reached 28. The
# capability was never missing, only the door — and duplicating them to open it would have
# created exactly the two-copies-that-must-agree problem this codebase keeps fixing.
#
# So there is one definition, in laserbrain._ops, and two front doors onto it: this bridge
# for the JS server, and mcp.py for the Python one. They cannot drift because there is
# nothing to drift from.
from laserbrain._ops import OPS                                     # noqa: E402




def main():
    try:
        req = json.loads(sys.stdin.read() or '{}')
        fn = OPS.get(req.get('op'))
        if fn is None:
            out = {'error': f"unknown op {req.get('op')!r}", 'known': sorted(OPS)}
        else:
            out = fn(req)
    except Exception as e:                       # the caller gets a reason, never a hang
        out = {'error': f'{type(e).__name__}: {e}'}
    json.dump(out, sys.stdout)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
