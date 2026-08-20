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
import { emptyDrift, checkStep } from '../dist/drift.js'

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

console.log(`\n  npm package vs laserbrain ${data.sdk_version} (Python)`)
console.log(`  ${data.vectors.length} sequences · ${checked} field comparisons\n`)
if (bad.length) {
  bad.slice(0, 12).forEach((b) => console.error('  MISMATCH ' + b))
  console.error(`\n  FAIL — ${bad.length} mismatches. The npm package disagrees with PyPI.\n`)
  process.exit(1)
}
console.log('  PASS — every field matches the Python implementation.\n')
