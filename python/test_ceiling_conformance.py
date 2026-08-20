#!/usr/bin/env python3
"""test_ceiling_conformance.py — the Python marker and the JS marker must agree.

The phrase lists moved into grammar.json precisely so there would be ONE list with two
readers. That buys nothing on its own: two implementations reading one list can still
disagree about what reading it means — a different regex assembly, a different tie-break
between overlapping phrases, a different answer for "nothing matched". This project has
already watched exactly that happen with the normaliser, where the same goal pair scored
0.46 in the server and 0.56 in the SDK, both reading their own copy, nothing checking.

So this runs both markers over the same inputs and fails on the first disagreement. It is
the test that makes one list with two readers a fact rather than an intention.

Skipped, loudly, if node or mcp-server.mjs is absent — the SDK ships to people who have
neither, and a gate that fails on a missing sibling checkout teaches people to ignore it.
"""
import json
import os
import pathlib
import random
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from laserbrain.ceiling import mark, CAUSE_PATTERNS, OBSERVATION_PATTERNS  # noqa: E402

_ROOT = pathlib.Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis'
SERVER = pathlib.Path(os.environ.get('LASERMIND_SERVER') or _ROOT / 'lasermind/mcp-server.mjs')

if not shutil.which('node') or not SERVER.exists():
    print(f'  SKIP — node or {SERVER.name} unavailable; nothing to compare against')
    sys.exit(0)

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


# Drive the REAL server over stdio, not a copy of its marker.
#
# The first version of this test inlined its own copy of markCeiling and compared against
# that. It passed on 304 inputs and proved almost nothing: a copy agreeing with a copy is
# the exact failure this project keeps finding, one level up from the lists themselves.
# What has to agree is the function that actually ships. So this speaks MCP to
# mcp-server.mjs and reads the `claims` its check_state really returns.
JS_DRIVER = r'''
import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'

const inputs = JSON.parse(readFileSync(process.argv[3], 'utf8'))
const srv = spawn('node', [process.argv[2]], {
  stdio: ['pipe', 'pipe', 'pipe'],
  // LASERBRAIN_ARM=open: this is a test harness, not a session. The arm file is
  // machine-global, so without this the run inherits whichever arm the human's live agent
  // is in — and a blinded check_state returns no `claims` at all, which reads here as 94
  // inputs "differing" when the two implementations in fact agree.
  env: { ...process.env,
         LASERBRAIN_ARM: 'open',
         LASERBRAIN_DRIFT_LOG: '/tmp/ceiling-conf-drift.jsonl',
         LASERBRAIN_OUTCOMES_LOG: '/tmp/ceiling-conf-out.jsonl' },
})
let buf = ''
const pending = new Map()
srv.stdout.on('data', (d) => {
  buf += d
  let i
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i); buf = buf.slice(i + 1)
    if (!line.trim()) continue
    try { const m = JSON.parse(line); if (pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } } catch {}
  }
})
let id = 0
const call = (method, params) => new Promise((res) => {
  const myId = ++id
  pending.set(myId, res)
  srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: myId, method, params }) + '\n')
})
await call('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'conf', version: '1' } })

const out = []
for (const text of inputs) {
  // reset_task each time so a long trace cannot change the verdict shape mid-run; the
  // claims reading is per-step and independent of it, but an isolated run keeps this
  // comparing one thing.
  await call('tools/call', { name: 'reset_task', arguments: {} })
  const r = await call('tools/call', {
    name: 'check_state',
    arguments: { goal: 'conformance probe', progress: 'advancing', distance: 5, doing: text },
  })
  const parsed = JSON.parse(r.result.content[0].text)
  out.push(parsed.claims ?? null)
}
console.log(JSON.stringify(out))
srv.kill()
'''

GRAMMAR = pathlib.Path(__file__).parent / 'laserbrain' / 'grammar.json'

# Randomised, plus the cases a hand-written list would never think to include: empty
# strings, punctuation-adjacent phrases, casing, and phrases that contain each other.
random.seed(11)
fragments = CAUSE_PATTERNS + OBSERVATION_PATTERNS + [
    'edited the file', 'ran nothing', '', '   ', 'BECAUSE', 'Since,', 'i think.',
    'should work should be', 'exit 0 exit 0', 'the reason because since',
]
inputs = [
    'the parser was fixed', '',
    'because it should work', 'ran it, exit 0, tests passed',
]
for _ in range(120):
    n = random.randint(0, 4)
    inputs.append(' '.join(random.choice(fragments) for _ in range(n)))

tmp_in = pathlib.Path('/tmp/ceiling_conformance_inputs.json')
tmp_js = pathlib.Path('/tmp/ceiling_conformance_driver.mjs')
tmp_in.write_text(json.dumps(inputs))
tmp_js.write_text(JS_DRIVER)

out = subprocess.run(['node', str(tmp_js), str(SERVER), str(tmp_in)],
                     capture_output=True, text=True, timeout=300)
if out.returncode != 0:
    print(f'  FAIL — the JS marker did not run:\n{out.stderr[:400]}')
    sys.exit(1)
js_results = json.loads(out.stdout)

check('the grammar is the source for both', 'ceiling_patterns' in json.loads(GRAMMAR.read_text()))
check(f'{len(inputs)} inputs run through the REAL server and the SDK',
      len(js_results) == len(inputs), f'{len(js_results)} returned')

disagreements = []
for text, js in zip(inputs, js_results):
    py = mark(text)
    py_norm = None if py['grounded'] is None else {
        'cause': py['cause'], 'observation': py['observation'], 'grounded': py['grounded'],
        'hits': [list(h) for h in py['hits']],
    }
    if py_norm != js:
        disagreements.append((text, py_norm, js))

check('every input scores identically in Python and JavaScript',
      not disagreements,
      '' if not disagreements else f'{len(disagreements)} differ, first: {disagreements[0]}')

# The null case is the one most likely to diverge, because the two languages spell it
# differently (None vs null) and both are falsy. Pinned explicitly.
none_cases = [i for i, t in enumerate(inputs) if mark(t)['grounded'] is None]
check('and they agree on "nothing matched" specifically',
      all(js_results[i] is None for i in none_cases),
      f'{len(none_cases)} such input(s)')

tmp_in.unlink(missing_ok=True)
tmp_js.unlink(missing_ok=True)

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — one list, two readers, and they agree on every input tried.')
