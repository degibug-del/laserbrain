/**
 * The npm package must agree with the Python package, step for step.
 *
 * The vectors are generated FROM the Python side by gen-drift-vectors.py, so PyPI is the
 * reference and this is the thing being checked — not the other way round. They are
 * SEQUENCES rather than one-shot cases because the first check sets the frozen ground and
 * every later verdict depends on it; one-shot vectors would exercise almost none of it.
 */
import { readFileSync } from 'node:fs'
import { emptyDrift, checkStep } from '../dist/drift.js'

type Step = { in: Record<string, unknown>; out: Record<string, unknown> }
const data = JSON.parse(readFileSync(new URL('./drift-vectors.json', import.meta.url), 'utf8'))

let checked = 0
const bad: string[] = []

for (const vec of data.vectors as { seq: number; steps: Step[] }[]) {
  let state = emptyDrift()
  vec.steps.forEach((s, i) => {
    const { verdict, state: next } = checkStep(state, s.in as never)
    state = next
    for (const [k, want] of Object.entries(s.out)) {
      const got = (verdict as Record<string, unknown>)[k]
      const same = typeof want === 'number' && typeof got === 'number'
        ? Math.abs(want - got) < 1e-9 : JSON.stringify(want) === JSON.stringify(got)
      checked++
      if (!same) bad.push(`seq ${vec.seq} step ${i} · ${k}: want ${JSON.stringify(want)}, got ${JSON.stringify(got)}`)
    }
  })
}

console.log(`\n  parity against laserbrain ${data.sdk_version} (PyPI)`)
console.log(`  ${data.vectors.length} sequences · ${checked} field comparisons\n`)
if (bad.length) {
  for (const b of bad.slice(0, 12)) console.error('  MISMATCH ' + b)
  console.error(`\n  FAIL — ${bad.length} mismatches. The npm package disagrees with PyPI.\n`)
  process.exit(1)
}
console.log('  PASS — every field matches the Python implementation.\n')
