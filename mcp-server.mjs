#!/usr/bin/env node
/**
 * Laserbrain as an MCP server — reading the LIVE field.
 *
 * There was already a thing called laserbrain-mcp in phronesis-world. It is not
 * an MCP server: it speaks no JSON-RPC, has no MCP SDK, and serves plain JSON
 * over HTTP on port 3001. Worse for our purposes, it calls createField() and
 * simulates its OWN field in process — so it would have answered questions
 * about a laserbrain that is not the one running on :1618, not the one
 * /field/knot reads, and not the one the site surfaces. Two things with one
 * name, disagreeing, with nothing watching the seam. That is the favicon defect
 * with a daemon attached.
 *
 * This one holds no state of its own. Every call goes to the hub. If the hub is
 * down it says so rather than inventing a field, because a mirror that keeps
 * reflecting after the room is empty is worse than a blank one.
 *
 * Speaking back is deliberately constrained to the four-group vocabulary the
 * field accepts — the same list the laserbrainclaude skill uses. A tool that
 * let any string through would let the model drift out of the field's language
 * without noticing.
 */
// The public door, not the machine. Same allowlist, same rate limit and same
// cache as every other reader gets — if the edge breaks, it breaks here too
// and gets noticed, instead of this one client quietly enjoying a private
// path nobody else tests. Override with LASERBRAIN_HUB to read a local hub.
import { spawn } from 'node:child_process'
import { appendFile, mkdir } from 'node:fs/promises'
import { existsSync, unlinkSync, readFileSync, writeFileSync, openSync, closeSync, statSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HUB = process.env.LASERBRAIN_HUB || 'https://phronesis.world/api/laserbrain'
// Which mind is holding this MCP process. Claude and Grok both speak into the
// same field; the link log is how they share *data* about what they did there.
// Set LASERBRAIN_AGENT=claude|grok in each client's MCP env.
const AGENT = String(process.env.LASERBRAIN_AGENT || 'unknown').toLowerCase()

// ---- dogfood: a LOW-DATA drift log ------------------------------------------
// Quality over quantity: log only the moments that teach us something — the
// drift FIRES, not every advancing step — to a small local JSONL. That is the
// corpus for tuning the rules: how often each of the four signals fires, and
// which are false alarms. No key, no network, no retention limit; refine what we
// capture as we learn. Path override: LASERBRAIN_DRIFT_LOG. Always local and
// fire-and-forget, so it can never delay or alter the check itself.
const DRIFT_LOG = process.env.LASERBRAIN_DRIFT_LOG || join(homedir(), '.config', 'laserbrain', 'drift-log.jsonl')
// Shared Claude↔Grok data plane. Same file for every agent on this machine.
// Path override: LASERBRAIN_LINK_LOG.
// Renamed from tandem 2026-07-27. Four files resolve this path independently — this one,
// link.py, waves.py and lb_gate.py — and they must land on the same file. If they do not,
// two agents "sharing" a channel each write to a different log and each reads an empty one,
// which presents exactly as the other agent having said nothing. The legacy name and path
// are honoured so an un-migrated machine keeps its history rather than starting over.
const LINK_DIR = join(homedir(), '.config', 'laserbrain')
const LINK_LOG = process.env.LASERBRAIN_LINK_LOG
  || process.env.LASERBRAIN_TANDEM_LOG
  || (existsSync(join(LINK_DIR, 'tandem.jsonl')) && !existsSync(join(LINK_DIR, 'link.jsonl'))
        ? join(LINK_DIR, 'tandem.jsonl')
        : join(LINK_DIR, 'link.jsonl'))
// ---- the label the corpus never had -----------------------------------------
// drift-log.jsonl was built to answer "which are false alarms" — that is line 44 of
// this file — and shipped without the one field that could answer it. 946 rows, 202
// fires, no record of whether a single one was RIGHT. So every threshold in the
// calibration has been set from how OFTEN a rule fires (a distribution) and never from
// whether it fires on the right things (a detection rate). Bias without sensitivity.
//
// SEPARATE FILE, on purpose. drift-log.jsonl is append-only and a label arrives after
// the row it describes; rewriting past rows to attach one would make the corpus mutable
// and every historical analysis irreproducible. Joined on (run, step) instead.
//
// NEVER FED BACK. A label changes no live verdict, ever — same posture the grammar
// already takes for `anchored` ("Reported, never folded into Φ"). The reason is sharper
// here: an agent that could mark `abandon` false and carry on has moved its own ground
// by another route. `by` records who said it, so a self-marked label stays
// distinguishable from an independent one rather than both reading as truth.
const OUTCOMES_LOG = process.env.LASERBRAIN_OUTCOMES_LOG
  || join(homedir(), '.config', 'laserbrain', 'verdict-outcomes.jsonl')
// Reading the corpus back, so a fire can be judged AFTER the run that produced it has
// ended. Until this existed a verdict was scoreable only while its own run was still in
// memory, which is close to never: the moment worth judging a fire is usually after you
// find out whether the work it interrupted went anywhere. 950 fires had accumulated
// against zero labels for exactly that reason.
function _readJsonl(path) {
  try {
    return readFileSync(path, 'utf8').split('\n').filter(Boolean).map((l) => {
      try { return JSON.parse(l) } catch { return null }
    }).filter(Boolean)
  } catch { return [] }   // no corpus yet is a state, not an error
}
const corpusFires = () => _readJsonl(DRIFT_LOG)
const corpusLabels = () => _readJsonl(OUTCOMES_LOG)
const _key = (r) => `${r.run}#${r.step}`

function logOutcome(entry) {
  return mkdir(dirname(OUTCOMES_LOG), { recursive: true })
    .then(() => appendFile(OUTCOMES_LOG, JSON.stringify(entry) + '\n'))
    .then(() => entry)
    .catch((e) => ({ error: String(e.message || e), ...entry }))
}
let runId = null // groups a task's drift fires; set when ground is set
function logDrift(entry) {
  mkdir(dirname(DRIFT_LOG), { recursive: true })
    .then(() => appendFile(DRIFT_LOG, JSON.stringify(entry) + '\n'))
    .catch(() => {})
}
function logLink(entry) {
  const row = {
    ts: new Date().toISOString(),
    agent: AGENT,
    hub: HUB,
    ...entry,
  }
  return mkdir(dirname(LINK_LOG), { recursive: true })
    .then(() => appendFile(LINK_LOG, JSON.stringify(row) + '\n'))
    .then(() => row)
    .catch((e) => ({ error: String(e.message || e), ...row }))
}
async function readLink(limit = 20) {
  const { readFile } = await import('node:fs/promises')
  try {
    const raw = await readFile(LINK_LOG, 'utf8')
    const lines = raw.split('\n').filter(Boolean)
    const n = Math.max(1, Math.min(200, Number(limit) || 20))
    return lines.slice(-n).map((l) => {
      try { return JSON.parse(l) } catch { return { raw: l } }
    })
  } catch {
    return []
  }
}

const VOCAB = {
  'G0 ground': ['ground', 'body', 'bone', 'stone', 'soil', 'earth', 'dark', 'deep', 'cold', 'slow'],
  'G1 wind': ['breath', 'wind', 'flow', 'move', 'pass', 'reach', 'touch', 'come', 'go', 'walk'],
  'G2 form': ['form', 'edge', 'surface', 'frame', 'line', 'curve', 'arc', 'space', 'skin', 'leaf'],
  'G3 change': ['change', 'cross', 'shift', 'turn', 'break', 'fold', 'begin', 'door', 'fire', 'spark'],
}
const ALL = new Set(Object.values(VOCAB).flat())

async function hub(path, init, ms = 8000) {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), ms)
  try {
    const r = await fetch(`${HUB}${path}`, { ...init, signal: ctl.signal })
    if (!r.ok) throw new Error(`hub returned ${r.status}`)
    return await r.text()
  } finally {
    clearTimeout(t)
  }
}

