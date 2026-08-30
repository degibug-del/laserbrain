/**
 * `wrong-problem` may only COMMAND when something independent agrees.
 *
 *     node test-judgment-corroboration.mjs
 *
 * WHY. On 2026-08-16 this verdict told an agent "You are not solving what you set out to
 * solve" while it was solving exactly that. A subagent's reset_task had destroyed the
 * parent's ground, so the parent's byte-identical goal string scored 0.02 five times over.
 * Every input to the rule was true and every one was an artifact of the fault.
 *
 * The asymmetry is the whole point: goalDrifts, regrounds and pace are all computed by the
 * instrument from the agent's own words, so one fault can satisfy all three at once.
 * `corroborated` counts checks backed by output something INDEPENDENT produced — the one
 * signal laserbrain cannot manufacture. Diego's call: a verdict that can halt an agent has
 * to pass it.
 *
 * Uncorroborated, the finding is still reported. What changes is that it asks the agent to
 * check its ground rather than telling it to abandon its work.
 */
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'

const HERE = dirname(fileURLToPath(import.meta.url))
let failures = 0
const check = (label, cond, saw) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'}  ${label}${cond || saw === undefined ? '' : `   saw: ${JSON.stringify(saw).slice(0, 220)}`}`)
  if (!cond) failures++
}

const srv = spawn('node', [join(HERE, 'mcp-server.mjs')], {
  stdio: ['pipe', 'pipe', 'pipe'],
  // FULLY ISOLATED. Overriding only the drift log was not enough: the judgment also reads
  // prior-session state from the config tree, so this test's verdict depended on how much
  // real work had happened on this machine that day — it passed once and then escalated
  // past wrong-problem to `abandon` on the next run. LASERBRAIN_HOME relocates both trees
  // at once, which is what makes the result a fact about the code rather than about today.
  env: { ...process.env,
         LASERBRAIN_HOME: mkdtempSync(join(tmpdir(), 'lb-test-')),
         LASERBRAIN_DRIFT_LOG: join(HERE, '.test-judgment.jsonl'),
         LASERBRAIN_ARM: 'open',
         LASERBRAIN_OFFLINE: '1' },
})
srv.stderr.on('data', () => {})

let buf = ''
const waiters = new Map()
srv.stdout.on('data', (d) => {
  buf += d.toString()
  let i
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1)
    if (!line) continue
    try {
      const m = JSON.parse(line)
      const w = waiters.get(m.id)
      if (w) { waiters.delete(m.id); w(m) }
    } catch { /* not ours */ }
  }
})
let nextId = 1
const rpc = (method, params) => new Promise((res, rej) => {
  const id = nextId++
  waiters.set(id, res)
  srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
  setTimeout(() => { if (waiters.delete(id)) rej(new Error(`timeout ${method}`)) }, 20000)
})
const call = async (name, args) => {
  const r = await rpc('tools/call', { name, arguments: args || {} })
  const t = r?.result?.content?.[0]?.text ?? ''
  try { return JSON.parse(t) } catch { return { text: t } }
}

// Distinct subjects with no shared vocabulary, so overlap against the ground collapses and
// the goal-drift counter climbs. Distance never falls, which is what pace <= 0 needs.
const GROUND = 'restore the paid billing tiers and rekey the payment links'
const AWAY = [
  'compile the kernel scheduler benchmark harness',
  'photograph migrating herons beside the estuary',
  'translate medieval lute tablature into modern notation',
  'repair the greenhouse irrigation timer',
  'catalogue mineral samples from the quarry floor',
  'rehearse the string quartet second movement',
]

try {
  await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {},
                            clientInfo: { name: 'test-judgment', version: '1' } })

  console.log('\n  wrong-problem may only command with corroboration\n')

  await call('check_state', { goal: GROUND, progress: 'advancing', distance: 5 })
  let last = null
  for (const g of AWAY) {
    last = await call('check_state', { goal: g, progress: 'advancing', distance: 5 })
    if (last?.judgment?.verdict === 'wrong-problem') break
  }

  const j = last?.judgment
  check('the pattern is still detected and named', j?.verdict === 'wrong-problem',
        { verdict: j?.verdict, reason: last?.reason })

  if (j?.verdict === 'wrong-problem') {
    // Nothing in this run was corroborated — no command was ever run, nothing independent
    // produced output. So it must ask, not instruct.
    check('uncorroborated, it does NOT tell the agent it is not solving its problem',
          !/not solving what you set out to solve/i.test(j.counsel || ''), j.counsel)
    check('uncorroborated, it asks the agent to check its ground first',
          /check the ground/i.test(j.counsel || ''), j.counsel)
    check('and it says why the reading might be about the instrument',
          /ground having moved underneath you/i.test(j.because || ''), j.because)
    check('the finding itself is not suppressed',
          /failed its overlap check/i.test(j.because || ''), j.because)
  }

  console.log(failures
    ? `\n  ${failures} FAILED\n`
    : '\n  PASS — it reports without corroboration, and only commands with it.\n')
} catch (e) {
  console.log(`\n  FAILED to drive the server: ${e.message}\n`)
  failures++
} finally {
  srv.kill()
}
process.exit(failures ? 1 : 0)
