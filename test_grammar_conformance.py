#!/usr/bin/env python3
"""test_grammar_conformance.py — one grammar, everywhere, or this fails.

THE DEFECT THIS PINS. The grammar was a literal in mcp-server.mjs and a second literal in
phronesis-world's API route. By 2026-07-26 they disagreed: the public endpoint served
1.0.0 with no parent_goal while the harness an agent actually called served 1.1.0 with it.

That is not a cosmetic mismatch. The document declares `immutable: true`, and PROOF turns
on a reference that is fixed, findable and unchangeable. Two versions under one URL breaks
"findable" and mocks "unchangeable" — the reference an agent checks itself against was not
the reference a reader could fetch. Nobody noticed for a day; it surfaced only because
Diego asked "have we mechanized grammar?" and the answer required looking.

So: one canonical file, and everything else must equal it.

    lasermind/grammar.json                              canonical — the server READS it
    phronesis-world/functions/api/laserbrain/*.json     synced copy — a static deploy
                                                        cannot read another repo
    https://phronesis.world/api/laserbrain/grammar      what the world actually gets

The live check is the one that matters and the one that can be skipped honestly: if the
network is down it says so rather than passing. A conformance test that quietly does not
run is how the divergence lasted as long as it did.
"""
import json
import pathlib
import sys
import urllib.error
import urllib.request

# ONE STATE ROOT — a private tree, so this suite cannot write into the live corpus.
#
# It could, and it did. On 2026-08-05 the live drift log held 2,644 rows of which 1,058 —
# 40% — were written by suites spawning the server against the real ~/.config/laserbrain.
# Synthetic runs are pathological ON PURPOSE (flat distance, repeated goals, abandon bait),
# so they do not dilute the corpus evenly: `stalled` is 39.7% of the test rows against 3.2%
# of the real ones, which makes the whole-log rate 5.6x the truth. Every threshold ever read
# off this log was read off that mixture.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _testhome                                                   # noqa: E402
_testhome.isolate()


HERE = pathlib.Path(__file__).parent
CANON = HERE / 'grammar.json'
COPY = pathlib.Path.home() / 'phronesis-world' / 'functions' / 'api' / 'laserbrain' / 'grammar.json'
LIVE = 'https://phronesis.world/api/laserbrain/grammar'

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def diff(a, b):
    """Where two grammar documents disagree, in words rather than a dump."""
    out = []
    for k in sorted(set(a) | set(b)):
        if k not in a:
            out.append(f'only in second: {k}')
        elif k not in b:
            out.append(f'only in first: {k}')
        elif a[k] != b[k]:
            if isinstance(a[k], dict) and isinstance(b[k], dict):
                for kk in sorted(set(a[k]) | set(b[k])):
                    if a[k].get(kk) != b[k].get(kk):
                        out.append(f'{k}.{kk} differs')
            else:
                out.append(f'{k}: {a[k]!r} vs {b[k]!r}')
    return '; '.join(out) or 'no difference'


show('the canonical grammar exists', CANON.exists(), str(CANON))
if not CANON.exists():
    raise SystemExit(1)
canon = json.loads(CANON.read_text())

# ── the shape the proof depends on ──────────────────────────────────────────
show('it declares a version', bool(canon.get('laserbrain_grammar')), canon.get('laserbrain_grammar'))
show('it declares itself immutable', canon.get('immutable') is True)
show('progress_enum is exactly the three states',
     canon.get('progress_enum') == ['advancing', 'stuck', 'circling'])
for f in ('goal', 'progress', 'distance', 'parent_goal'):
    show(f'field {f!r} is documented', f in (canon.get('fields') or {}))

# ── the site's copy ─────────────────────────────────────────────────────────
if COPY.exists():
    copy = json.loads(COPY.read_text())
    show('the site copy is byte-equal to canonical', copy == canon, diff(canon, copy))
else:
    show('the site copy exists', False, f'missing: {COPY}')

# ── what the world actually receives ────────────────────────────────────────
# The deployed answer is the only one a reader can check, so a mismatch here is the real
# failure even when both files agree.
try:
    # A User-Agent is required: the edge answers urllib's default with 403, which would
    # read as "the endpoint is broken" when it is merely fussy about clients.
    req = urllib.request.Request(LIVE, headers={'User-Agent': 'laserbrain-conformance/1.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        live = json.loads(r.read().decode())
    show('the LIVE endpoint matches canonical', live == canon, diff(canon, live))
except (urllib.error.URLError, TimeoutError, OSError) as e:
    show('the LIVE endpoint could be reached', False, f'{type(e).__name__}: {e} — NOT a pass')

# ── and the server reads rather than restates ───────────────────────────────
server = (HERE / 'mcp-server.mjs').read_text()
show('mcp-server.mjs READS grammar.json instead of restating it',
     "readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'grammar.json')" in server)
show('and holds no second literal version string',
     "laserbrain_grammar: '" not in server)

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