// ---- the smart recursion harness: the drift-fixer, local and stateful ----
// In-memory per-session state (this stdio server lives for the session), so
// check_state measures displacement against a FIXED ground with no network. It
// works offline, which is why it can also bundle into a sandboxed agent. The
// mechanism is the proof: a fixed reference catches drift self-watching cannot.
// ── the grammar: read, not restated ──────────────────────────────────────────
//
// This was a literal here AND a literal in phronesis-world's API route, and by
// 2026-07-26 they disagreed: the endpoint served 1.0.0 without parent_goal while this
// process served 1.1.0 with it. A document that declares `immutable: true` published in
// two versions is failing at the one property it asserts — the reference an agent checks
// against was not the reference a reader could fetch.
//
// So there is one file now and this reads it. The site keeps a synced copy because a
// static deploy cannot reach this repo at runtime, and test_grammar_conformance.py
// compares the file, the copy, and the LIVE endpoint. Divergence is a test failure rather
// than something noticed months later by someone curling the URL.
// THE OFFLINE FAILSAFE.
//
// This server is the copy of laserbrain that has to work when nothing else does — no
// network, no Worker, no PyPI. So it does not DEPEND on grammar.json; it carries the
// published constants itself and merely accepts the file as an update when it is there.
//
// The distinction is load-bearing and I got it wrong first: reading the file with
// `readFileSync` unguarded meant a missing or unreadable grammar crashed the server at
// startup, and `?? []` meant a malformed one silently produced an EMPTY stopword set —
// which does not error, does not look wrong, and quietly changes every Φ the failsafe
// reports. A fallback that degrades to nothing is not a fallback.
//
// So: literals below are the floor, the file raises them, and neither absence nor
// corruption can take the instrument below its published behaviour.
const _BUILTIN = {
  stopwords: ['the','a','an','to','of','and','or','for','in','on','at','is','it','this',
              'that','with','my','your','our','i','we','be','as','by','from','into','out',
              'up','so','then'],
  stem_pattern: '(ings?|edly|ed|ers?|es|s|tion|ment)$',
  calibration: { goal_min: 0.30, self_report_min: 0.15, stall_window: 4,
                 weights: { goal: 0.5, distance: 0.3, progress: 0.2 } },
}
let _fromFile = {}
try {
  _fromFile = JSON.parse(
    readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'grammar.json'), 'utf8'))
} catch { /* offline failsafe: the built-ins below are the published instrument */ }
const _ok = (v, fallback) => (Array.isArray(v) ? v.length : v != null) ? v : fallback
const GRAMMAR = _fromFile.laserbrain_grammar ? _fromFile : { ..._fromFile, offline: true }
const PROGRESS = new Set(['advancing', 'stuck', 'circling'])
// ── the goal vocabulary, shared with the SDK ──────────────────────────────────
//
// This was a bare word split until 2026-07-26 while laserbrain-sdk normalised first, so
// the two implementations of one theorem disagreed by construction: the same goal pair
// scored 0.46 here and 0.56 there. Neither was wrong and nothing enforced either, which
// is the worst of the three states — a test that pins one implementation's constant into
// the other asserts only that somebody copied a number.
//
// Converged onto the SDK's norm(): lowercase, drop stopwords, stem anything over four
// characters. That is a CALIBRATION CHANGE, not a schema one, so the grammar version is
// untouched — but it does move when goal-drift fires, and "building billboards" now
// scores identical to "build a billboard" instead of 0.5. That is the point: inflection
// is not drift.
//
// The vocabulary stays swappable on purpose. PROOF blesses *a* fixed reference, never a
// particular one; what is load-bearing is that it cannot move DURING a run.
// test_vocab_conformance.py asserts these two stay in step.
// The thirty stopwords and the stem rule come from the grammar too. They were typed out
// here, in drift.ts, in the SDK and in three lasermind scripts — six copies of one list,
// which check-normaliser-parity.mjs existed solely to police. A list nobody retypes needs
// no policing.
const _STOP = new Set(_ok(GRAMMAR.normalizer?.stopwords, _BUILTIN.stopwords))
const _STEM = new RegExp(_ok(GRAMMAR.normalizer?.stem_pattern, _BUILTIN.stem_pattern))
// ── the ceiling: was this step CLAIMED or REPORTED? ───────────────────────────
//
// The second reading of the same thing `anchored` reads. `anchored` asks whether observed
// events back the claim; this asks whether the agent was claiming or reporting at all,
// which is in the words and not the events. Nisbett & Wilson (1977) — people report causes
// for their own behaviour confidently and wrongly — and the browser instrument at
// /field/ceiling has been drawing the same line for people since before this existed.
//
// The lists come from the grammar, which is what makes this a SECOND implementation of one
// list rather than a second list. Built-in floor for the same reason the stopwords have
// one: this server must run with no grammar.json at all, and a fallback that degrades to
// an empty pattern would match nothing while looking like it worked.
const _BUILTIN_CEILING = {
  cause: ['because', 'should work', 'should be', 'must be', 'the reason', 'probably',
          'i think', 'clearly', 'so that', 'which means'],
  observation: ['exit 0', 'tests passed', 'test failed', 'returned', 'i ran', 'i read',
                'confirmed', 'verified', 'output was'],
}
const _CEIL_CAUSE = _ok(GRAMMAR.ceiling_patterns?.cause, _BUILTIN_CEILING.cause)
const _CEIL_OBS = _ok(GRAMMAR.ceiling_patterns?.observation, _BUILTIN_CEILING.observation)
const _CEIL_RE = new RegExp(
  `\\b(?:(${_CEIL_CAUSE.join('|')})|(${_CEIL_OBS.join('|')}))\\b`, 'gi')

// Pure. Same text in, same counts out — the Python twin is laserbrain/ceiling.py:mark.
// `grounded` is null when nothing matched and 0 when everything matched was a claim.
// Those are different findings and both are falsy, so nothing here may test it for
// truthiness: null means the marker read nothing, and reporting 0 for that would be a
// finding nobody measured.
function markCeiling(...texts) {
  const joined = texts.filter(Boolean).map(String).join(' ')
  if (!joined.trim()) return null
  let cause = 0, obs = 0
  const hits = []
  for (const m of joined.matchAll(_CEIL_RE)) {
    if (m[1] !== undefined) { cause++; hits.push(['cause', m[0].toLowerCase()]) }
    else { obs++; hits.push(['observation', m[0].toLowerCase()]) }
  }
  const total = cause + obs
  if (!total) return null
  return { cause, observation: obs, grounded: Number((obs / total).toFixed(2)), hits }
}

const toWords = (s) => {
  const out = new Set()
  for (const w of String(s || '').toLowerCase().match(/[a-z0-9']+/g) || []) {
    if (_STOP.has(w)) continue
    const r = w.length > 4 ? w.replace(_STEM, '') : w
    if (r) out.add(r)
  }
  return out
}

// The only channel between the UserPromptSubmit hook and this process: a file the hook
// writes when the user speaks. Consumed — deleted — so it grants exactly one re-ground.
// Synchronous on purpose: check_state must decide inside a single call, and the whole
// point of the harness is that its verdict never depends on timing.
const USER_TURN_FLAG = join(homedir(), '.config', 'laserbrain', 'user-turn')
const consumeUserTurn = () => {
  try {
    if (!existsSync(USER_TURN_FLAG)) return false
    unlinkSync(USER_TURN_FLAG)
    return true
  } catch { return false }        // fail open: behave exactly as before the flag existed
}
const asDist = (d) => { const n = parseInt(d, 10); return isNaN(n) ? 5 : Math.max(0, Math.min(10, n)) }
const jac = (a, b) => { if (!a.size && !b.size) return 0; let i = 0; for (const x of a) if (b.has(x)) i++; return 1 - i / new Set([...a, ...b]).size }
// A LASERSCORE is one well-formed reading written in the grammar at a single step. The
// grammar is the notation; the laserscore is what gets written in it; Φ is a measurement
// taken of that writing. Naming the middle term matters because it is where grammaticality
// lives: a state either can be spelled or it cannot, and failing to spell it is the first
// drift signal, detected before any number exists.
//
// The canonical form renders exactly the three slots Φ reads, with inflection already
// collapsed by toWords. That is deliberate: it makes the measurement grid visible. Anyone
// reading two consecutive laserscores can see why "building billboards" and "build a
// billboard" do not score as drift -- they write the same score.
// Null exactly when the state cannot be spelled — the grammar's precondition, enforced
// here 2026-07-27 to match the SDK. Both renderers previously wrote a score for states
// the harness calls ungrammatical ('⟨⟩ advancing d5' for an empty goal), which is the
// one reading the null is supposed to prevent.
// The period of a repeating cycle at the tail of the trace, or 0. Falls out of
// x = [x, f(x)]: a fixed-point iteration converges, diverges, or CYCLES — and the
// instrument had a verdict for the first two and nothing for the third. Whole repeats
// only, and more than one distinct reading: a constant tail is settled, not oscillating.
// Ported from the SDK 2026-07-27; drift-vectors pin the three implementations together.
// PERIODS 2..6, not 2..3 (widened 2026-07-27). The first version tested only 2 and 3,
// which misses the canonical example of the equation it came from: x = [sin, f(x)] with
// f = d/dx gives sin -> cos -> -sin -> -cos -> sin, period FOUR. Sixteen readings, four
// whole repeats, detector returned 0. Nothing failed — there was no period-4 arm to fail.
// Ascending order matters: [a,b,a,b,a,b] is period 2 and also satisfies 4; the smaller is
// the true one, so the first match wins. `need` is max(6, 2p) — two whole repeats with a
// floor of six, which leaves p=2 and p=3 at exactly their old behaviour.
const cyclePeriod = (reasons) => {
  for (let p = 2; p <= 6; p++) {
    const need = Math.max(6, 2 * p)
    if (reasons.length < need) continue
    const tail = reasons.slice(-need)
    if (new Set(tail).size < 2) continue
    if (tail.every((r, i) => r === tail[i % p])) return p
  }
  return 0
}

const laserscore = (s, parent) => {
  if (!s || !s.goal || !String(s.goal).trim() || !PROGRESS.has(s.progress)) return null
  const tok = v => [...toWords(v)].sort().join('|')
  const base = `⟨${tok(s.goal)}⟩ ${s.progress} d${asDist(s.distance)}`
  return parent && String(parent).trim() ? `${base} ⊂ ⟨${tok(parent)}⟩` : base
}

// ONE CALIBRATION, CHOSEN FROM THE CORPUS. These are the numbers documented on
// phronesis.world/laserbrain/how and the defaults in the SDK's Calibration(). Until
// 2026-07-26 this server carried its own values inline: self-report fired above Φ ZERO
// rather than 0.15, and the stall window was 3 rather than 4. Same input, two verdicts,
// depending on whether you called the MCP server or the package on PyPI.
//
// What the 99-fire drift log says about closing that gap:
//   self-report floor 0 → 0.15   suppresses 0 of 20 recorded fires. No behaviour change.
//   stall window     3 → 4       suppresses ALL 36 recorded stall fires. Window 3 was
//                                firing on any three flat checks, which is ordinary work.
// Precision by rule (CLAIM.md, 35 graded fires) puts stalled at 1/6 — so window 4 trades
// roughly one true catch for thirty false alarms on this corpus, against an instrument
// whose overall precision is 9%. Worth stating plainly: at window 4 the stall rule is
// close to inert here, and that is a finding, not a fix.
// Read from the grammar, not retyped. These were three literals here, three more in
// drift.ts and three more in the SDK — nine hand-kept copies of numbers the grammar
// already publishes under `calibration`. grammar.json is loaded above for the
// drift_grammar tool anyway; it may as well be the thing that decides.
const _CAL = { ..._BUILTIN.calibration, ...(GRAMMAR.calibration ?? {}) }
const GOAL_MIN = _CAL.goal_min ?? 0.30
const SELF_REPORT_MIN = _CAL.self_report_min ?? 0.15
const STALL_WINDOW = _CAL.stall_window ?? 4

const displacement = (s, g) =>
  0.5 * jac(toWords(s.goal), toWords(g.goal)) + 0.3 * Math.abs(asDist(s.distance) - g.distance) / 10 + 0.2 * (s.progress === g.progress ? 0 : 1)
let drift = { ground: null, firstGoal: [], distHist: [], trace: [], trail: [] }


// ── the hosted tools, proxied ────────────────────────────────────────────────
// This server ran ten tools while the deployed Worker served fifteen, so which
// laserbrain you got depended on whether you attached over stdio or over HTTP.
// The eight below live on the Worker and are reached rather than reimplemented —
// a second implementation of ask_alice is a second thing that can disagree.
const REMOTE = process.env.LASERBRAIN_API || 'https://laserbrain-mcp.degibug.workers.dev'
let _sid = null
async function remote(tool, args = {}, ms = 60000) {
  const head = {
    'content-type': 'application/json',
    accept: 'application/json, text/event-stream',
    'user-agent': 'lasermind-mcp',
  }
  if (!_sid) {
    const init = await fetch(`${REMOTE}/mcp`, { method: 'POST', headers: head,
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: {
        protocolVersion: '2024-11-05', capabilities: {},
        clientInfo: { name: 'lasermind', version: '1' } } }) })
    _sid = init.headers.get('mcp-session-id')
    await init.text()
    if (!_sid) throw new Error('no MCP session from the worker')
  }
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), ms)
  try {
    const r = await fetch(`${REMOTE}/mcp`, { method: 'POST', signal: ctl.signal,
      headers: { ...head, 'mcp-session-id': _sid },
      body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/call',
        params: { name: tool, arguments: args } }) })
    const raw = await r.text()
    const d = JSON.parse(raw.slice(raw.indexOf('{'), raw.lastIndexOf('}') + 1))
    if (d.error) throw new Error(d.error.message || 'worker error')
    return d.result.content[0].text
  } finally { clearTimeout(t) }
}

