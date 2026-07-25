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

const LOG = process.env.LASERBRAIN_DRIFT_LOG || join(homedir(), '.config', 'laserbrain', 'drift-log.jsonl')
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

console.log(`\n  drift corpus — ${rows.length} fires across ${runs.size} run(s)\n  ${LOG}\n`)
console.log('  by signal:')
for (const [reason, n] of Object.entries(byReason).sort((a, b) => b[1] - a[1])) {
  const pct = ((n / rows.length) * 100).toFixed(0)
  console.log(`    ${reason.padEnd(22)} ${String(n).padStart(4)}  ${'█'.repeat(Math.round(n / rows.length * 24))} ${pct}%`)
}
console.log(`\n  Φ at fire:  min ${phis[0].toFixed(2)}  median ${med.toFixed(2)}  mean ${(phiSum / rows.length).toFixed(2)}  max ${phis[phis.length - 1].toFixed(2)}`)
console.log(`\n  read: a signal that fires a lot at LOW Φ is a false-alarm suspect —\n  it is flagging drift while the agent has barely moved from ground.\n`)

if (tailN) {
  console.log(`  last ${Math.min(tailN, rows.length)} fires (judge true catch vs false alarm):`)
  for (const r of rows.slice(-tailN)) {
    console.log(`    ${(r.ts || '').slice(5, 16)}  ${String(r.reason).padEnd(22)} Φ${Number(r.phi).toFixed(2)}  ${String(r.goal || '').slice(0, 48)}`)
  }
  console.log('')
}
