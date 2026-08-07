#!/usr/bin/env node
/**
 * dogfood-stats — read the drift-fire corpus the harness writes (mcp-server.mjs)
 * and report what we'd tune from for the next iteration. Low-data by design:
 * only the fires are logged, so this is small and fast to eyeball.
 *
 *   node dogfood-stats.mjs                 # default ~/.config/laserbrain/drift-log.jsonl
 *   LASERBRAIN_DRIFT_LOG=path node dogfood-stats.mjs
 *   node dogfood-stats.mjs --tail 20       # show the last N fires to judge false alarms
 *
 * The judgement this feeds: of these fires, which were TRUE catches (the agent
 * really was looping) vs FALSE alarms (it was fine)? That ratio, per signal, is
 * the thing the next rule-tuning turns on. This script surfaces the fires; the
 * labelling is a human/agent read, added later.
 */
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { config as lbConfig } from './lb_paths.mjs'

const LOG = process.env.LASERBRAIN_DRIFT_LOG || lbConfig('drift-log.jsonl')
const tailN = (() => { const i = process.argv.indexOf('--tail'); return i >= 0 ? Number(process.argv[i + 1]) || 20 : 0 })()

let rows = []
try {
  rows = readFileSync(LOG, 'utf8').split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l) } catch { return null } }).filter(Boolean)
} catch {
  console.log(`no corpus yet at ${LOG}\n(the harness writes here once it fires on a real drift — use check_state while you work)`)
  process.exit(0)
}

if (!rows.length) { console.log(`corpus is empty: ${LOG}`); process.exit(0) }

const byReason = {}
const runs = new Set()
let phiSum = 0
for (const r of rows) { byReason[r.reason] = (byReason[r.reason] || 0) + 1; if (r.run) runs.add(r.run); phiSum += Number(r.phi) || 0 }
const phis = rows.map((r) => Number(r.phi) || 0).sort((a, b) => a - b)
const med = phis[Math.floor(phis.length / 2)]

// FIRES vs READINGS. This log kept only the drift moments until the policy changed to
// record every step; the reporting did not follow, so the headline said "N fires" about a
// row count that is mostly quiet readings — overstating the corpus by ~4.5x. The two
// numbers answer different questions and both belong here.
// ERAS. This corpus spans more than one instrument and could not say so until rows
// started carrying grammar_version. The seam that matters is `drifting`: before it
// existed, ONLY drift moments were logged, so every row of that era is a fire and none
// of them can be a non-fire. Pooling the two takes a numerator from one policy and a
// denominator from the other, which is how a 24.8% fire rate got reported as 22%, and
// how fifty rows read as "an interrupt that did not interrupt" when the field had simply
// not been invented yet.
const dated = rows.filter((r) => r.drifting !== undefined && r.drifting !== null)
const undated = rows.filter((r) => r.drifting === undefined || r.drifting === null)
if (undated.length) {
  const cut = dated.length ? dated.map((r) => r.ts).sort()[0] : '?'
  console.log(`\n  TWO ERAS in this corpus — rates are computed on the newer one only`)
  console.log(`    ${undated.length} row(s) predate the \`drifting\` field. In that era only drift`)
  console.log(`    moments were logged, so each is a fire with no denominator beside it.`)
  console.log(`    ${dated.length} row(s) from ${String(cut).slice(0, 10)} onward log every step.`)
  const vs = [...new Set(rows.map((r) => r.grammar_version).filter(Boolean))]
  console.log(`    grammar versions present: ${vs.length ? vs.join(', ') : 'none recorded (older rows)'}`)
}
const fires = dated.filter((r) => r.drifting)
console.log(`\n  drift corpus — ${rows.length} readings across ${runs.size} run(s)`)
console.log(`  ${fires.length} fires in ${dated.length} comparable readings (${(fires.length / Math.max(dated.length, 1) * 100).toFixed(1)}%)\n  ${LOG}\n`)
console.log('  by signal (every reading, fires and holds alike):')
for (const [reason, n] of Object.entries(byReason).sort((a, b) => b[1] - a[1])) {
  const pct = ((n / rows.length) * 100).toFixed(0)
  console.log(`    ${reason.padEnd(22)} ${String(n).padStart(4)}  ${'█'.repeat(Math.round(n / rows.length * 24))} ${pct}%`)
}
console.log(`\n  Φ at fire:  min ${phis[0].toFixed(2)}  median ${med.toFixed(2)}  mean ${(phiSum / rows.length).toFixed(2)}  max ${phis[phis.length - 1].toFixed(2)}`)
console.log(`\n  read: a signal that fires a lot at LOW Φ is a false-alarm suspect —\n  it is flagging drift while the agent has barely moved from ground.\n`)

// ---- the excursion question -------------------------------------------------
//
// goal-drift is the overwhelming majority of everything this instrument has ever fired.
// Before reaching for its threshold, ask whether the grammar already has an answer that
// nobody is using: `parent_goal` exists so a sub-task can be SPELLED rather than collapsed
// into the single goal slot, and `excursion` is the verdict for one. The laserscore
// records it — a state with a parent carries ⊂ — so the corpus can answer this directly.
const parented = rows.filter((r) => typeof r.laserscore === 'string' && r.laserscore.includes('\u2282'))
const drifts = rows.filter((r) => r.reason === 'goal-drift')
const driftsParented = drifts.filter((r) => typeof r.laserscore === 'string' && r.laserscore.includes('\u2282'))
const excursions = rows.filter((r) => r.reason === 'excursion')

