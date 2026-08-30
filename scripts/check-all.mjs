/**
 * Every gate this repository can run on its own.
 *
 * These lived in phronesis-world, a private repository, which meant a clone of laserbrain
 * got the code and none of the checks. Every divergence found on 2026-08-30 — four copies of
 * mcp-server.mjs, grammar 1.21.0 naming two documents, LASERBRAIN_HOME resolving two ways,
 * a vendored copy 146 lines behind, dist four renames stale, two transports 17 tools apart —
 * was found by a check or by counting, never by reading the code.
 *
 * Run:  node scripts/check-all.mjs
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const GATES = [
  ['check-grammar-version', 'the grammar matches its own content hash'],
  ['check-normaliser-parity', 'one normaliser across every implementation'],
  ['check-tool-parity', 'the stdio and hosted transports expose what the contract says'],
]

let failed = 0
for (const [g, what] of GATES) {
  const r = spawnSync('node', [join(HERE, `${g}.mjs`)], { encoding: 'utf8' })
  const ok = r.status === 0
  if (!ok) failed++
  const line = (r.stdout + r.stderr).split('\n').find((l) => /^\s*(ok|FAIL)/.test(l)) || ''
  console.log(`  ${ok ? 'ok  ' : 'FAIL'}  ${g.padEnd(26)} ${line.trim().replace(/^(ok|FAIL)\s+/, '') || what}`)
}
console.log(failed ? `\n  ${failed} of ${GATES.length} failed\n` : `\n  ${GATES.length} gates pass\n`)
process.exit(failed ? 1 : 0)
