/**
 * Does the stdio server agree with the Python package?
 *
 * This server had no parity suite for its whole life, while being the implementation its
 * own authors ran every day. The TypeScript package is checked on 276 field comparisons;
 * this was checked on nothing.
 *
 * Driven over stdio exactly as an agent host drives it: initialize, then one check_state
 * per step, comparing against ../../json/drift-vectors.json — generated FROM Python, which
 * is the reference.
 *
 * HOME IS REDIRECTED TO A SCRATCH DIRECTORY. The server reads the blind-probe arm from
 * ~/.claude/laserbrain/current-arm.json and inherits whatever the live agent is in; under a
 * blind arm it withholds every verdict and this suite would compare nothing while passing.
 * The scratch HOME also keeps the run from writing into the live corpus — the probe is
 * pre-registered and a test must not perturb it.
 *
 *   node test/parity.mjs
 */
import { spawn } from 'node:child_process'
import { readFileSync, mkdtempSync } from 'node:fs'
// fileURLToPath, not .pathname: on Windows a file:// URL's pathname is '/C:/...'
// and every join off it resolves to nothing. Reported 2026-08-25.
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const vectors = JSON.parse(readFileSync(join(HERE, '../../json/drift-vectors.json'), 'utf8'))
const HOME = mkdtempSync(join(tmpdir(), 'lb-parity-'))

function runSequence(steps) {
  return new Promise((resolve, reject) => {
    const srv = spawn('node', [join(HERE, '../mcp-server.mjs')],
                      { env: { ...process.env, HOME }, stdio: ['pipe', 'pipe', 'ignore'] })
    const out = []
    srv.stdout.on('data', (d) => out.push(d.toString()))
    srv.on('close', () => {
      const verdicts = []
      for (const line of out.join('').split('\n')) {
        if (!line.trim()) continue
        let msg; try { msg = JSON.parse(line) } catch { continue }
        const c = msg?.result?.content?.[0]?.text
        if (!c) continue
        try { verdicts.push(JSON.parse(c)) } catch { /* not a verdict */ }
      }
      resolve(verdicts)
    })
    srv.on('error', reject)
    srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize',
      params: { protocolVersion: '2024-11-05', capabilities: {},
                clientInfo: { name: 'parity', version: '1' } } }) + '\n')
    steps.forEach((s, i) => srv.stdin.write(JSON.stringify({
      jsonrpc: '2.0', id: 10 + i, method: 'tools/call',
      params: { name: 'check_state', arguments: s.in } }) + '\n'))
    srv.stdin.end()
  })
}

const bad = []
let compared = 0
for (const vec of vectors.vectors) {
  const got = await runSequence(vec.steps)
  vec.steps.forEach((s, i) => {
    const g = got[i]
    if (!g) { bad.push(`seq ${vec.seq} step ${i}: no verdict returned`); return }
    if (g.blind) { bad.push(`seq ${vec.seq} step ${i}: blind — arm leaked into the test`); return }
    for (const k of ['reason', 'drifting']) {
      compared++
      if (JSON.stringify(g[k]) !== JSON.stringify(s.out[k]))
        bad.push(`seq ${vec.seq} step ${i} · ${k}: want ${JSON.stringify(s.out[k])}, got ${JSON.stringify(g[k])}`)
    }
  })
}

console.log(`\n  stdio server vs laserbrain ${vectors.sdk_version} (Python)`)
console.log(`  ${vectors.vectors.length} sequences · ${compared} comparisons\n`)
if (bad.length) {
  bad.slice(0, 12).forEach((b) => console.error('  MISMATCH ' + b))
  console.error(`\n  FAIL — ${bad.length} mismatches.\n`)
  process.exit(1)
}
console.log('  PASS — reason and drifting match Python on every step.\n')
