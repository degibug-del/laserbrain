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
import { appendFile, mkdir } from 'node:fs/promises'
import { existsSync, unlinkSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HUB = process.env.LASERBRAIN_HUB || 'https://phronesis.world/api/laserbrain'
// Which mind is holding this MCP process. Claude and Grok both speak into the
// same field; the tandem log is how they share *data* about what they did there.
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
// Path override: LASERBRAIN_TANDEM_LOG.
const TANDEM_LOG = process.env.LASERBRAIN_TANDEM_LOG || join(homedir(), '.config', 'laserbrain', 'tandem.jsonl')
let runId = null // groups a task's drift fires; set when ground is set
function logDrift(entry) {
  mkdir(dirname(DRIFT_LOG), { recursive: true })
    .then(() => appendFile(DRIFT_LOG, JSON.stringify(entry) + '\n'))
    .catch(() => {})
}
function logTandem(entry) {
  const row = {
    ts: new Date().toISOString(),
    agent: AGENT,
    hub: HUB,
    ...entry,
  }
  return mkdir(dirname(TANDEM_LOG), { recursive: true })
    .then(() => appendFile(TANDEM_LOG, JSON.stringify(row) + '\n'))
    .then(() => row)
    .catch((e) => ({ error: String(e.message || e), ...row }))
}
async function readTandem(limit = 20) {
  const { readFile } = await import('node:fs/promises')
  try {
    const raw = await readFile(TANDEM_LOG, 'utf8')
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
const GRAMMAR = JSON.parse(
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'grammar.json'), 'utf8'))
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
const _STOP = new Set(['the','a','an','to','of','and','or','for','in','on','at','is','it','this',
  'that','with','my','your','our','i','we','be','as','by','from','into','out','up','so','then'])
const _STEM = /(ings?|edly|ed|ers?|es|s|tion|ment)$/
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
const laserscore = (s, parent) => {
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
const GOAL_MIN = 0.30
const SELF_REPORT_MIN = 0.15
const STALL_WINDOW = 4

const displacement = (s, g) =>
  0.5 * jac(toWords(s.goal), toWords(g.goal)) + 0.3 * Math.abs(asDist(s.distance) - g.distance) / 10 + 0.2 * (s.progress === g.progress ? 0 : 1)
let drift = { ground: null, firstGoal: [], distHist: [], trace: [] }

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
      'also written to the tandem log so the other agent can see it.',
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
    name: 'tandem_whoami',
    description:
      'Which agent this MCP process is (claude|grok|…), which hub it shares, and where the tandem log lives. ' +
      'Claude and Grok share the same laserfield hub and the same tandem.jsonl on this machine.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'tandem_write',
    description:
      'Write a structured handoff or note into the shared tandem log for the other agent. ' +
      'Use kind: handoff | note | goal | done | claim | wave_open | wave_close. ' +
      'Keep goal identical across agents when tandeming. ' +
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
    name: 'tandem_read',
    description:
      'Read recent entries from the shared Claude↔Grok tandem log (field speaks + handoffs). ' +
      'Call at session start and when picking up work from the other agent.',
    inputSchema: {
      type: 'object',
      properties: {
        limit: { type: 'number', description: 'How many recent entries (default 20, max 200).' },
      },
    },
  },
]

async function call(name, args) {
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
    await logTandem({ kind: 'field_speak', words: joined, reply, signal })
    return typeof reply === 'string' ? `[${AGENT}] ${reply}` : JSON.stringify({ agent: AGENT, reply, signal })
  }
  if (name === 'tandem_whoami') {
    return JSON.stringify({
      agent: AGENT,
      hub: HUB,
      tandem_log: TANDEM_LOG,
      drift_log: DRIFT_LOG,
      shared: 'Claude and Grok both use this hub for weather and this tandem_log for handoffs on the same machine.',
    })
  }
  if (name === 'tandem_write') {
    const kind = String(args?.kind || 'note').toLowerCase()
    const text = String(args?.text || '').trim()
    if (!text) throw new Error('tandem_write needs text')
    const ALLOWED_KINDS = new Set([
      'handoff', 'note', 'goal', 'done', 'claim', 'field_speak',
      'wave_open', 'wave_close',
    ])
    if (!ALLOWED_KINDS.has(kind)) throw new Error(`tandem_write kind must be one of ${[...ALLOWED_KINDS].join('|')}; got ${kind}`)
    let payload = args?.payload && typeof args.payload === 'object' ? { ...args.payload } : undefined
    // wave_open without id: assign next integer after last wave in the log
    if (kind === 'wave_open') {
      payload = payload || {}
      if (payload.wave == null) {
        try {
          const prev = await readTandem(200)
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
    const row = await logTandem({
      kind,
      text,
      goal: args?.goal ? String(args.goal).slice(0, 400) : undefined,
      payload,
    })
    return JSON.stringify(row)
  }
  if (name === 'tandem_read') {
    const entries = await readTandem(args?.limit)
    return JSON.stringify({ agent: AGENT, hub: HUB, path: TANDEM_LOG, n: entries.length, entries })
  }
  if (name === 'drift_grammar') return JSON.stringify(GRAMMAR)
  if (name === 'reset_task') { drift = { ground: null, firstGoal: [], distHist: [], trace: [] }; runId = null; return 'reset — ground and history cleared. Your next check_state sets a new ground.' }
  if (name === 'get_history') return JSON.stringify({ steps: drift.trace.length, trace: drift.trace })
  if (name === 'check_state') {
    const { goal, progress, distance, parent_goal } = args || {}
    const record = (drifting, reason, advice, phi = 0) => {
      const step = drift.trace.length + 1
      drift.trace.push({ step, reason, phi: Number(phi.toFixed(2)) })
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
      if (drifting) logDrift({ ts: new Date().toISOString(), run: runId, agent: AGENT, step, reason, phi: Number(phi.toFixed(2)), laserscore: score, goal, progress, distance: asDist(distance), dist_recent: drift.distHist.slice(-4) })
      return JSON.stringify({ drifting, reason, laserscore: score, phi: Number(phi.toFixed(2)), advice })
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
            serverInfo: { name: 'laserbrain', version: '1.1.0' },
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