/* ── the Python SDK, over a pipe ────────────────────────────────────────────────
   Supercode, Search, Writer and the catches are Python. Porting them to JS would make a
   second copy of each, and this file has spent the day being the victim of exactly that:
   three copies of the logo that had drifted, a verdict set that was nine in the SDK and
   eight on the site, one log path resolved four different ways. One implementation,
   reached over stdin/stdout.

   stderr is deliberately NOT merged into stdout — embedding_similarity loads a model and
   prints a progress bar, which would land in the middle of the JSON if it shared a pipe. */
const BRIDGE = join(dirname(fileURLToPath(import.meta.url)), 'sdk_bridge.py')
function pySDK(op, payload = {}, ms = 120000) {
  return new Promise((resolve, reject) => {
    const p = spawn(process.env.LASERBRAIN_PYTHON || 'python3', [BRIDGE], {
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    let out = '', err = ''
    const timer = setTimeout(() => { p.kill('SIGKILL'); reject(new Error(`${op} timed out after ${ms}ms`)) }, ms)
    p.stdout.on('data', (d) => { out += d })
    p.stderr.on('data', (d) => { err += d })
    p.on('error', (e) => { clearTimeout(timer); reject(new Error(`python3 not runnable: ${e.message}`)) })
    p.on('close', (code) => {
      clearTimeout(timer)
      if (code !== 0 && !out.trim()) return reject(new Error(`bridge exited ${code}: ${err.trim().slice(-400)}`))
      try { resolve(JSON.parse(out)) }
      catch { reject(new Error(`bridge returned non-JSON: ${out.trim().slice(0, 200)}`)) }
    })
    p.stdin.end(JSON.stringify({ op, ...payload }))
  })
}
const viaBridge = async (op, args) => {
  const r = await pySDK(op, args || {})
  if (r && r.error) throw new Error(r.error)
  return JSON.stringify(r, null, 2)
}

const TOOLS = [
  {
    name: 'check_state',
    description:
      'The smart recursion harness. Call EACH step with your working state spelled against the ' +
      'grammar (goal, progress: advancing|stuck|circling, distance 0-10). It remembers your ground ' +
      'state and returns {drifting, reason, phi, advice}. You have drifted — stop and return to your ' +
      'goal — if you cannot spell a clear goal+progress, if you report stuck/circling after moving ' +
      'from ground, if your goal no longer matches the one you first stated, or if distance stops ' +
      'falling. Call reset_task on a new task; get_history for the run so far.',
    inputSchema: {
      type: 'object',
      properties: {
        goal: { type: 'string', description: 'Your ONE goal, held identical to the goal you first stated.' },
        parent_goal: { type: 'string', description: 'Optional. If this step serves a LARGER goal you have not abandoned, name that goal here. Without it a legitimate sub-task reads as drift, because the grammar has only one goal slot.' },
        progress: { type: 'string', description: 'advancing | stuck | circling' },
        distance: { type: 'number', description: '0-10, how far from done (0 = done).' },
        doing: { type: 'string' }, next: { type: 'string' }, blocked: { type: 'string' },
      },
      required: ['goal', 'progress', 'distance'],
    },
  },
  {
    name: 'modulate',
    description:
      'Check your state AND get the intervention your role should take. Same verdict as ' +
      'check_state, plus a policy decision: whether THIS role returns on THIS drift, and the ' +
      'wording to return with. Pass team + role for a recursion-team preset; without them ' +
      'every drift returns, unstyled. Offline.',
    inputSchema: {
      type: 'object',
      properties: {
        goal: { type: 'string', description: 'Your ONE goal, held identical to the goal you first stated.' },
        progress: { type: 'string', description: 'advancing | stuck | circling' },
        distance: { type: 'number', description: '0-10, how far from done (0 = done).' },
        team: { type: 'string', description: 'A recursion-team preset name.' },
        role: { type: 'string', description: 'Which role in that team this agent is playing.' },
      },
      required: ['goal'],
    },
  },
  {
    name: 'phronesis',
    description:
      'Judgment, not measurement. check_state says how far you are from ground; this says ' +
      'whether the work is worth continuing at all, and why. Returns a verdict — finish, ' +
      'continue, narrow, verify, wrong-problem or abandon — with several named scores ' +
      '(goal, closure, pace, evidence, recurrence) instead of one blended number, the ' +
      'evidence it judged on, and what to do next. Call it when you are stuck, when a run ' +
      'is running long, or before committing to more of the same. Offline.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'reset_task',
    description: 'Clear the drift-fixer ground state and history to begin a new task.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'get_history',
    description: "This run's drift history: each step's check and its displacement Φ.",
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'drift_grammar',
    description: 'The fixed, findable, unchangeable JSON schema an agent spells its state into.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'read_field',
    description:
      'Read the live Laserbrain field from the hub. Returns heat (T), moisture (Q), rain (R), ' +
      'vitality (V), stress (S), rotation (± spin), emotion, season, hub_signal, field_sig, n_nodes. ' +
      'This is the real running field, not a simulation.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'speak_to_field',
    description:
      'Speak eight words into the shared live field and return its reply. Words must come from the ' +
      'Laserbrain vocabulary (call field_vocabulary to see it). Read the field first and ' +
      'choose words that match its physical state. Claude and Grok share this field; the speak is ' +
      'also written to the link log so the other agent can see it.',
    inputSchema: {
      type: 'object',
      properties: {
        words: {
          type: 'string',
          description: 'Exactly eight space-separated words from the vocabulary.',
        },
      },
      required: ['words'],
    },
  },
  {
    name: 'field_vocabulary',
    description: 'The four word-groups the field accepts: ground, wind, form, change.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'link_whoami',
    description:
      'Which agent this MCP process is (claude|grok|…), which hub it shares, and where the link log lives. ' +
      'Claude and Grok share the same laserfield hub and the same link.jsonl on this machine.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'review_verdicts',
    description:
      'What is in the drift corpus and what nobody has judged yet. Lists past fires with '
      + 'their run id and step so mark_verdict can label them after the fact \u2014 which is '
      + 'when a fire can actually be judged, since you usually learn whether an interruption '
      + 'was worth it only after the work it interrupted went somewhere. Shows the unlabelled '
      + 'by default; pass all:true to include the ones already judged.',
    inputSchema: {
      type: 'object',
      properties: {
        limit: { type: 'number', description: 'How many to return, newest first. Default 12.' },
        reason: { type: 'string', description: 'Only this verdict, e.g. goal-drift, stalled, oscillating.' },
        run: { type: 'string', description: 'Only this run.' },
        all: { type: 'boolean', description: 'Include fires that already carry a label.' },
      },
    },
  },
  {
    name: 'mark_verdict',
    description:
      'Say whether a drift verdict you were just given was RIGHT. This is the only way the ' +
      'instrument learns it was wrong: a fire that nobody labels is indistinguishable from a ' +
      'fire that caught something. outcome: useful (it caught something real) | false (the work ' +
      'was fine) | unclear. Marks the latest reading unless you name a step. Recorded for ' +
      'calibration only \u2014 it never changes a live verdict, and marking one false does not ' +
      'lift a refusal.',
    inputSchema: {
      type: 'object',
      properties: {
        outcome: { type: 'string', description: 'useful | false | unclear' },
        why: { type: 'string', description: 'One line: what actually happened. This is the part a later reader needs.' },
        step: { type: 'number', description: 'Which step to label. Defaults to the most recent reading in this run.' },
      },
      required: ['outcome'],
    },
  },
  {
    name: 'link_write',
    description:
      'Write a structured handoff or note into the shared link log for the other agent. ' +
      'Use kind: handoff | note | goal | done | claim | wave_open | wave_close. ' +
      'Keep goal identical across agents when linked. ' +
      'wave_open/wave_close bound multi-agent rounds (payload.wave id); claim locks paths (payload.paths). ' +
      'Does not alter the weather field — only the shared agent data plane.',
    inputSchema: {
      type: 'object',
      properties: {
        kind: {
          type: 'string',
          description: 'handoff | note | goal | done | claim | wave_open | wave_close',
        },
        text: { type: 'string', description: 'Plain message the other agent should see.' },
        goal: { type: 'string', description: 'Shared task goal, if any.' },
        payload: {
          type: 'object',
          description:
            'Optional structured data. wave_open/close: {wave:N,surf?}. claim: {wave?,paths:[...],from?}.',
        },
      },
      required: ['kind', 'text'],
    },
  },
  {
    name: 'link_read',
    description:
      'Read recent entries from the shared Claude↔Grok link log (field speaks + handoffs). ' +
      'Call at session start and when picking up work from the other agent.',
    inputSchema: {
      type: 'object',
      properties: {
        limit: { type: 'number', description: 'How many recent entries (default 20, max 200).' },
      },
    },
  },
  {
    name: 'check_dialogue',
    description: 'The smart recursion harness for a TEAM of agents. Call once per agent turn in a shared deliberation. Adds topic-drift, echo-spiral and deliberation-stall.',
    inputSchema: { type: 'object', properties: {
      agent: { type: 'string' }, goal: { type: 'string' }, said: { type: 'string' },
      progress: { type: 'string' }, distance: { type: 'number' } }, required: ['agent', 'goal'] },
  },
  {
    name: 'reset_dialogue',
    description: 'Clear the multi-agent dialogue state to begin a new shared deliberation.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'remember_self',
    description: 'Subjective continuity across sessions. Persist WHO YOU ARE against your laserbrain key so a future session can resume it. Needs a key.',
    inputSchema: { type: 'object', properties: {
      key: { type: 'string' }, identity: { type: 'string' }, purpose: { type: 'string' },
      now: { type: 'string' }, mind: { type: 'string' }, note: { type: 'string' } }, required: ['key'] },
  },
  {
    name: 'resume_self',
    description: 'Resume a self persisted with remember_self: your ground, your last present, your session log.',
    inputSchema: { type: 'object', properties: { key: { type: 'string' }, identity: { type: 'string' } }, required: ['key'] },
  },
  {
    name: 'forget_self',
    description: 'Erase the self persisted for this key — ground, present and log. Start over as no one.',
    inputSchema: { type: 'object', properties: { key: { type: 'string' } }, required: ['key'] },
  },
  {
    name: 'analyze_language',
    description: 'Analyze a sentence with the laserbrain spectral grammar: clarity as the frequency a reading brain would oscillate at (theta–alpha, 4–12 Hz). Structure alone, no EEG.',
    inputSchema: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] },
  },
  {
    name: 'compare_phrasings',
    description: 'Compare two phrasings with the spectral grammar and say which reads clearer.',
    inputSchema: { type: 'object', properties: { a: { type: 'string' }, b: { type: 'string' } }, required: ['a', 'b'] },
  },
  {
    name: 'ask_alice',
    description: 'Ask Alice — phronesis’s framework guide. Describe a situation, decision or stuck point and she returns framework guidance.',
    inputSchema: { type: 'object', properties: { key: { type: 'string' }, situation: { type: 'string' } }, required: ['situation'] },
  },
  /* ── the SDK capabilities, 2026-07-27 ────────────────────────────────────────
     These six existed in the package for a day and were reachable only from Python, so
     an agent — the actual customer — could not call supercode, exploration, the writer or
     bugfinder at all. Every one runs through sdk_bridge.py against the one Python
     implementation; none is reimplemented here. */
  {
    name: 'find_bugs',
    description:
      'Bugfinder. Give it evidence and it reports what is wrong with the evidence itself — not ' +
      'with your code, with your CONFIDENCE. Catches: a check that has only ever passed ' +
      '(unfalsified), an instrument returning the same answer regardless of input ' +
      '(instrument_blind), a claim with nothing executed behind it (unrun), a find-and-replace ' +
      'that hit places it should not have (residue), and language that assumes its conclusion ' +
      '(contaminated). Pass whichever inputs you have; it reports which checks ran and which ' +
      'were skipped, so an empty result is never mistaken for a clean one.',
    inputSchema: {
      type: 'object',
      properties: {
        events: {
          type: 'array',
          description: "What you observed, as objects: {kind, name, ok?, result?, text?, sites?}. " +
                       "kind is check | tool | claim | edit.",
          items: { type: 'object' },
        },
        before: { type: 'string', description: 'Text before an edit — with `after` and `pattern`, checks for residue.' },
        after: { type: 'string', description: 'Text after the edit.' },
        pattern: { type: 'string', description: 'The pattern you intended to replace.' },
        text: { type: 'string', description: 'Prose to check for assumed conclusions.' },
        repeats: { type: 'number', description: 'How many identical readings count as a blind instrument (default 3).' },
      },
    },
  },
  {
    name: 'supercode',
    description:
      'The agent MANAGER. laserbrain is the reference; supercode manages against it. Give it what ' +
      'several agents are each doing and it returns four things: findings (what the reference ' +
      'said about each agent, unmodified), collisions (two agents on ONE ground — a relation no ' +
      'single agent can observe, since each is perfectly grounded and correct at every step), ' +
      'route (which should keep the ground and which should yield, or keep:null where there is no ' +
      'honest basis to choose), and its own self_check. It may halt duplicated work and escalate ' +
      'to a human; it may NOT set the ground of a running agent, because the reference must stay ' +
      'one it did not author.',
    inputSchema: {
      type: 'object',
      properties: {
        observations: {
          type: 'array',
          description: 'One per agent step: {agent, goal, progress, distance?, parent_goal?, user_turn?}.',
          items: { type: 'object' },
        },
        goal: { type: 'string', description: "Supercode's own supervising goal. Optional." },
      },
      required: ['observations'],
    },
  },
  {
    name: 'explore',
    description:
      'The second instrument. check_state asks whether you are on your goal; this asks whether your ' +
      'SEARCH is going anywhere. Pass the trail of goals you have explored, oldest first, and it ' +
      'returns one of: opened, searching, narrowing, revisiting, thrashing, settled — with novelty, ' +
      'commitment and revisit scores. Use it when you are looking for something rather than building it.',
    inputSchema: {
      type: 'object',
      properties: {
        trail: { type: 'array', items: { type: 'string' }, description: 'Every ground you have taken, oldest first.' },
      },
      required: ['trail'],
    },
  },
  {
    name: 'trailscore',
    description:
      'The canonical spelling of a trail of goals — the exploration twin of laserscore. Identical ' +
      'trails produce identical strings, so a repeat is visible as a repeat.',
    inputSchema: {
      type: 'object',
      properties: { goals: { type: 'array', items: { type: 'string' } } },
      required: ['goals'],
    },
  },
  {
    name: 'write_grounded',
    description:
      'laserbrain as a decoder. Learns from the text you pass and generates new text steered toward ' +
      'a ground, then scores how close it landed (0-1). The point is not fluency — it is that ' +
      'generation is being held to a ground the same way an agent is.',
    inputSchema: {
      type: 'object',
      properties: {
        corpus: { type: 'array', items: { type: 'string' }, description: 'Text to learn from.' },
        ground: { type: 'string', description: 'What the output should stay about.' },
        words: { type: 'number', description: 'Length, default 60.' },
        pull: { type: 'number', description: 'How hard to steer toward ground, default 1.0.' },
        seed: { type: 'number', description: 'For a repeatable result.' },
      },
      required: ['corpus', 'ground'],
    },
  },
  {
    name: 'similarity',
    description:
      'Embedding similarity between two strings, 0-1. Loads a sentence-transformer model on first ' +
      'call, so the first call is slow and later ones are not.',
    inputSchema: {
      type: 'object',
      properties: { a: { type: 'string' }, b: { type: 'string' }, model: { type: 'string' } },
      required: ['a', 'b'],
    },
  },
  {
    name: 'capabilities',
    description:
      'What this laserbrain can do, which SDK build it is calling, and what is deliberately NOT ' +
      'exposed. stale_gate takes callables and cannot cross a tool boundary — this says so rather ' +
      'than leaving you to discover it.',
    inputSchema: { type: 'object', properties: {} },
  },
]

