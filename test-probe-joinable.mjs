/**
 * A drift reading must say which arm it belongs to.
 *
 *     node test-probe-joinable.mjs
 *
 * WHY. The blind probe assigns arms into blind-arms.jsonl keyed by `unit`; readings go to
 * drift-log.jsonl keyed by `run`. On 2026-08-17 the two shared NOT ONE FIELD and no `unit`
 * had ever appeared as a `run` — so a finished probe would hold its assignments and its
 * outcomes in separate files with nothing connecting them, and the comparison it is
 * pre-registered to make would be uncomputable. That would have surfaced at analysis time,
 * after 40 units of real work.
 *
 * It had already been found once, on 2026-08-10, and "fixed" by putting `arm` in the
 * check_state RESPONSE — which an agent reads and discards. Nothing wrote it down. This
 * pins the part that survives: the row on disk.
 */
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { mkdtempSync, readFileSync, existsSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'

const HERE = dirname(fileURLToPath(import.meta.url))
const HOME = mkdtempSync(join(tmpdir(), 'lb-probe-'))
const LOG = join(HOME, 'drift.jsonl')
let failures = 0
const check = (l, c, saw) => {
  console.log(`  ${c ? 'ok  ' : 'FAIL'}  ${l}${c || saw === undefined ? '' : `   saw: ${JSON.stringify(saw)}`}`)
  if (!c) failures++
}

// Plant an arm assignment where the server reads it.
mkdirSync(join(HOME, '.claude', 'laserbrain'), { recursive: true })
writeFileSync(join(HOME, '.claude', 'laserbrain', 'current-arm.json'),
  JSON.stringify({ session: 's1', unit: 's1#7', segment: 7, blind: 'sighted', at: '2026-08-17T00:00:00' }))

const srv = spawn('node', [join(HERE, 'mcp-server.mjs')], {
  stdio: ['pipe', 'pipe', 'pipe'],
  env: { ...process.env, HOME, LASERBRAIN_HOME: HOME, LASERBRAIN_DRIFT_LOG: LOG,
         LASERBRAIN_ARM: 'open', LASERBRAIN_OFFLINE: '1' },
})
srv.stderr.on('data', () => {})
let buf = ''; const waiters = new Map()
srv.stdout.on('data', (d) => {
  buf += d.toString(); let i
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1)
    if (!line) continue
    try { const m = JSON.parse(line); const w = waiters.get(m.id); if (w) { waiters.delete(m.id); w(m) } } catch {}
  }
})
let id = 1
const rpc = (method, params) => new Promise((res, rej) => {
  const n = id++; waiters.set(n, res)
  srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: n, method, params }) + '\n')
  setTimeout(() => { if (waiters.delete(n)) rej(new Error('timeout')) }, 20000)
})

try {
  await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 't', version: '1' } })
  await rpc('tools/call', { name: 'check_state', arguments: { goal: 'ship the parser and the benchmark', progress: 'advancing', distance: 5 } })
  await new Promise(r => setTimeout(r, 400))   // the log is fire-and-forget

  check('a drift row was written', existsSync(LOG))
  const rows = existsSync(LOG) ? readFileSync(LOG, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : []
  check('at least one reading', rows.length > 0, rows.length)
  if (rows.length) {
    const r = rows[rows.length - 1]
    check('the reading carries its ARM', r.arm === 'sighted', r.arm)
    check('the reading carries its UNIT', r.unit === 's1#7', r.unit)
    check('so a reading is self-describing — no join needed',
          Boolean(r.arm) && Boolean(r.unit) && Boolean(r.run))
  }
  console.log(failures ? `\n  ${failures} FAILED\n` : '\n  PASS — every reading names its own arm.\n')
} catch (e) { console.log(`\n  FAILED to drive the server: ${e.message}\n`); failures++ }
finally { srv.kill() }
process.exit(failures ? 1 : 0)