console.log('  the excursion question:')
console.log(`    parent_goal spelled     ${parented.length} of ${rows.length} readings (${(parented.length / rows.length * 100).toFixed(1)}%)`)
console.log(`    goal-drift fires        ${drifts.length}, of which ${driftsParented.length} named a parent`)
console.log(`    excursion verdicts      ${excursions.length}`)
if (parented.length / Math.max(rows.length, 1) < 0.05 && drifts.length > 20) {
  console.log('    read: the grammar has a slot for a legitimate sub-task and it is going unused,')
  console.log('    so an excursion has no way to read as anything but drift. That is a USAGE')
  console.log('    finding, not a calibration one — moving the goal_min threshold would trade')
  console.log('    these false alarms for real misses and never touch the cause.')
}
console.log('')

// ---- the labels, where they exist -------------------------------------------
// Until mark_verdict shipped, everything above was a distribution and nothing here was a
// detection rate: how OFTEN each signal fires, never whether it fired on the right thing.
// A signal firing 40% of the time is not a fault and not a virtue — it depends entirely on
// whether those fires were catching anything, which is precisely what nothing recorded.
const OUTCOMES = process.env.LASERBRAIN_OUTCOMES_LOG
  || lbConfig('verdict-outcomes.jsonl')
let labels = []
try {
  labels = readFileSync(OUTCOMES, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
} catch { /* no labels yet — the honest state for a corpus nobody has judged */ }

if (!labels.length) {
  console.log(`  no verdict outcomes recorded yet (${OUTCOMES})`)
  console.log(`  ${fires.length} fires, 0 labelled. Every threshold is therefore tuned on how often`)
  console.log(`  a rule fires and not on whether it was right. Use mark_verdict to label one.\n`)
} else {
  // Joined on (run, step) — the outcomes file never rewrites the corpus it labels.
  const key = (r) => `${r.run}#${r.step}`
  const seen = new Map()
  for (const l of labels) seen.set(key(l), l)   // last label for a step wins
  const perSignal = {}
  let labelled = 0
  for (const r of rows) {
    const l = seen.get(key(r))
    if (!l) continue
    labelled++
    const b = (perSignal[r.reason] ||= { useful: 0, false: 0, unclear: 0 })
    b[l.outcome] = (b[l.outcome] || 0) + 1
  }
  const firesLabelled = rows.filter((r) => r.drifting && seen.has(key(r))).length
  const cov = ((firesLabelled / Math.max(fires.length, 1)) * 100).toFixed(1)
  console.log(`  verdict outcomes — ${firesLabelled} of ${fires.length} FIRES labelled (${cov}%)`)
  if (labelled > firesLabelled) {
    console.log(`  (${labelled - firesLabelled} label(s) sit on readings that never fired — recorded, but`)
    console.log('   they say nothing about whether an interruption was warranted)')
  }
  console.log(`  ${OUTCOMES}\n`)
  if (labelled) {
    console.log('  by signal (useful / false / unclear):')
    for (const [reason, b] of Object.entries(perSignal).sort((a, b2) => (b2[1].useful + b2[1].false) - (a[1].useful + a[1].false))) {
      const n = b.useful + b.false + b.unclear
      const judged = b.useful + b.false
      const rate = judged ? `${((b.useful / judged) * 100).toFixed(0)}% useful` : 'no clear calls'
      console.log(`    ${reason.padEnd(22)} ${b.useful}/${b.false}/${b.unclear}  n=${n}  ${rate}`)
    }
  }
  // The number the whole exercise is for. Self-marked labels are recorded but weaker:
  // an agent grading the instrument that judged it is not an independent reference.
  const selfMarked = labels.filter((l) => l.by && l.agent && l.by === l.agent).length
  if (selfMarked) {
    console.log(`\n  ${selfMarked} of ${labels.length} label(s) were marked by the agent they were about —`)
    console.log(`  recorded, but weaker evidence than an independent call.`)
  }
  // PRECISION, and only precision. d' needs both halves of a detection matrix: hits and
  // false alarms among the FIRES, and misses and correct rejections among the steps that
  // did NOT fire. This corpus can only ever hold the first half, because review_verdicts
  // offers fires to be judged and nothing judges a quiet step. So what is computable here
  // is "when it fired, how often was it right" — not sensitivity, and not d'. Saying it
  // plainly costs nothing; quoting a d' from half a matrix would be inventing a number.
  const useful = Object.values(perSignal).reduce((n, b) => n + b.useful, 0)
  const wrong = Object.values(perSignal).reduce((n, b) => n + b.false, 0)
  if (useful + wrong) {
    console.log(`\n  precision (fired and was right): ${(useful / (useful + wrong) * 100).toFixed(0)}%  — ${useful} of ${useful + wrong} clear calls`)
    console.log('  NOT d-prime: sensitivity needs labels on the steps that did not fire,')
    console.log('  and nothing collects those. This is half a detection matrix, said as half.')
  }
  if (labelled < 30) {
    console.log(`\n  too few to calibrate on. A detection rate on ${labelled} labelled fire(s) is an`)
    console.log(`  anecdote; do not move a threshold on it.`)
  }
  console.log('')
}

if (tailN) {
  console.log(`  last ${Math.min(tailN, rows.length)} readings (judge true catch vs false alarm):`)
  for (const r of rows.slice(-tailN)) {
    console.log(`    ${(r.ts || '').slice(5, 16)}  ${String(r.reason).padEnd(22)} Φ${Number(r.phi).toFixed(2)}  ${String(r.goal || '').slice(0, 48)}`)
  }
  console.log('')
}
