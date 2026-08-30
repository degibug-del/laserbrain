/**
 * Does the grammar's version still describe its content?
 *
 * sync-grammar.mjs --check asks whether the four copies are identical, and they were — it
 * passed throughout. check-laserbrain-parity.mjs asks whether the version STRINGS match,
 * and they did. Neither asks whether the version still describes the document, and on
 * 2026-07-28 grammar 1.6.0 came to mean two different files: seven additions went in under
 * one version number, so the canonical copy and the live endpoint both announced 1.6.0 and
 * carried different content.
 *
 * Same failure as everything else this week, one level down. A label agreeing with another
 * label is not a label describing a thing.
 *
 * WHY IT HASHES BYTES AND NOT JSON
 * --------------------------------
 * The first two versions of this gate hashed a re-serialised document, and both failed —
 * not on the grammar, on the serialiser. Python escapes non-ASCII by default where
 * JavaScript does not (340 characters of difference), and Python writes `1.0` where
 * JavaScript writes `1` for the same number. A cross-language content hash of parsed JSON
 * compares serialisers, not content.
 *
 * The file's own lines have no such ambiguity. Every copy is byte-identical because
 * sync-grammar.mjs writes them that way, so bytes are the honest thing to hash.
 */
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { CONTRACT } from './paths.mjs'

const CANON = join(CONTRACT, 'grammar.json')

const raw = readFileSync(CANON, 'utf8')
const g = JSON.parse(raw)

// The version line is excluded so that a content change is what moves the hash; the two
// hash lines are excluded because a hash cannot cover itself.
const SKIP = ['"laserbrain_grammar"', '"content_hash"', '"content_hash_what"']
const bodyHash = (text) => createHash('sha256')
  .update(text.split('\n').filter((l) => !SKIP.some((k) => l.includes(k))).join('\n'))
  .digest('hex').slice(0, 16)

const want = g.content_hash
const got = bodyHash(raw)

if (!want) {
  console.error('\n  FAIL  grammar.json carries no content_hash — its version is unverifiable\n')
  process.exit(1)
}
if (want !== got) {
  console.error(`\n  FAIL  grammar ${g.laserbrain_grammar} no longer describes its own content\n`)
  console.error(`    recorded ${want}`)
  console.error(`    actual   ${got}`)
  console.error('\n  The content changed and the version did not. Bump laserbrain_grammar,')
  console.error('  regenerate content_hash, then: node scripts/sync-grammar.mjs\n')
  process.exit(1)
}
console.log(`  ok    grammar ${g.laserbrain_grammar} matches its content (${got})`)
