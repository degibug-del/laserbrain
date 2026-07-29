#!/usr/bin/env python3
"""test_laserscore_conformance.py — one laserscore, written the same way twice.

A laserscore is the grammatical object laserbrain produces: one well-formed reading
written in the grammar at a single step. Φ is a measurement taken of that writing. So the
laserscore is the thing a reader checks the number against — and it is worth exactly as
much as its reproducibility. Two renderers that disagree would mean the audit trail from
lasermind and the audit trail from the PyPI SDK cannot be compared, which is the same
defect test_vocab_conformance.py already pins one layer down: there, the two normalisers
disagreed silently for a day and a hard-coded 0.46 met a computed 0.56.

Normalisation agreement is necessary but not sufficient. The renderers could share toWords
and still order tokens differently, join them differently, or format the distance
differently. This file pins the written form itself.

Requires node. Skips loudly rather than silently — a conformance test that quietly does
not run is how the last divergence lasted as long as it did.
"""
import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'laserbrain-sdk'))
from laserbrain import laserscore                                   # noqa: E402

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


if not shutil.which('node'):
    print('  ✗ node not found — cannot compare renderers. NOT a pass.')
    raise SystemExit(1)

# (goal, progress, distance, parent_goal)
CASES = [
    ('build the sky billboard', 'advancing', 3, None),
    ('building billboards', 'advancing', 3, None),
    ('build a billboard', 'advancing', 3, None),          # must equal the line above
    ('make laserscore first class', 'advancing', 7, None),
    ('fix the ci script', 'advancing', 3, 'make laserscore first class'),
    ('ship nano DRIFT to the App Store', 'stuck', 10, None),
    ('ship nano DRIFT to the App Store', 'circling', 0, None),
    ("fix SOLO's display name from Best Score to Solo", 'advancing', 5, None),
    ('a an the of and', 'advancing', 4, None),            # normalises to nothing
    ('RUNNING runner runs run', 'advancing', 6, 'deployment deploys deployed'),
    ('refactor the particle renderer', 'advancing', 0, '   '),  # blank parent = no parent
]

SERVER = pathlib.Path(__file__).parent / 'mcp-server.mjs'
js = f'''
import {{ readFileSync }} from 'node:fs'
const src = readFileSync({json.dumps(str(SERVER))}, 'utf8')
const words = src.match(/const _STOP = new Set\\(\\[[\\s\\S]*?\\n\\}}/)
const dist  = src.match(/const asDist = .*/)
// The renderer enforces the grammar's precondition, so it needs the progress enum in
// scope. Extracted rather than restated: a second copy of the enum in this test would be
// one more thing that can drift from the server, which is what the test exists to stop.
const prog  = src.match(/const PROGRESS = new Set\\(\\[.*?\\]\\)/)
const score = src.match(/const laserscore = \\(s, parent\\) => \\{{[\\s\\S]*?\\n\\}}/)
if (!words) {{ console.error('could not extract toWords'); process.exit(2) }}
if (!dist)  {{ console.error('could not extract asDist');  process.exit(2) }}
if (!prog)  {{ console.error('could not extract PROGRESS'); process.exit(2) }}
if (!score) {{ console.error('could not extract laserscore'); process.exit(2) }}
const fn = new Function(words[0] + '\\n' + dist[0] + '\\n' + prog[0] + '\\n' + score[0] + '; return laserscore;')()
const cases = {json.dumps(CASES)}
console.log(JSON.stringify(cases.map(([g, p, d, par]) =>
  fn({{ goal: g, progress: p, distance: d }}, par))))
'''
res = subprocess.run(['node', '--input-type=module', '-e', js],
                     capture_output=True, text=True)
if res.returncode != 0:
    print('  ✗ could not run the server renderer:', res.stderr.strip()[:300])
    raise SystemExit(1)

server_out = json.loads(res.stdout)

for (goal, progress, d, parent), got in zip(CASES, server_out):
    want = laserscore(goal, progress, d, parent)
    label = repr(goal)[:40]
    show(f'{label:<42} agree', got == want,
         '' if got == want else f'server {got!r} vs sdk {want!r}')

# ── the properties the written form has to have ─────────────────────────────
show('inflection collapses — "building billboards" == "build a billboard"',
     laserscore('building billboards', 'advancing', 3)
     == laserscore('build a billboard', 'advancing', 3),
     laserscore('building billboards', 'advancing', 3))

show('a named parent_goal is visible in the score',
     '⊂' in laserscore('fix the ci script', 'advancing', 3, 'ship nano DRIFT'))

show('a blank parent_goal adds nothing',
     '⊂' not in laserscore('fix the ci script', 'advancing', 3, '   '))

show('distance is part of the score — d3 and d7 differ',
     laserscore('same goal', 'advancing', 3) != laserscore('same goal', 'advancing', 7))

show('progress is part of the score — advancing and stuck differ',
     laserscore('same goal', 'advancing', 3) != laserscore('same goal', 'stuck', 3))

show('token order is canonical, not input order',
     laserscore('billboard sky build', 'advancing', 3)
     == laserscore('build the sky billboard', 'advancing', 3))

# The SDK renders 'd?' when distance is unknown; the server coerces a missing distance to
# 5 via asDist. Those would disagree — so the server must never see one. It doesn't: the
# tool schema marks distance required. This asserts that guard rather than assuming it.
server_src = SERVER.read_text()
show("the server's schema requires distance, so 'd?' cannot arise there",
     "required: ['goal', 'progress', 'distance']" in server_src)

# ── and the grammar has to document what it produces ────────────────────────
grammar = json.loads((pathlib.Path(__file__).parent / 'grammar.json').read_text())
show('the grammar documents laserscore', 'laserscore' in grammar)
show('the grammar documents drift_score', 'drift_score' in grammar)
show('the grammar names the derivation', 'derivation' in grammar,
     str(grammar.get('derivation', ''))[:70])
show('laserscore names what Φ measures',
     (grammar.get('laserscore') or {}).get('measured') == ['goal', 'progress', 'distance'])

# The public description promises "any GRAMMATICAL goal". The grammar has to state that
# scope in its own words, or the sentence on the site is the only place it exists — and
# the site is not the reference. Added in 1.2.1 for exactly that reason.
show('laserscore states the grammaticality precondition',
     bool((grammar.get('laserscore') or {}).get('precondition')))
show('drift_score states that it requires a laserscore',
     bool((grammar.get('drift_score') or {}).get('requires')))
show('the precondition says an unspellable goal yields no score',
     'no laserscore' in str((grammar.get('laserscore') or {}).get('precondition', '')))

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
