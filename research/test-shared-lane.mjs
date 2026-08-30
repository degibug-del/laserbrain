/**
 * A ground on the SHARED lane survives somebody else's reset_task.
 *
 *     node test-shared-lane.mjs
 *
 * WHY. The lane partition added on 2026-08-05 was correct and did not help, because it is
 * opt-in: "Omit it and you get the shared lane, byte-identical to the old behaviour."
 * Every caller omits it. `session` is an argument an agent has to know to pass, nothing
 * tells one to, and a subagent least of all — it does not know that it is a subagent. So
 * every caller lands in `__shared__` and gets the original defect, which is exactly what
 * happened again on 2026-08-16: a child's reset wiped the parent's ground, and the parent's
 * next check with a BYTE-IDENTICAL goal string came back goal-drift at 0.02, then escalated
 * to `wrong-problem` and told a correctly-working agent to stop.
 *
 * A safety that has to be requested is not a default. This pins the default.
 *
 * Drives the real server over stdio rather than importing it, because the bug lives in how
 * one PROCESS serves many callers — importing the module and calling functions would test a
 * different thing and would have passed all along.
 *
 * THIS TEST CAN FAIL: restore reset_task's body to `drift = freshDrift()` with no suspend
 * and the first assertion goes red at the original 0.02-0.32 band.
 */
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'

const HERE = dirname(fileURLToPath(import.meta.url))
const PARENT = 'Restore the paid laserbrain tiers Group and Pro and rekey the payment links'
const CHILD = 'Sweep the workers directory for every price constant and tier definition'
const OTHER = 'Write the employee handbook and index it in the folder'

let failures = 0
const check = (label, cond, saw) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'}  ${label}${cond || saw === undefined ? '' : `   saw: ${JSON.stringify(saw)}`}`)
  if (!cond) failures++
}

// One server process for the whole run — that is the point.
const srv = spawn('node', [join(HERE, 'mcp-server.mjs')], {
  stdio: ['pipe', 'pipe', 'pipe'],
  // Never the real corpus. A test that appends to drift-log.jsonl would be writing its own
  // fixtures into the calibration the product ships.
  // FULLY ISOLATED. Overriding only the drift log was not enough: the judgment also reads
  // prior-session state from the config tree, so this test's verdict depended on how much
  // real work had happened on this machine that day — it passed once and then escalated
  // past wrong-problem to `abandon` on the next run. LASERBRAIN_HOME relocates both trees
  // at once, which is what makes the result a fact about the code rather than about today.
  env: { ...process.env,
         LASERBRAIN_HOME: mkdtempSync(join(tmpdir(), 'lb-test-')),
         LASERBRAIN_DRIFT_LOG: join(HERE, '.test-shared-lane.jsonl'),
         LASERBRAIN_ARM: 'open',            // never the blind arm: we need to read verdicts
         LASERBRAIN_OFFLINE: '1' },
})
srv.stderr.on('data', () => {})

let buf = ''
const waiters = new Map()
srv.stdout.on('data', (d) => {
  buf += d.toString()
  let i
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim()
    buf = buf.slice(i + 1)
    if (!line) continue
    try {
      const msg = JSON.parse(line)
      const w = waiters.get(msg.id)
      if (w) { waiters.delete(msg.id); w(msg) }
    } catch { /* not our line */ }
  }
})

let nextId = 1
function rpc(method, params) {
  const id = nextId++
  return new Promise((resolve, reject) => {
    waiters.set(id, resolve)
    srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
    setTimeout(() => { if (waiters.delete(id)) reject(new Error(`timeout on ${method}`)) }, 20000)
  })
}

const callTool = async (name, args) => {
  const r = await rpc('tools/call', { name, arguments: args || {} })
  const text = r?.result?.content?.[0]?.text ?? ''
  try { return JSON.parse(text) } catch { return { text } }
}

try {
  await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {},
                            clientInfo: { name: 'test-shared-lane', version: '1' } })

  console.log('\n  a ground on the shared lane survives somebody else\'s reset\n')

  await callTool('check_state', { goal: PARENT, progress: 'advancing', distance: 7 })
  await callTool('reset_task', {})                                  // the CHILD, starting new work
  const child = await callTool('check_state', { goal: CHILD, progress: 'advancing', distance: 5 })
  const back = await callTool('check_state', { goal: PARENT, progress: 'advancing', distance: 6 })

  // WEAK ON PURPOSE, and measured to be: with the fix reverted this assertion still PASSED,
  // because these two goals share enough vocabulary ("tier") to stay above the drift
  // threshold even when compared against the wrong ground. It is kept as a smoke test and
  // is explicitly not the one carrying this file — that is `resumed_ground` below, and the
  // child's own reclaim further down. Both of those went red on the reverted build.
  check("a child's reset does not destroy the parent's ground",
        back.reason !== 'goal-drift', { reason: back.reason, goal_score: back.goal_score })
  check('the parent is told its ground was resumed, not moved silently',
        back.resumed_ground === PARENT, back.resumed_ground)
  check('the child still gets a ground of its own',
        child.reason === 'grounded', child.reason)

  // Or the theft has merely moved one level down.
  const childBack = await callTool('check_state', { goal: CHILD, progress: 'advancing', distance: 4 })
  check('the child reclaims its own ground in turn',
        childBack.reason !== 'goal-drift', childBack.reason)

  // Resume is a comparison, not a threshold: genuinely new work must still ground fresh
  // rather than being handed whichever suspended ground it least mismatches.
  await callTool('reset_task', {})
  const fresh = await callTool('check_state', { goal: OTHER, progress: 'advancing', distance: 8 })
  check('a genuine redirect still grounds fresh, not resumed',
        fresh.reason === 'grounded' && !fresh.resumed_ground,
        { reason: fresh.reason, resumed: fresh.resumed_ground })

  // An explicit session asked for isolation and must still get exactly that.
  await callTool('check_state', { session: 'iso', goal: 'isolated lane task about parsers', progress: 'advancing', distance: 5 })
  await callTool('reset_task', { session: 'iso' })
  const iso = await callTool('check_state', { session: 'iso', goal: 'a completely different isolated job', progress: 'advancing', distance: 5 })
  check('an explicit session still clears only its own lane',
        iso.reason === 'grounded' && !iso.resumed_ground,
        { reason: iso.reason, resumed: iso.resumed_ground })

  console.log(failures
    ? `\n  ${failures} FAILED\n`
    : '\n  PASS — the shared lane is safe by default, not by request.\n')
} catch (e) {
  console.log(`\n  FAILED to drive the server: ${e.message}\n`)
  failures++
} finally {
  srv.kill()
}
process.exit(failures ? 1 : 0)
