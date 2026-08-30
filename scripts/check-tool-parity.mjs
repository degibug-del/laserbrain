/**
 * Do the two laserbrain transports expose the tools they are supposed to?
 *
 * WHY THIS EXISTS. The stdio server and the hosted Worker are separate implementations with
 * separately hand-maintained tool lists. The stdio server declares 32 tools in one array;
 * index.ts hand-writes 15 `registerTool` calls. Nothing compared them, and the 17-tool gap
 * was found on 2026-08-30 by counting the tools in an agent's own context, not by any check.
 *
 * Two laserbrains under one name and one version, with no fence between them, is the same
 * shape as every other divergence this repo has recorded: four copies of mcp-server.mjs,
 * grammar 1.21.0 naming two different documents, LASERBRAIN_HOME resolving to two paths.
 *
 * THE CONTRACT is laserbrain/json/tools.json:
 *   universal   must exist on BOTH transports. A difference is a bug.
 *   local_only  cannot run in a Worker — each needs a filesystem or a Python runtime, and
 *               each carries the reason, so the absence is stated rather than merely true.
 *
 * This checks the LIVE hosted server, not the source, because what a source registers and
 * what a deployed Worker serves are different claims. It also checks the stdio server by
 * driving it over stdin the way a host would.
 *
 * Run:  node scripts/check-tool-parity.mjs
 *       node scripts/check-tool-parity.mjs --offline   (skip the hosted probe)
 */
import { readFileSync, existsSync } from 'node:fs'
import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { CONTRACT, SERVER } from './paths.mjs'

const offline = process.argv.includes('--offline')
const HOST = process.env.LASERBRAIN_API || 'https://api.phronesis.world'

const contractPath = join(CONTRACT, 'tools.json')
if (!existsSync(contractPath)) {
  console.error(`\n  FAIL  no tool contract at ${contractPath}\n`)
  process.exit(1)
}
const spec = JSON.parse(readFileSync(contractPath, 'utf8'))
const universal = new Set(spec.universal.tools)
const localOnly = new Set(Object.keys(spec.local_only.tools))
const problems = []

/* ── the stdio server, driven the way a host drives it ─────────────────────────── */
const stdioTools = await new Promise((resolve) => {
  const p = spawn('node', [join(SERVER, 'mcp-server.mjs')], { stdio: ['pipe', 'pipe', 'ignore'] })
  let out = ''
  const t = setTimeout(() => { p.kill(); resolve(null) }, 15000)
  p.stdout.on('data', (d) => {
    out += d
    for (const line of out.split('\n')) {
      if (!line.startsWith('{')) continue
      try {
        const m = JSON.parse(line)
        if (m.id === 2 && m.result?.tools) {
          clearTimeout(t); p.kill()
          resolve(m.result.tools.map((x) => x.name))
        }
      } catch { /* partial line */ }
    }
  })
  p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize',
    params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'gate', version: '0' } } }) + '\n')
  p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} }) + '\n')
})

if (!stdioTools) {
  problems.push('the stdio server did not answer tools/list within 15s')
} else {
  const have = new Set(stdioTools)
  const expected = new Set([...universal, ...localOnly])
  for (const t of expected) if (!have.has(t)) problems.push(`stdio is MISSING ${t}`)
  for (const t of have) if (!expected.has(t)) problems.push(`stdio serves ${t}, which the contract does not list`)
}

/* ── the hosted Worker, live ───────────────────────────────────────────────────── */
let hostedTools = null
if (!offline) {
  try {
    const init = await fetch(`${HOST}/mcp`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream',
                 'user-agent': 'laserbrain-gate/1' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize',
        params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'gate', version: '0' } } }),
    })
    const sid = init.headers.get('mcp-session-id')
    const res = await fetch(`${HOST}/mcp`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream',
                 'mcp-session-id': sid, 'user-agent': 'laserbrain-gate/1' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} }),
    })
    const text = await res.text()
    const line = text.split('\n').find((l) => l.startsWith('data: '))
    hostedTools = JSON.parse(line.slice(6)).result.tools.map((x) => x.name)
  } catch (e) {
    problems.push(`the hosted server could not be reached: ${e.message}`)
  }
}

if (hostedTools) {
  const have = new Set(hostedTools)
  for (const t of universal) if (!have.has(t)) problems.push(`hosted is MISSING ${t}, which the contract calls universal`)
  for (const t of have) {
    if (universal.has(t)) continue
    if (localOnly.has(t)) problems.push(`hosted serves ${t}, which the contract calls local-only`)
    else problems.push(`hosted serves ${t}, which the contract does not list`)
  }
}

if (problems.length) {
  console.error('\n  FAIL  the transports do not match json/tools.json\n')
  for (const p of problems) console.error(`      ✗ ${p}`)
  console.error('\n  Either the tool moved and the contract should follow, or a transport drifted.')
  console.error('  Fix laserbrain/json/tools.json, or the server that disagrees with it.\n')
  process.exit(1)
}

const s = stdioTools ? `${stdioTools.length} stdio` : 'stdio skipped'
const h = hostedTools ? `${hostedTools.length} hosted` : 'hosted skipped'
console.log(`  ok    tool parity — ${s}, ${h}, ${universal.size} universal + ${localOnly.size} local-only`)
