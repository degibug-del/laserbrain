/**
 * One normaliser. Six files. This is what makes that true.
 *
 * The 30 stopwords and the stem rule are the atom of laserbrain — every laserscore,
 * every Φ, every verdict is downstream of them. On 2026-07-27 they existed as six
 * independent hand-written copies across three languages, and they were identical:
 * all 30 words, all six files. Identical by attention, not by construction.
 *
 * Every divergence found that day lived in exactly this kind of seam — the Worker
 * missing laserscore, the SDK violating its own precondition, field.py pointing at a
 * localhost nobody else runs, the site calling verdicts "modes". Five for five.
 *
 * grammar.json now carries the normaliser and is the source. This reads it, reads all
 * six implementations, and fails if any of them has drifted. A copy that cannot be
 * found is a failure too — a file renamed out of this list is exactly how a seventh
 * copy would start.
 */
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { CONTRACT, RESEARCH, SDK, SERVER } from './paths.mjs'

// The canonical grammar. In the site repository this read the Worker's bundled copy;
// here the canonical one is json/grammar.json, which that copy is synced from.
const GRAMMAR = join(CONTRACT, 'grammar.json')

// Each copy, and how to pull the word set out of it. Deliberately per-file rather than
// one clever regex: the languages spell a set three different ways, and a pattern loose
// enough to match all of them is loose enough to match the wrong thing.
// Only the copies that still DECLARE a stopword list. drift.ts and mcp-server.mjs read
// theirs out of grammar.json as of 2026-07-27, so there is no literal left to compare and
// nothing for them to drift from — the thing this gate was built to catch is now
// structurally impossible for those two. They are covered by
// check-normaliser-behaviour.mjs, which asks the better question anyway: not "do they
// declare the same list" but "do they compute the same answer".
//
// The three research scripts still carry their own literals, so they still need this.
const COPIES = [
  { name: 'SDK  laserbrain/__init__.py', path: join(SDK, 'laserbrain/__init__.py'), re: /_FALLBACK_STOP = \{([^}]+)\}/ },
  { name: 'research  m1.py', path: join(RESEARCH, 'm1.py'), re: /\bSTOP = \{([^}]+)\}/ },
  { name: 'research  multiagent.py', path: join(RESEARCH, 'multiagent.py'), re: /\bSTOP = \{([^}]+)\}/ },
  { name: 'research  retest.py', path: join(RESEARCH, 'retest.py'), re: /\bSTOP = \{([^}]+)\}/ },
  { name: 'server  mcp-server.mjs (offline floor)', path: join(SERVER, 'mcp-server.mjs'), re: /stopwords: \[([^\]]+)\]/ },
]

const problems = []
const seen = []

if (!existsSync(GRAMMAR)) {
  console.error(`\n  FAIL  ${GRAMMAR} is missing — the source of the normaliser is gone\n`)
  process.exit(1)
}
const grammar = JSON.parse(readFileSync(GRAMMAR, 'utf8'))
const source = grammar.normalizer
if (!source?.stopwords?.length) {
  console.error('\n  FAIL  grammar.json carries no normalizer — it is meant to be the source\n')
  process.exit(1)
}
const want = new Set(source.stopwords)

for (const c of COPIES) {
  if (!existsSync(c.path)) {
    problems.push(`${c.name}: file not found at ${c.path} — renamed, moved, or a copy this list has lost track of`)
    continue
  }
  const body = readFileSync(c.path, 'utf8')
  const m = body.match(c.re)
  if (!m) {
    problems.push(`${c.name}: could not find its stopword set — the shape changed, so this gate stopped watching it`)
    continue
  }
  const got = new Set([...m[1].matchAll(/['"]([a-z]+)['"]/g)].map((x) => x[1]))
  const extra = [...got].filter((w) => !want.has(w))
  const missing = [...want].filter((w) => !got.has(w))
  if (extra.length || missing.length) {
    problems.push(`${c.name}: differs from grammar ${grammar.laserbrain_grammar}` +
      (extra.length ? ` · has ${extra.join(', ')}` : '') +
      (missing.length ? ` · lacks ${missing.join(', ')}` : ''))
  }
  // The stem rule travels with the words; a matching vocabulary stemmed differently is
  // still a different normaliser.
  if (source.stem_pattern && !body.includes(source.stem_pattern.replace(/\$$/, ''))) {
    problems.push(`${c.name}: stem rule does not match grammar's ${source.stem_pattern}`)
  }
  seen.push(c.name)
}

if (problems.length) {
  console.error('\n  FAIL  the normaliser has drifted between copies\n')
  for (const p of problems) console.error(`    ${p}`)
  console.error(`\n  grammar.json is the source. Change it there, then the copies — never the other way.\n`)
  process.exit(1)
}

console.log(`  ok    one normaliser — ${want.size} stopwords and the stem rule agree across ${seen.length} implementations in 3 languages`)
