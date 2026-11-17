/**
 * The npm package must agree with the Python package, step for step.
 *
 * Vectors are generated FROM Python by gen-drift-vectors.py, so PyPI is the reference and
 * this is the thing being checked. They are SEQUENCES rather than one-shot cases because
 * the first check sets the frozen ground and every later verdict depends on it.
 *
 * PLAIN JAVASCRIPT ON PURPOSE. This was parity.ts and ran only on Node 22+, where the
 * runtime strips types natively — it passed on the author's Node 24 and died in CI on
 * Node 20 with ERR_UNKNOWN_FILE_EXTENSION. It imports compiled output, so it never needed
 * to be TypeScript; being TypeScript only narrowed the set of machines that could run it.
 */
import { readFileSync } from 'node:fs'
import { emptyDrift, checkStep, isDrift } from '../dist/drift.js'

const data = JSON.parse(readFileSync(new URL('../../json/drift-vectors.json', import.meta.url), 'utf8'))

let checked = 0
const bad = []

for (const vec of data.vectors) {
  let state = emptyDrift()
  vec.steps.forEach((s, i) => {
    const { verdict, state: next } = checkStep(state, s.in)
    state = next
    for (const [k, want] of Object.entries(s.out)) {
      const got = verdict[k]
      const same = (typeof want === 'number' && typeof got === 'number')
        ? Math.abs(want - got) < 1e-9
        : JSON.stringify(want) === JSON.stringify(got)
      checked++
      if (!same) bad.push(`seq ${vec.seq} step ${i} · ${k}: want ${JSON.stringify(want)}, got ${JSON.stringify(got)}`)
    }
  })
}

// ── goal-drift is a note, not an interrupt (2026-11-15) ──────────────────────────────
// research/DAY-FIVE-REAL-SESSIONS.md §3: all 7 live goal-drift fires were false. The vectors
// above already pin drifting=false on every goal-drift step; these pin what vectors cannot:
// the advice wording, the first-strike rule and the escalation. Same contract as
// python/test_goal_drift_note.py and javascript/test_goal_drift_note.py.
let noteChecks = 0
const expect = (label, cond, detail) => {
  noteChecks++
  if (!cond) bad.push(`goal-drift note · ${label}${detail === undefined ? '' : ': ' + JSON.stringify(detail)}`)
}
const run = (steps) => {
  let st = emptyDrift(), v = null
  for (const s of steps) ({ verdict: v, state: st } = checkStep(st, s))
  return v
}
const G = 'build the JSON parser'
const plain = run([{ goal: G, progress: 'advancing', distance: 6 },
                   { goal: 'write a poem about the sea', progress: 'advancing', distance: 5 }])
expect('plain: reason kept', plain.reason === 'goal-drift', plain.reason)
expect('plain: drifting false', plain.drifting === false, plain.drifting)
const rej = run([{ goal: G, progress: 'advancing', distance: 6 },
                 { goal: 'cook a vegan dinner', progress: 'advancing', distance: 5,
                   parent_goal: 'paint the garden fence' }])
expect('rejected parent: reason kept', rej.reason === 'goal-drift', rej.reason)
expect('rejected parent: drifting false', rej.drifting === false, rej.drifting)
for (const [name, v] of [['plain', plain], ['rejected parent', rej]]) {
  expect(`${name}: says it is not an interrupt`, v.advice.includes('not an interrupt'), v.advice)
  expect(`${name}: points at the ground`, v.advice.includes('compare your goal with the ground'), v.advice)
  expect(`${name}: no order to return`, !/return/i.test(v.advice), v.advice)
}
expect('plain: still offers parent_goal', plain.advice.includes('pass parent_goal'), plain.advice)
expect('rejected parent: never asks for what it just got', !rej.advice.includes('pass parent_goal'), rej.advice)
expect("isDrift('goal-drift') is false", isDrift('goal-drift') === false)
expect("isDrift('ungrammatical') is still true", isDrift('ungrammatical') === true)
const afterGd = run([{ goal: G, progress: 'advancing', distance: 5 },
                     { goal: 'write a poem about the sea', progress: 'advancing', distance: 5 },
                     { goal: G, progress: 'stuck', distance: 5 }])
expect('a first self-report after goal-drift warns',
       afterGd.reason === 'self-report:stuck' && afterGd.drifting === false, afterGd)
const afterUngr = run([{ goal: G, progress: 'advancing', distance: 5 },
                       { goal: '', progress: 'advancing', distance: 5 },
                       { goal: G, progress: 'stuck', distance: 5 }])
expect('...and after ungrammatical it still interrupts',
       afterUngr.reason === 'self-report:stuck' && afterUngr.drifting === true, afterUngr)
const many = run([{ goal: G, progress: 'advancing', distance: 5 },
                  { goal: 'write a poem about the sea', progress: 'advancing', distance: 5 },
                  { goal: 'paint the garden fence', progress: 'advancing', distance: 5 },
                  { goal: 'cook a vegan dinner', progress: 'advancing', distance: 5 }])
expect('three goal-drifts: still not drifting', many.reason === 'goal-drift' && many.drifting === false, many)
expect('three goal-drifts: the existing escalation still says wrong-problem',
       many.judgment?.verdict === 'wrong-problem', many.judgment)

console.log(`\n  npm package vs laserbrain ${data.sdk_version} (Python)`)
console.log(`  ${data.vectors.length} sequences · ${checked} field comparisons · ${noteChecks} goal-drift note checks\n`)
if (bad.length) {
  bad.slice(0, 12).forEach((b) => console.error('  MISMATCH ' + b))
  console.error(`\n  FAIL — ${bad.length} mismatches. The npm package disagrees with PyPI.\n`)
  process.exit(1)
}
console.log('  PASS — every field matches the Python implementation.\n')