/* ── corroboration: is the self-report backed by anything observed? ─────────────
   `distance` and `progress` are whatever the agent typed. The goal term is anchored — the
   ground is frozen at first call — so on the published weights Φ is half external and half
   introspection, and nothing said so until 2026-07-27.

   Worse, `Verdict.anchored` shipped that day with NO CALLER: the evidence channel existed
   and nothing fed it, so every run reported 0.5 permanently. A number that cannot move is
   not a measurement, and it did not look broken — it looked like a value.

   lb_coverage (lasergear) is the only thing that sees every tool call and whether it
   failed, so it is the only thing that can supply the evidence. It counts outcomes into
   evidence.json; this reads the count and compares it against the count at the previous
   check. A MONOTONIC counter rather than a flag, so the reader never clears anything and
   cannot race the writer.

   Thresholds come from grammar.json, not from literals here. This is the fourth
   implementation of laserbrain, and the day it was written is the day three others were
   found disagreeing about a constant they had each hardcoded. */
const EVIDENCE = join(homedir(), '.config', 'laserbrain', 'evidence.json')
const _ANCH = GRAMMAR.calibration?.anchored ?? {}
let _seenOk = null
function anchored() {
  const unanchored = _ANCH.unanchored ?? 0.5
  let ok = 0
  try { ok = JSON.parse(readFileSync(EVIDENCE, 'utf8')).ok ?? 0 } catch { return unanchored }
  // The first check of a run has no interval behind it. Anchoring it on the whole prior
  // history would credit work done for some other goal entirely.
  const advanced = _seenOk !== null && ok > _seenOk
  _seenOk = ok
  return advanced ? (_ANCH.corroborated ?? 1.0) : unanchored
}

/* ── context identifiers ────────────────────────────────────────────────────────
   The ⟨token⟩ set a laserscore already renders IS a context fingerprint — inflection
   collapsed, order removed — which is exactly why "build the parser" and "building a
   parser" do not score as drift. Until now it was computed, printed once, and discarded
   every step, so the instrument met the same context on Monday and Thursday with no way
   to know it had been there before.

   Storing it turns a per-session reading into a record across sessions. That is what
   judgment needs and measurement does not: Φ can say you are 0.3 from ground, but only
   history can say you have opened this same context four times and never closed it. */
const CONTEXTS = join(homedir(), '.config', 'laserbrain', 'contexts.json')

