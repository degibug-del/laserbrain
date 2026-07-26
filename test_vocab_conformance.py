#!/usr/bin/env python3
"""test_vocab_conformance.py — two implementations of one theorem must agree.

laserbrain exists twice: mcp-server.mjs (what an agent actually calls) and laserbrain-sdk
(what anyone installs from PyPI). Until 2026-07-26 they normalised goals DIFFERENTLY — the
server split raw words, the SDK dropped stopwords and stemmed — so the same goal pair
scored 0.46 in one and 0.56 in the other.

Neither was wrong. Nothing enforced either. That is the worst of the three available
states, and it produced a real failure the same day: a test hard-coded 0.46, the SDK
returned 0.56, and the assertion failed for a reason that had nothing to do with the
behaviour under test. A constant copied between implementations asserts only that somebody
copied it.

So this file runs BOTH on identical input and requires the same answer. It is the thing
that makes "the vocabulary is swappable" safe to say: swap it, and this fails until you
swap it in both places.

Requires node. Skips loudly rather than silently if node is missing — a conformance test
that quietly does not run is how the divergence lasted this long.
"""
import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'laserbrain-sdk'))
from laserbrain import norm                                        # noqa: E402

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


if not shutil.which('node'):
    print('  ✗ node not found — cannot compare implementations. NOT a pass.')
    raise SystemExit(1)

CASES = [
    'build the sky billboard',
    'building billboards',
    'build a billboard',
    'verify the 7 leaderboard ids in App Store Connect match the code',
    "fix SOLO's display name from Best Score to Solo",
    'ship the thing',
    'Ship The Things',
    'refactor the particle renderer to use instanced geometry',
    '',
    'a an the of and',                 # stopwords only — must normalise to nothing
    "don't stop believing",            # apostrophes survive tokenising
    'RUNNING runner runs run',         # stemming, including the <=4 char exemption
    'deployment deploys deployed',
]

# Ask the server's own normaliser, via the module it actually ships.
SERVER = pathlib.Path(__file__).parent / 'mcp-server.mjs'
js = f'''
import {{ readFileSync }} from 'node:fs'
const src = readFileSync({json.dumps(str(SERVER))}, 'utf8')
const m = src.match(/const _STOP = new Set\\(\\[[\\s\\S]*?\\n\\}}/)
if (!m) {{ console.error('could not extract toWords from the server'); process.exit(2) }}
const toWords = new Function(m[0] + '; return toWords;')()
const cases = {json.dumps(CASES)}
console.log(JSON.stringify(cases.map(c => [...toWords(c)].sort())))
'''
res = subprocess.run(['node', '--input-type=module', '-e', js],
                     capture_output=True, text=True)
if res.returncode != 0:
    print('  ✗ could not run the server normaliser:', res.stderr.strip()[:200])
    raise SystemExit(1)

server_out = json.loads(res.stdout)

for case, got in zip(CASES, server_out):
    want = sorted(norm(case))
    label = repr(case)[:44]
    show(f'{label:<46} agree', got == want,
         '' if got == want else f'server {got} vs sdk {want}')

# The case that motivated all of this: inflection is not drift.
show('inflection collapses in BOTH — "building billboards" == "build a billboard"',
     sorted(norm('building billboards')) == sorted(norm('build a billboard')),
     str(sorted(norm('building billboards'))))

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
