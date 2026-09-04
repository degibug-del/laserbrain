/**
 * Do nova's two planners return the same plan?
 *
 * WHY THIS EXISTS, and it is not a flattering reason. On 2026-09-01 a page was published
 * saying "a check fails if the two disagree on any case". There was no check. The parity had
 * been verified once, by hand, in the session that wrote the port — which is the same shape
 * as every defect this repository has spent the day finding: a claim on a live surface with
 * nothing holding it up. This file is the check that sentence described.
 *
 * THE REFERENCE IS PYTHON. nova.plan() in laserbrain/python is where the planner was written
 * and tested; json/plan-vectors.json is generated FROM it. javascript/planner.mjs follows.
 * One of them has to be named or "parity" means two things drifting together.
 *
 * WHAT THE CASES COVER, and each is here because it is a way the port could look right and
 * be wrong:
 *
 *   a chain nobody wrote          the ordinary case
 *   skips what is already true    `have` short-circuits, rather than replaying a script
 *   a goal already met            returns [] — NOT null. Different answers.
 *   nothing produces it           returns null with the condition named
 *   shortest of two routes        breadth-first, not the first route found
 *   order decides a tie           declaration order, so ties resolve identically
 *   a cycle terminates            visited-states, or the port hangs where Python does not
 *   a broken skill is excluded    distrust changes the plan
 *   excluded and now unreachable  and the message names the skill, not the goal
 *   two conditions wanted         a goal is a SET, not one string
 *
 * `steps: []` and `steps: null` are compared strictly, because collapsing them is the
 * easiest way to write a port that passes a loose check and answers the wrong question:
 * "already true" and "no route" are opposite outcomes.
 *
 * Run:  node scripts/check-plan-parity.mjs
 *       node scripts/check-plan-parity.mjs --control   (prove the gate can fail)
 */
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { plan } from '../javascript/planner.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const V = JSON.parse(readFileSync(join(ROOT, 'json/plan-vectors.json'), 'utf8'))

/* CONTROL. A gate nobody has watched fail is a gate nobody knows is wired up — the same
 * lesson as `silence is not success`, which this repository learned by shipping a suite that
 * asserted on a substring and would have passed on a false sentence forever. With --control
 * one vector's expected answer is corrupted, and the run MUST report a failure. */
const control = process.argv.includes('--control')

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b)
const problems = []

for (const [i, c] of V.cases.entries()) {
  const skills = c.skills.map((s) => ({ ...s, broken: c.broken.includes(s.name) ? 1 : 0 }))
  const got = plan(skills, c.want, c.have)
  const wantSteps = control && i === 0 ? ['deliberately wrong'] : c.steps
  if (!same(got.steps, wantSteps)) {
    problems.push(`${c.name}\n        python ${JSON.stringify(wantSteps)}\n        js     ${JSON.stringify(got.steps)}`)
    continue
  }
  if ((got.why || null) !== (c.why || null)) {
    problems.push(`${c.name} — the plan matches and the REASON does not\n`
      + `        python ${JSON.stringify(c.why)}\n        js     ${JSON.stringify(got.why)}`)
  }
}

if (problems.length) {
  console.error(`\n  FAIL  nova's planners disagree — ${problems.length} of ${V.cases.length} cases\n`)
  for (const p of problems) console.error(`      ✗ ${p}`)
  console.error('\n  The Python is the reference. Either the port is wrong, or the behaviour')
  console.error('  changed and json/plan-vectors.json needs regenerating from it.\n')
  process.exit(control ? 0 : 1)
}

if (control) {
  console.error('\n  FAIL  --control corrupted a vector and the gate still passed.')
  console.error('  The check is not comparing what it claims to compare.\n')
  process.exit(1)
}
console.log(`  ok    plan parity — ${V.cases.length}/${V.cases.length}, python and javascript`)