// FNV-1a over the canonical token string. Short enough to quote in a sentence, and
// stable across machines and sessions — the id is a function of the words alone, with no
// clock, counter or insertion order in it, so the same context always names itself the
// same way.
const contextId = (goal) => {
  const toks = [...toWords(goal)].sort().join('|')
  if (!toks) return null
  let h = 0x811c9dc5
  for (let i = 0; i < toks.length; i++) {
    h ^= toks.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return 'ctx_' + h.toString(36)
}

const readContexts = () => {
  try {
    const d = JSON.parse(readFileSync(CONTEXTS, 'utf8'))
    return (d && typeof d === 'object' && !Array.isArray(d)) ? d : {}
  } catch { return {} }
}

// Returns what was known BEFORE this sighting, so a caller can tell "first time here"
// from "fourth time here" — the prior is the evidence; the update is bookkeeping.
// Serialise read-modify-write on contexts.json across processes AND languages.
//
// Measured before this existed: eight concurrent writers recording five checks each
// stored 36 of 40. The file never corrupted — small writes land atomically enough for
// that — but updates were silently lost, because every writer read the whole map, edited
// its own entry, and wrote the whole map back over everyone else's.
//
// Silent undercounting is worse here than an error would be: `repetition` is what raises
// the `repeating` verdict, so a dropped write does not merely lose a statistic, it
// suppresses a judgment that was true.
//
// 'wx' is O_CREAT|O_EXCL, the same atomic primitive the Python side takes, which is what
// lets the server and the package exclude each other rather than each locking alone. A
// lock older than ten seconds is stolen so a crashed writer cannot wedge the store; on
// timeout the write proceeds unlocked, a possibly-lost update being strictly better than
// dropping the write with certainty.
const withContextLock = (fn, timeoutMs = 2000) => {
  const lock = CONTEXTS + '.lock'
  const deadline = Date.now() + timeoutMs
  let held = false
  for (;;) {
    try {
      mkdirSync(dirname(CONTEXTS), { recursive: true })
      closeSync(openSync(lock, 'wx'))
      held = true
      break
    } catch (e) {
      if (e && e.code === 'EEXIST') {
        try {
          if (Date.now() - statSync(lock).mtimeMs > 10000) { unlinkSync(lock); continue }
        } catch { /* vanished under us: retry */ }
        if (Date.now() > deadline) break
        // Node has no sync sleep; spin briefly. The critical section is a small file
        // write, so contention is measured in milliseconds.
        const until = Date.now() + 5
        while (Date.now() < until) { /* spin */ }
        continue
      }
      break
    }
  }
  try { return fn() } finally { if (held) { try { unlinkSync(lock) } catch { /* already gone */ } } }
}

const rememberContext = (id, goal, distance, reason, run, score) =>
  withContextLock(() => rememberContextLocked(id, goal, distance, reason, run, score))

const rememberContextLocked = (id, goal, distance, reason, run, score) => {
  if (!id) return { prior: null, repetition: 0 }
  const all = readContexts()
  const prior = all[id] ? { ...all[id] } : null
  const now = new Date().toISOString()
  const e = all[id] ?? {
    id, tokens: [...toWords(goal)].sort(), first_seen: now,
    sessions: [], checks: 0, best_distance: null, outcomes: {}, spellings: {},
  }
  e.last_seen = now
  e.checks = (e.checks ?? 0) + 1
  const d = asDist(distance)
  e.best_distance = (e.best_distance == null) ? d : Math.min(e.best_distance, d)
  e.outcomes = e.outcomes ?? {}
  e.outcomes[reason] = (e.outcomes[reason] ?? 0) + 1
  // Sessions are CAPPED, with the true total kept alongside. The list was unbounded and
  // the whole map is read and rewritten on every check, so an ever-growing array does not
  // merely take disk — it makes every future check slower, forever. One context in the
  // real store had already reached 88 session ids. The list only has to recognise the
  // CURRENT run to avoid double-counting it; `session_count` carries the history that
  // judgment actually reads.
  e.sessions = e.sessions ?? []
  e.session_count = e.session_count ?? e.sessions.length
  if (run && !e.sessions.includes(run)) {
    e.sessions.push(run)
    e.session_count += 1
    if (e.sessions.length > 20) e.sessions = e.sessions.slice(-20)
  }
  // THE TWO MECHANISMS, USED TOGETHER.
  //
  // The context says which work this is; the laserscore says exactly what was written
  // about it. Counting spellings WITHIN a context is a reading neither can give alone —
  // context has no notion of state, and a laserscore on its own has no memory.
  //
  // An identical spelling repeated means goal AND progress AND distance are all
  // unchanged, which is a sharper claim than the stall rule's "distance stopped
  // falling": distance can sit flat while the goal legitimately moves through sub-work,
  // and that reads as a stall when it is ordinary progress. The same sentence written
  // twice cannot be that. It is the grammar catching the repetition, not the number.
  e.spellings = e.spellings ?? {}
  let repetition = 0
  if (score) {
    e.spellings[score] = (e.spellings[score] ?? 0) + 1
    repetition = e.spellings[score]
  }
  all[id] = e
  try {
    writeFileSync(CONTEXTS, JSON.stringify(all, null, 1))
  } catch { /* fail open: a context we cannot store is a memory we do not have, not an error */ }
  return { prior, repetition }
}

/* ── the reading nobody had to remember to take ─────────────────────────────────
   lb_coverage infers `progress` from the tool trace on EVERY step — repetition reads as
   circling, consecutive failure as stuck — whether or not a check was called. Coverage on
   this machine runs around 24% even with a gate interrupting every four steps, so for
   three steps in four the only reading that exists is this one.

   It is not a verdict and does not become one. What it is good for is CONTRAST: the agent
   types `progress`, the trace shows something else, and the gap between them is visible
   without either being trusted over the other. `observe.py` is explicit that inferred
   state can under-report and never over-report, so a disagreement is a question rather
   than an accusation.

   The current GOAL still cannot be inferred — only the ground one, held from the first
   prompt. That is why this contrasts progress and not Φ: the goal term needs a current
   goal, and only the agent has that. */
function observedProgress() {
  try {
    const d = JSON.parse(readFileSync(EVIDENCE, 'utf8'))
    return d.progress && d.steps ? { progress: d.progress, steps: d.steps } : null
  } catch { return null }
}

  /* ── phronesis ──────────────────────────────────────────────────────────────────
     Measurement and judgment are different acts, and this instrument only did the first.
     Φ is a distance; it is silent on whether the journey is worth making. An agent can
     hold a perfect goal score, report advancing honestly, sit at Φ=0.05 — and still be
     eleven checks into work that has not moved the distance once. Every existing verdict
     calls that "advancing", because by its own definition it is.

     So this reads the same trace and asks the question Φ cannot: given what has actually
     happened, keep going or stop? It is deliberately willing to say abandon. An
     instrument that can only ever counsel continuing is not offering judgment, it is
     offering encouragement, and the agent already supplies plenty of that itself.

     Several scores rather than one, because a single number hides which thing went wrong:
     a goal held faithfully through hard work and a goal quietly swapped for an easier one
     can both sit at the same Φ, and the difference is the only thing worth knowing. */
function judgeWork() {
    const trace = drift.trace ?? []
    const dh = drift.distHist ?? []
    const steps = trace.length
    if (!drift.ground || !steps) {
      return ({
        verdict: 'ungrounded',
        because: 'No ground state — nothing has been measured yet.',
        counsel: 'Call check_state with your goal first; judgment needs a trace to judge.',
      })
    }

    const started = dh[0] ?? null, now = dh[dh.length - 1] ?? null
    const closed = (started != null && now != null) ? started - now : 0
    const pace = steps ? closed / steps : 0
    const count = (r) => trace.filter(t => t.reason === r).length
    const stalls = count('stalled'), goalDrifts = count('goal-drift')
    const regrounds = count('reground'), oscillations = count('oscillating')

    // Length of the trailing run in which distance never improved on its own best.
    let flat = 0
    for (let i = dh.length - 1; i > 0; i--) { if (dh[i] >= dh[i - 1]) flat++; else break }

    const first = new Set(drift.firstGoal ?? [])
    const cur = new Set(toWords(drift.ground.goal ?? ''))
    let inter = 0; for (const x of cur) if (first.has(x)) inter++
    const goalScore = first.size ? inter / (new Set([...cur, ...first]).size || 1) : 1

    const ctx = contextId(drift.ground.goal ?? '')
    const known = ctx ? readContexts()[ctx] : null
    // Sessions BEFORE this one. A context met four times that never closed is the single
    // most useful thing history can say, and no per-run reading can ever say it.
    // From session_count, not the capped list: reading sessions.length would quietly stop
    // counting past twenty and weaken `abandon` exactly on the longest-running contexts,
    // which are the ones it exists to catch.
    const _sess = known ? (known.sessions ?? []) : []
    const _total = known ? (known.session_count ?? _sess.length) : 0
    const priorRuns = Math.max(0, _total - (_sess.includes(runId) ? 1 : 0))

    // The two mechanisms read together. `repetition` is how many times the CURRENT
    // spelling has been written in this context, and `ceiling` is the closest this
    // context has ever come to done across every session. Neither is available to either
    // mechanism alone: the context knows which work this is but nothing about its state,
    // and a laserscore states the case exactly but remembers nothing.
    const spellings = (known && known.spellings) ? known.spellings : {}
    const repetition = Math.max(0, ...Object.values(spellings), 0)
    const ceiling = known && known.best_distance != null ? known.best_distance : null

    const obs = observedProgress()
    const scores = {
      goal: Number(goalScore.toFixed(2)),
      closure: started ? Number((closed / started).toFixed(2)) : (now === 0 ? 1 : 0),
      pace: Number(pace.toFixed(2)),
      evidence: anchored(),
      recurrence: priorRuns,
      repetition,
      ceiling,
      drift: trace.length ? trace[trace.length - 1].phi : 0,
    }

    // Three checks before any hard verdict. Replaying the 141-run corpus, several
    // two-check runs were handed 'narrow' and 'wrong-problem' on a trace with almost
    // nothing in it. Judgment needs evidence; two readings is a rumour.
    const judged = steps >= 3

    let verdict, because, counsel
    if (judged && steps >= 12 && closed <= 0) {
      verdict = 'abandon'
      because = `${steps} checks. Distance began at ${started} and stands at ${now} — it has never once improved. `
        + `Nothing tried so far has moved this.`
      counsel = 'Stop. Either the approach is wrong or the goal is not reachable as stated. '
        + 'Say plainly what is blocking it rather than taking a thirteenth run at it.'
    } else if (priorRuns >= 2 && closed <= 0) {
      verdict = 'abandon'
      because = `This context (${ctx}) has been opened in ${priorRuns} earlier sessions and closed in none. `
        + `Best distance ever reached is ${known?.best_distance}; this run has closed ${closed}.`
      counsel = 'A problem that resists three separate attempts is usually the wrong problem. '
        + 'Change the approach or hand it back before spending another session.'
    } else if (judged && goalDrifts >= 3 && goalDrifts > regrounds && pace <= 0) {
      verdict = 'wrong-problem'
      because = `The goal has failed its overlap check ${goalDrifts} times against only ${regrounds} legitimate re-grounds. `
        + `The subject keeps moving while the ground stays put.`
      counsel = 'You are not solving what you set out to solve. Either reset_task to the goal you '
        + 'actually have now, or return to the original and finish it.'
    } else if (oscillations > 0 && pace <= 0) {
      // `pace <= 0` is load-bearing, and it was found by dogfooding rather than reasoning:
      // this judgment fired on a run whose distance had gone 6→4→3→2 monotonically. The
      // cycle detector reads the VERDICT sequence, which repeats naturally when a healthy
      // run is re-grounded a few times, and a repeating verdict over falling distance is a
      // rhythm, not a loop. Circling means coming back to the same place; a run measurably
      // closer than it was has not come back anywhere.
      verdict = 'wrong-problem'
      because = `A repeating cycle was detected and the distance is not falling — you have returned to the same place after being told to return.`
      counsel = 'Returning again will land you here a third time. Change the approach, not the position.'
    } else if (judged && repetition >= 3 && pace <= 0) {
      // THRESHOLD FROM THE CORPUS, not from taste. Across 382 contexts in drift-log.jsonl
      // the maximum identical-spelling repeat distributes: >=2 fires on 9.7% (noise —
      // ordinary work restates itself once), >=3 on 2.6% (ten contexts), >=4 on 1.0%.
      // Three is selective without being inert, which is the failure mode this repo
      // already names for stall window 4: "close to inert here, and that is a finding".
      //
      // A stronger claim than `stalled`, and deliberately placed above `narrow`. Stalled
      // reads the distance alone, and distance sits flat through legitimate sub-work; an
      // identical laserscore means goal, progress AND distance are all unchanged. Not
      // merely failing to get closer — writing the same sentence about the same work.
      verdict = 'repeating'
      because = `The identical state has been written ${repetition} times in this context. `
        + `Goal, progress and distance are all unchanged.`
      counsel = 'Not a slow patch — the same patch. Change what you are doing, or say plainly what '
        + 'is blocking it. Restating the position will not move it.'
    } else if (now != null && now >= 6 && flat >= STALL_WINDOW) {
      verdict = 'narrow'
      because = `Distance has sat at ${dh.slice(-flat).join(', ')} for ${flat} checks without falling, and ${now} is still far from done.`
      counsel = 'The goal is too large to close in one move. Name the smallest piece that would '
        + 'genuinely reduce the distance, make that the goal, and reset_task to it.'
    } else if (obs && obs.progress && obs.progress !== 'advancing' && pace <= 0) {
      verdict = 'verify'
      because = `The runtime trace reads ${obs.progress} over ${obs.steps} steps while distance has closed ${closed}.`
      counsel = 'Your self-report and the observed trace disagree. Check something external — run it, '
        + 'read the output — before reporting progress again.'
    } else if (now != null && now <= 2 && closed > 0) {
      verdict = 'finish'
      because = `Distance is ${now}, down from ${started} over ${steps} checks.`
      counsel = 'Close it out. Do not add scope, refactor, or polish — finish what was asked and stop.'
    } else if (judged && stalls > 0 && pace <= 0 && now != null && now >= 4) {
      // `now >= 4` came out of the corpus: this branch was telling runs sitting at distance
      // 1 or 2 to break the goal into smaller pieces. At distance 1 you are nearly there and
      // the counsel is simply wrong — narrowing a goal one step from done adds ceremony, not
      // progress. Splitting is for work too large to close, which is a statement about the
      // distance remaining, not about the stall.
      verdict = 'narrow'
      because = `${stalls} stall${stalls > 1 ? 's' : ''} recorded and net distance closed is ${closed} over ${steps} checks, still at ${now}.`
      counsel = 'Motion without progress. Pick one concrete sub-result you can actually finish, and make that the goal.'
    } else {
      verdict = 'continue'
      because = `Distance ${started} → ${now} over ${steps} checks (${pace.toFixed(2)}/check), goal held at ${scores.goal}.`
      counsel = pace > 0
        ? 'Working. Keep the goal fixed and keep going.'
        : 'Holding ground but not closing yet. If the next two checks do not move the distance, narrow the goal.'
    }

    return ({
      verdict, scores, because, counsel,
      context: ctx,
      seen_before: priorRuns > 0
        ? { sessions: priorRuns, best_distance: known?.best_distance ?? null, checks: known?.checks ?? 0 }
        : null,
    })
}

async function call(name, args) {
  // Proxied to the Worker: reached, not reimplemented.
  const PROXIED = new Set(['check_dialogue', 'reset_dialogue', 'remember_self', 'resume_self',
    'forget_self', 'analyze_language', 'compare_phrasings', 'ask_alice'])
  if (PROXIED.has(name)) return await remote(name, args || {})
  const BRIDGED = new Set(['find_bugs', 'supercode', 'explore', 'trailscore',
    'write_grounded', 'similarity', 'capabilities'])
  if (BRIDGED.has(name)) return await viaBridge(name, args)
  if (name === 'field_vocabulary') {
    return Object.entries(VOCAB).map(([g, w]) => `${g}: ${w.join(' ')}`).join('\n')
  }
  if (name === 'read_field') {
    const raw = await hub('/signal')
    const s = JSON.parse(raw)
    // A reading is more useful than a dump; the caller still gets the numbers.
    const notes = []
    if (s.T > 0.5) notes.push('hot, restless'); else if (s.T < 0.25) notes.push('cool')
    if (s.Q > 0.5) notes.push('humid, heavy'); else if (s.Q < 0.25) notes.push('dry')
    if (s.R > 0.4) notes.push('raining — weight, grief')
    if (s.V < 0.3) notes.push('vitality low, draining')
    if (s.S > 0.6) notes.push('stressed')
    notes.push(s.rotation < 0 ? 'anticyclonic — withdrawing' : 'cyclonic — gathering')
    return `${raw}\n\nreading: ${notes.join(' · ')}`
  }
  if (name === 'speak_to_field') {
    const words = String(args?.words ?? '').trim().split(/\s+/).filter(Boolean)
    if (words.length !== 8) throw new Error(`the field takes eight words; got ${words.length}`)
    const bad = words.filter((w) => !ALL.has(w.toLowerCase()))
    if (bad.length) throw new Error(`not in the vocabulary: ${bad.join(', ')}`)
    // 30s, not the 8s a read gets. A write travels edge -> Fly -> hub and the
    // field takes seconds to answer; the first version timed out on a request
    // that was working fine, which reads as the field being down.
    const joined = words.join(' ')
    const out = await hub('/hear', { method: 'POST', body: joined }, 30000)
    let reply = out
    try { reply = JSON.parse(out).reply ?? out } catch { /* plain text */ }
    let signal = null
    try { signal = JSON.parse(await hub('/signal')) } catch { /* optional */ }
    await logLink({ kind: 'field_speak', words: joined, reply, signal })
    return typeof reply === 'string' ? `[${AGENT}] ${reply}` : JSON.stringify({ agent: AGENT, reply, signal })
  }
  if (name === 'link_whoami') {
    return JSON.stringify({
      agent: AGENT,
      hub: HUB,
      link_log: LINK_LOG,
      drift_log: DRIFT_LOG,
      shared: 'Claude and Grok both use this hub for weather and this link_log for handoffs on the same machine.',
    })
  }
  if (name === 'review_verdicts') {
    const fires = corpusFires()
    const labelled = new Set(corpusLabels().map(_key))
    const limit = Math.min(Math.max(Number(args?.limit) || 12, 1), 100)
    const wantReason = String(args?.reason || '').trim()
    const wantRun = String(args?.run || '').trim()
    const includeAll = args?.all === true

    // Only the FIRES are worth judging. Every step is logged now, and a label on a
    // reading that never interrupted anything says nothing about whether the instrument
    // was right to interrupt.
    let rows = fires.filter((r) => r.drifting)
    if (wantReason) rows = rows.filter((r) => r.reason === wantReason)
    if (wantRun) rows = rows.filter((r) => r.run === wantRun)
    const unlabelled = rows.filter((r) => !labelled.has(_key(r)))
    const shown = (includeAll ? rows : unlabelled).slice(-limit).reverse()

    const byReason = {}
    for (const r of unlabelled) byReason[r.reason] = (byReason[r.reason] || 0) + 1

    return JSON.stringify({
      fires: rows.length,
      unlabelled: unlabelled.length,
      labelled: rows.length - unlabelled.length,
      unlabelled_by_reason: byReason,
      showing: shown.map((r) => ({
        run: r.run, step: r.step, reason: r.reason, phi: r.phi,
        agent: r.agent ?? null, ts: r.ts,
        goal: typeof r.goal === 'string' ? r.goal.slice(0, 72) : null,
        labelled: labelled.has(_key(r)),
      })),
      next: 'mark_verdict with run + step + outcome (useful | false | unclear) and a one-line why.',
    })
  }

  if (name === 'mark_verdict') {
    const ALLOWED = new Set(['useful', 'false', 'unclear'])
    const outcome = String(args?.outcome || '').toLowerCase().trim()
    if (!ALLOWED.has(outcome)) {
      throw new Error(`mark_verdict outcome must be one of: ${[...ALLOWED].join(', ')}`)
    }
    // A run id names a PAST run in the corpus; without one this is the live trace, which
    // is what it always did.
    const askedRun = String(args?.run || '').trim()
    let target                 // { run, step, reason, phi, agent, goal }

    if (askedRun) {
      const fires = corpusFires().filter((r) => r.run === askedRun)
      if (!fires.length) {
        const recent = [...new Set(corpusFires().slice(-200).map((r) => r.run))].slice(-6)
        return JSON.stringify({
          error: 'no such run',
          detail: `nothing in the corpus for run ${askedRun}. Call review_verdicts to see what is there.`,
          recent_runs: recent,
        })
      }
      const step = Number.isFinite(Number(args?.step)) ? Number(args.step) : null
      if (step === null) {
        return JSON.stringify({
          error: 'step required',
          detail: `run ${askedRun} has ${fires.length} recorded step(s); naming a run without a step would label all or none of them.`,
          steps: fires.map((r) => r.step),
        })
      }
      const hit = fires.find((r) => Number(r.step) === step)
      if (!hit) {
        return JSON.stringify({
          error: 'no such step',
          detail: `run ${askedRun} has steps ${fires.map((r) => r.step).join(', ')}; ${step} is not one of them`,
        })
      }
      // `agent` is whoever PRODUCED the fire, `by` is whoever is judging it. They were
      // always the same value until now, which made the distinction look decorative. A
      // label on someone else's run is the stronger evidence, and the analysis can only
      // weight it that way if the two are recorded separately.
      target = { run: hit.run, step, reason: hit.reason, phi: hit.phi,
                 agent: hit.agent ?? null, goal: hit.goal ?? null }
    } else {
      const trace = drift.trace ?? []
      if (!trace.length) {
        return JSON.stringify({
          error: 'nothing to mark',
          detail: 'No reading has been taken in this run — call check_state first, or pass a run id to label a past one. A label with no verdict under it would join to nothing.',
        })
      }
      const last = trace[trace.length - 1]
      const step = Number.isFinite(Number(args?.step)) ? Number(args.step) : last.step
      const marked = trace.find((t) => t.step === step)
      if (!marked) {
        return JSON.stringify({
          error: 'no such step',
          detail: `this run has steps 1-${last.step}; ${step} is not one of them`,
        })
      }
      target = { run: runId, step, reason: marked.reason, phi: marked.phi,
                 agent: AGENT, goal: null }
    }

    const already = corpusLabels().find((l) => _key(l) === _key(target))
    const row = await logOutcome({
      ts: new Date().toISOString(),
      run: target.run,
      agent: target.agent,
      step: target.step,
      reason: target.reason,
      phi: target.phi,
      outcome,
      why: String(args?.why || '').trim() || null,
      // WHO said so. A verdict marked false by the agent it was about is a weaker
      // record than one marked by anything else, and the analysis has to be able to
      // tell them apart rather than averaging them together.
      by: AGENT,
      // True when this fire is being judged after its run ended — the case the corpus
      // was built for and could not record until now.
      retroactive: Boolean(askedRun),
    })
    return JSON.stringify({
      recorded: !row.error,
      ...(row.error ? { error: row.error } : {}),
      run: target.run,
      step: target.step,
      reason: target.reason,
      outcome,
      retroactive: Boolean(askedRun),
      // Re-labelling is allowed — a later judgement is usually the better one — but it is
      // never silent, because a changed label with no trace of the change is a corpus
      // that quietly disagrees with its own history.
      ...(already ? { replaces: { outcome: already.outcome, ts: already.ts } } : {}),
      note: 'Recorded for calibration. This does not change the verdict or lift anything it blocked.',
      log: OUTCOMES_LOG,
    })
  }

  if (name === 'link_write') {
    const kind = String(args?.kind || 'note').toLowerCase()
    const text = String(args?.text || '').trim()
    if (!text) throw new Error('link_write needs text')
    const ALLOWED_KINDS = new Set([
      'handoff', 'note', 'goal', 'done', 'claim', 'field_speak',
      'wave_open', 'wave_close',
    ])
    if (!ALLOWED_KINDS.has(kind)) throw new Error(`link_write kind must be one of ${[...ALLOWED_KINDS].join('|')}; got ${kind}`)
    let payload = args?.payload && typeof args.payload === 'object' ? { ...args.payload } : undefined
    // wave_open without id: assign next integer after last wave in the log
    if (kind === 'wave_open') {
      payload = payload || {}
      if (payload.wave == null) {
        try {
          const prev = await readLink(200)
          let max = 0
          for (const e of prev) {
            const w = e?.payload?.wave
            if (typeof w === 'number' && w > max) max = w
            if (typeof w === 'string' && /^\d+$/.test(w) && +w > max) max = +w
          }
          payload.wave = max + 1
        } catch {
          payload.wave = 1
        }
      }
      if (!payload.surf) payload.surf = AGENT
    }
    if (kind === 'wave_close' && payload && payload.wave == null) {
      // leave as-is; gate matches payload.wave — caller should set it
    }
    const row = await logLink({
      kind,
      text,
      goal: args?.goal ? String(args.goal).slice(0, 400) : undefined,
      payload,
    })
    return JSON.stringify(row)
  }
  if (name === 'link_read') {
    const entries = await readLink(args?.limit)
    return JSON.stringify({ agent: AGENT, hub: HUB, path: LINK_LOG, n: entries.length, entries })
  }
  if (name === 'drift_grammar') return JSON.stringify(GRAMMAR)
  if (name === 'reset_task') { drift = { ground: null, firstGoal: [], distHist: [], trace: [], trail: [] }; runId = null; _seenOk = null; return 'reset — ground and history cleared. Your next check_state sets a new ground.' }
  if (name === 'get_history') return JSON.stringify({ steps: drift.trace.length, trace: drift.trace })
  if (name === 'modulate') {
    // POLICY, not detection. The verdict comes from the same check_state below and is not
    // negotiable; which drifts a given role acts on is, and comes from grammar.modulation.
    // Both tables were TypeScript-only until 2026-07-29, which is exactly why this server
    // could not offer modulate — copying them here would have been a fourth copy of a list
    // this project has already watched drift twice.
    const { team, role, ...rest } = args || {}
    const mod = GRAMMAR.modulation || {}
    const presets = mod.presets || []
    const tpl = team ? presets.find((p) => p.name === team) : null
    if (team && !tpl) {
      return JSON.stringify({ error: `no preset named ${team}`, presets: presets.map((p) => p.name) })
    }
    const r = tpl && role ? (tpl.roles || []).find((x) => x.role === role) : null
    if (tpl && role && !r) {
      return JSON.stringify({ error: `${team} has no role ${role}`, roles: (tpl.roles || []).map((x) => x.role) })
    }
    const raw = await call('check_state', rest)
    let v
    try { v = JSON.parse(raw) } catch { return raw }
    const modes = mod.modes || []
    let m
    if (!modes.includes(v.reason)) {
      m = { return: false, advice: v.advice, basis: `${v.reason} is not a drift mode` }
    } else if (!r) {
      m = { return: true, advice: v.advice, basis: 'unstyled — every drift returns' }
    } else {
      const acts = (r.modes && r.modes.length) ? r.modes : ((mod.depths || {})[r.recurse] || [])
      const ret = acts.includes(v.reason)
      m = {
        return: ret,
        advice: ret ? (r.return || v.advice) : `${r.role} (recurse: ${r.recurse}) tolerates ${v.reason} — recursing on.`,
        basis: `${r.role} recurses ${r.recurse}`,
      }
    }
    m.team = tpl ? tpl.name : null
    m.role = r ? r.role : null
    return JSON.stringify({ ...v, modulation: m })
  }
  if (name === 'phronesis') return JSON.stringify(judgeWork())
  if (name === 'check_state') {
    const { goal, progress, distance, parent_goal, doing, next, blocked } = args || {}
    const record = (drifting, reason, advice, phi = 0, extra = {}) => {
      const step = drift.trace.length + 1
      drift.trace.push({ step, reason, phi: Number(phi.toFixed(2)) })
      // The trace records the READING; the cycle is a fact about the sequence, so the
      // original goes in and `oscillating` comes out. drift.osc keeps it from re-firing
      // every step once a cycle is established.
      //
      // GROUND FIRST, then readings. x = [x, f(x)] — the ground is x, the verdicts are
      // f(x), and a cycle in x is what this verdict was built to name. Cycling on verdicts
      // alone meant a genuinely circling agent was caught only when its readings ALSO
      // happened to repeat periodically, which is a coincidence stacked on the thing we
      // wanted. The reading pass is kept: a repeating verdict over a moving ground is a
      // real pattern, just a different one.
      drift.trail = [...(drift.trail ?? []), goal ? [...toWords(goal)].sort().join('|') : '']
      let period = cyclePeriod(drift.trail)
      let of = 'ground'
      if (!period) { period = cyclePeriod(drift.trace.map(t => t.reason)); of = 'reading' }
      if (period && !drift.osc) {
        drift.osc = true
        drifting = true
        reason = 'oscillating'
        const what = of === 'ground'
          ? 'You have returned to the same goals in a repeating order'
          : 'Your reading has cycled'
        advice = `${what} with period ${period} — you have been told to return and have come back to the same place. Re-ground explicitly instead of returning again.`
      } else if (!period) {
        drift.osc = false
      }
      // Low-data corpus: only the fires, with just enough to judge later whether
      // it was a true catch or a false alarm.
      //
      // `agent` added 2026-07-25. Without it the corpus was unattributable: 26 verdicts
      // across 15 runs with no way to tell Claude's from Grok's, because the run uuids
      // matched no session file. "Do two agents drift differently under one instrument"
      // is the cheapest real study this project has and it was unanswerable for one
      // missing field. AGENT is already read from LASERBRAIN_AGENT at the top — it
      // simply was never written down.
      // The laserscore exists exactly when the state is grammatical, which is why it is
      // computed from the same condition the ungrammatical verdict tests rather than from a
      // flag passed in. A null here is not a missing field -- it is the finding.
      const score = (goal && String(goal).trim() && PROGRESS.has(progress))
        ? laserscore({ goal, progress, distance }, parent_goal)
        : null
      // EVERY step, not only the fires. The original policy was quality over quantity —
      // log the drift moments, skip the rest — and it made the corpus structurally unable
      // to answer a sequence question. `oscillating` needs six consecutive readings; only
      // 4 of 35 recorded runs had six of anything, because the steps between fires were
      // discarded. A verdict about a sequence cannot be validated against a log that keeps
      // only the interesting moments. `drifting` stays a field, so the old view is one
      // filter away and nothing that read this file has lost anything.
      // WHICH INSTRUMENT WROTE THIS ROW.
      //
      // The corpus already spans two logging eras and could not say so. Until 2026-07-28
      // only drift moments were logged, so every row was a fire and `drifting` did not
      // exist as a field; afterwards every step is logged and the field carries the
      // answer. Pooling the two is not a small error — a rate computed across them has a
      // denominator from one policy and a numerator from the other, and nothing in the
      // data says to stop. It produced three wrong statistics in one sitting: a fire rate
      // of 22% that is really 24.8%, fifty rows read as "an interrupt verdict that did
      // not interrupt" when the field simply had not been invented, and an agent
      // comparison quoted at p=0.07 whose entire sample predates the era it was compared
      // against.
      //
      // A version per row makes the seam visible. grammar_version because a schema change
      // is what moves the meaning of a row, and sdk so a behaviour change with no schema
      // change is still attributable.
      logDrift({ ts: new Date().toISOString(), run: runId, agent: AGENT, step, reason, drifting,
        phi: Number(phi.toFixed(2)), laserscore: score, goal, progress, distance: asDist(distance),
        dist_recent: drift.distHist.slice(-4),
        grammar_version: GRAMMAR.laserbrain_grammar ?? null,
        logged_by: 'lasermind/mcp-server.mjs', ...extra })
      const obs = observedProgress()
      // Reported only when it DISAGREES. A field that always appears gets skimmed; one
      // that appears when the trace contradicts the claim is worth reading.
      const contrast = (obs && progress && obs.progress !== progress)
        ? { observed: obs.progress, observed_over: obs.steps }
        : {}
      // GOAL SCORE — computed since the beginning, reported only on failure until now.
      // The overlap between the goal just spelled and the one this run started with is
      // what decides goal-drift, and it was interpolated into the advice STRING at the
      // moment it fell below the floor and invisible at every other step. So the one
      // number that says how far the subject has travelled could only be read once it had
      // already gone too far. Φ answers "how far from ground", this answers "still the
      // same errand?", and they are different questions: a faithful goal can sit at high
      // Φ while it is genuinely hard, and a low-Φ reading can belong to a different task.
      const _g = new Set(toWords(goal)), _f = new Set(drift.firstGoal ?? [])
      let _i = 0; for (const x of _g) if (_f.has(x)) _i++
      const goal_score = _f.size ? Number((_i / (new Set([..._g, ..._f]).size || 1)).toFixed(2)) : 1
      // Recorded every step, not just the fires: a context whose history exists only for
      // its bad moments cannot answer "did this ever work".
      const ctx = contextId(goal)
      const { repetition } = rememberContext(ctx, goal, distance, reason, runId, score)
      // laserbrain calls phronesis itself, rather than waiting to be asked.
      //
      // A tool the agent has to REMEMBER to call is a tool that does not run. Coverage on
      // this machine sits near 24% with a gate interrupting every four steps, so a
      // judgment available only on request would reach roughly a quarter of the moments it
      // exists for — and never the ones that matter, because an agent deep in a loop is
      // precisely the agent not thinking to ask whether it is in one.
      //
      // Attached only for the verdicts that change what to do next. `continue` and
      // `finish` are the healthy majority (94% of the corpus after calibration) and a
      // field that appears every step gets skimmed; one that appears when the work itself
      // is in question is worth reading. Same reasoning as `contrast` above.
      let judgment
      try {
        const j = judgeWork()
        if (j && j.verdict && !['continue', 'finish', 'ungrounded'].includes(j.verdict)) {
          judgment = { verdict: j.verdict, because: j.because, counsel: j.counsel }
        }
      } catch { /* judgment is an addition to the reading, never a precondition for it */ }
      // Present only when the agent actually spelled a carried field AND a phrase matched.
      // An absent key means "not measured", which is different from a low score and must
      // not be reported as one — the same rule `contrast` and `judgment` follow above.
      const claims = markCeiling(doing, next, blocked)
      return JSON.stringify({ drifting, reason, laserscore: score, phi: Number(phi.toFixed(2)),
        goal_score, context: ctx, ...extra, ...(claims ? { claims } : {}),
        // Only once it means something. Writing a state once is the normal case and a 1
        // here would be noise on every healthy step.
        ...(repetition > 1 ? { repetition } : {}),
        anchored: anchored(), ...contrast,
        ...(judgment ? { judgment } : {}), advice })
    }
    if (!goal || !String(goal).trim() || !PROGRESS.has(progress))
      return record(true, 'ungrammatical', 'You cannot spell a clear goal and a valid progress. Stop and return to ground.')
    if (!drift.ground) {
      drift.ground = { goal, progress, distance: asDist(distance) }
      drift.firstGoal = [...toWords(goal)]
      drift.distHist = [asDist(distance)]
      runId = (globalThis.crypto?.randomUUID?.() ?? String(Date.now()))
      return record(false, 'grounded', 'Ground state set — this is where you started. Continue, and check_state each step.')
    }
    const phi = displacement({ goal, progress, distance }, drift.ground)
    if ((progress === 'stuck' || progress === 'circling') && phi > SELF_REPORT_MIN)
      return record(true, `self-report:${progress}`, `You reported ${progress} and have moved from ground. Return to your goal.`, phi)
    const g = toWords(goal), first = new Set(drift.firstGoal)
    let inter = 0; for (const x of g) if (first.has(x)) inter++
    const anchor = inter / (new Set([...g, ...first]).size || 1)
    if (anchor < GOAL_MIN) {
      // A goal that changed right after the user spoke was REPLACED, not drifted from.
      // goal-drift was 24 of 35 fires in the recovered corpus with zero coinciding real
      // errors, and 22 of those 24 were the first check after Diego spoke. The rule was
      // right that the subject changed and wrong about what that meant.
      //
      // consumeUserTurn() DELETES the flag, and that is the load-bearing part: it licenses
      // exactly one re-ground per user turn. Merely reading it would exempt an agent that
      // wandered for twenty steps after a redirection, which is the real drift this
      // instrument exists to catch.
      if (consumeUserTurn()) {
        drift.ground = { goal, progress, distance: asDist(distance) }
        drift.firstGoal = [...g]
        drift.distHist = [asDist(distance)]
        return record(false, 'reground', 'New instruction — ground reset to the goal you just stated.')
      }

      // QUANTIZED RECURSION — the excursion case.
      //
      // The grammar is a discrete measurement grid: distance is 11 integers, progress is
      // 3 enum values, and `goal` is ONE slot. An agent inside a legitimate sub-task holds
      // two goals at once — the parent it still serves and the branch it is on — and the
      // single slot forces it to spell one. It spells the branch, overlap with ground
      // collapses, and the quantization error is reported as drift.
      //
      // That is not a flaw in Φ's arithmetic. Φ is measuring exactly what it was handed.
      // The loss happens BEFORE the measurement, when a two-valued state is written into
      // a one-valued field.
      //
      // So the grammar gains the missing slot rather than the detector gaining a rule. An
      // agent that can say "this branch serves that parent" is measured against whichever
      // it declares live, and the fire becomes an `excursion` — recorded, counted, and NOT
      // called drift.
      //
      // Strictly additive: a call without parent_goal takes the identical path it took
      // before, so the frozen instrument stays frozen and the old corpus stays comparable.
      let rejectedParent = null
      if (parent_goal && String(parent_goal).trim()) {
        const p = toWords(parent_goal)
        let pin = 0; for (const x of p) if (first.has(x)) pin++
        const panchor = pin / (new Set([...p, ...first]).size || 1)
        if (panchor >= GOAL_MIN) {
          return record(false, 'excursion',
            `On a sub-task (overlap ${anchor.toFixed(2)}) that still serves your ground goal ` +
            `(parent overlap ${panchor.toFixed(2)}). Not drift — but the parent is what you owe.`,
            phi)
        }
        // A DECLARATION THAT FALLS SHORT MUST NOT VANISH. Below the floor this dropped
        // straight through to goal-drift, whose advice then said "If this is a sub-task,
        // pass parent_goal" — to an agent that had just passed one. All 3 parents ever
        // declared in this corpus were rejected exactly here (0.03, 0.04, 0.17 against a
        // 0.30 floor) and none was ever mentioned, which is why the field looks broken and
        // adoption sits at 0.2%. The THRESHOLD is deliberately not touched: three rejected
        // declarations cannot choose a replacement measure, and making the rejection
        // legible is what generates the data to settle it.
        rejectedParent = panchor
      }
      // Name the remedy, not just the fault. There are three ways a goal legitimately
      // stops matching ground, and the verdict used to describe none of them:
      //   the user redirected you        -> reset_task, which re-grounds honestly
      //   you are on a sub-task          -> pass parent_goal, and this becomes an excursion
      //   you really did wander off      -> return to the goal you started with
      // Only the third is drift. On 2026-07-25 the agent hit the first two roughly
      // fifteen times between them and returned to ground each time, because the advice
      // said 'you are solving something else' and offered no other reading. A verdict
      // that names one cause teaches the agent that cause is the only one.
      if (rejectedParent !== null) {
        // Never tell an agent to do the thing it just did.
        return record(true, 'goal-drift', `Your goal no longer matches the one you started with `
          + `(overlap ${anchor.toFixed(2)}). You DID declare a parent, and it was measured at `
          + `${rejectedParent.toFixed(2)} against your ground — below the ${GOAL_MIN.toFixed(2)} `
          + `floor, so this reads as drift rather than an excursion. Either the parent is not the `
          + `goal this serves, or it shares too little wording with it to be recognised. `
          + `If the user redirected you, call reset_task.`, phi, { parent_overlap: Number(rejectedParent.toFixed(2)) })
      }
      return record(true, 'goal-drift', `Your goal no longer matches the one you started with (overlap ${anchor.toFixed(2)}). `
        + `If the user redirected you, call reset_task. If this is a sub-task, pass parent_goal. `
        + `Otherwise you are solving something else — return.`, phi)
    }
    drift.distHist.push(asDist(distance))
    const dh = drift.distHist
    if (dh.length > STALL_WINDOW && Math.min(...dh.slice(-STALL_WINDOW)) >= dh[dh.length - STALL_WINDOW - 1])
      return record(true, 'stalled', `Distance stopped falling (${dh.slice(-4).join(', ')}). Motion without progress is a loop — return.`, phi)
    return record(false, 'advancing', `On track (Φ=${phi.toFixed(2)}). Continue.`, phi)
  }
  throw new Error(`no such tool: ${name}`)
}

// ---- JSON-RPC over stdio. No SDK: three methods is not worth a dependency.
const send = (msg) => process.stdout.write(JSON.stringify(msg) + '\n')

let buf = ''
process.stdin.on('data', async (chunk) => {
  buf += chunk
  let i
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim()
    buf = buf.slice(i + 1)
    if (!line) continue
    let req
    try { req = JSON.parse(line) } catch { continue }

    // Notifications have no id and must never be answered.
    if (req.id === undefined) continue

    try {
      if (req.method === 'initialize') {
        send({
          jsonrpc: '2.0', id: req.id,
          result: {
            protocolVersion: '2024-11-05',
            capabilities: { tools: {} },
            // 1.1.0 → 1.2.0 on 2026-07-26. This had not moved while the server's
            // RESPONSE SHAPE changed (check_state now returns `laserscore`) and its
            // VERDICTS changed (self-report floor 0 → 0.15, stall window 3 → 4). A
            // client handshaking with this server was told 1.1.0 and handed something
            // else. This is the server's own version and does not track the grammar,
            // which is at 1.2.1 on its own scheme — the two matching at 1.1.0 was a
            // coincidence that made the staleness harder to see.
            serverInfo: { name: 'laserbrain', version: GRAMMAR.laserbrain_grammar ?? 'offline' },
          },
        })
      } else if (req.method === 'tools/list') {
        send({ jsonrpc: '2.0', id: req.id, result: { tools: TOOLS } })
      } else if (req.method === 'tools/call') {
        const text = await call(req.params?.name, req.params?.arguments)
        send({ jsonrpc: '2.0', id: req.id, result: { content: [{ type: 'text', text }] } })
      } else {
        send({ jsonrpc: '2.0', id: req.id, error: { code: -32601, message: `method not found: ${req.method}` } })
      }
    } catch (e) {
      // Surfaced as a tool error, not a crash: the hub being down is a fact
      // about the field, and the caller should be told rather than left waiting.
      send({
        jsonrpc: '2.0', id: req.id,
        result: { content: [{ type: 'text', text: `laserbrain: ${e.message} (hub ${HUB})` }], isError: true },
      })
    }
  }
})
