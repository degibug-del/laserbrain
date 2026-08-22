// The one grammar, synced from lasermind/grammar.json by scripts/sync-grammar.mjs and
// bundled at build time — a Worker has no filesystem to read it from at runtime.
import GRAMMAR from './grammar.js'

// The smart recursion harness — the pure drift check, shared by the MCP tools
// (index.ts) and the metered observability ingest (api.ts). One source of truth.
// A fixed reference (the ground) catches drift that self-watching cannot — PROOF.md.
//
// ┌─ The published instrument (worker 6b483de7) ────────────────────────────────┐
// │ The freeze is lifted — the H1 run is complete and reported. But the studies  │
// │ (lasermind/RETEST.md, and the public /laserbrain/research page)    │
// │ ran on THIS metric and return criterion, so it is the detector the public    │
// │ research describes. Change it deliberately: if you alter the metric, note it  │
// │ and re-version on the research page so the record stays honest. Frozen values │
// │ are recorded in RETEST.md § FREEZE.                                          │
// └─────────────────────────────────────────────────────────────────────────────┘

export type DriftState = {
  ground: { goal: string; progress: string; distance: number } | null
  firstGoal: string[]
  distHist: number[]
  // Whole-run twins of distHist and the osc latch — NOT reset on a reground, because the
  // rules whose subject is the whole run (a cycle in the ground) have no subject without
  // them. See the Python dist_all declaration for the failure that produced them.
  distAll: number[]
  oscFires: number
  // Experiment + outcome metadata (run-level), set through the ingest. `pair`
  // groups a treatment/control pair for the H1 A/B; `arm` says which side this
  // run is; `outcome`/`score` record whether the task actually succeeded — so
  // cost can be read against SUCCESS, not just against fewer steps.
  pair?: string
  arm?: 'treatment' | 'control'
  outcome?: string
  score?: number
  // Whether an oscillation has already been reported for the cycle currently at the tail
  // of the trace. Without it `oscillating` re-fires on every step once a cycle is
  // established, which buries the one message that matters under repetition.
  osc?: boolean
  // `tokens`/`overhead` are per-step cost accounting; `drifting` records the
  // verdict so alerts can fire on the transition into drift without re-deriving
  // it from the reason (which a soft, unconfirmed drift also carries).
  trace: { step: number; reason: string; phi: number; drifting?: boolean; tokens?: number; overhead?: boolean }[]
  // The canonical spelling of the GROUND at each step. Optional because this state is
  // persisted in a Durable Object and sessions that started before 2026-07-27 have no
  // such field — every read goes through `st.trail ?? []` for that reason.
  //
  // It exists because of x = [x, f(x)]. The state is the PAIR, ground and measurement,
  // and `trace` only ever held the measurement. Cycling on verdicts alone was cycling on
  // f(x), so a genuinely circling agent was caught only when its READINGS also happened
  // to repeat periodically — a coincidence on top of the thing being detected.
  trail?: string[]
  // The full canonical spelling at each step, where `trail` holds only the GROUND's
  // tokens. Both are needed and they answer different questions: a repeated trail entry
  // means you came back to the same goal, a repeated `scores` entry means goal, progress
  // AND distance are all unchanged — the same sentence written twice, which is a stronger
  // claim than the stall rule can make from distance alone.
  //
  // Optional for the same reason `trail` is: this state lives in a Durable Object and
  // sessions that started before it existed have no such field, so every read goes
  // through `st.scores ?? []`.
  scores?: string[]
}

export const emptyDrift = (): DriftState => ({ ground: null, firstGoal: [], distHist: [], distAll: [], oscFires: 0, trace: [], trail: [] })

// A trace step's reason, classified. The Verdict carries `drifting` for the
// current step; for a PAST step only the reason is stored, so alerts (which fire
// on the edge into drift) need this to read the previous step's state.
export const isDrift = (reason: string): boolean =>
  reason === 'ungrammatical' || reason === 'goal-drift' || reason === 'stalled' || reason.startsWith('self-report')

const PROGRESS = new Set(['advancing', 'stuck', 'circling'])
export const asDist = (d: unknown) => { const n = parseInt(String(d), 10); return isNaN(n) ? 5 : Math.max(0, Math.min(10, n)) }

// Normalised goal words. Raw-word Jaccard fired "goal-drift" on trivial variation
// — "build the parser" vs "build a parser", "parsing" vs "parser" — so the metric
// mistook rephrasing for drift. Dropping stopwords and a light suffix stem makes
// overlap robust to that, which is the point: measure the goal, not its wording.
// Still deterministic and symmetric, so Φ remains a well-defined pseudometric.
// Read, not retyped. These were duplicated here, in the SDK, in mcp-server.mjs and in
// three lasermind scripts — six copies of one list that a gate existed solely to police.
const STOP = new Set<string>(GRAMMAR.normalizer?.stopwords ?? [])
const STEM = new RegExp(GRAMMAR.normalizer?.stem_pattern ?? '(ings?|edly|ed|ers?|es|s|tion|ment)$')
const stem = (w: string) => (w.length > 4 ? w.replace(STEM, '') : w) || w
export const norm = (s: string) => {
  const out = new Set<string>()
  for (const w of (s || '').toLowerCase().match(/[a-z0-9']+/g) || []) { if (STOP.has(w)) continue; const r = stem(w); if (r) out.add(r) }
  return out
}
const jac = (a: Set<string>, b: Set<string>) => {
  if (a.size === 0 && b.size === 0) return 0
  let inter = 0; for (const x of a) if (b.has(x)) inter++
  return 1 - inter / new Set([...a, ...b]).size
}
// Φ's weights come from the grammar too. They were literals here, in the SDK's
// Calibration defaults and in mcp-server.mjs — and Φ is the number the whole product is
// about, so three hand-kept copies of its weighting is the last place drift should live.
const W = GRAMMAR.calibration?.weights ?? {}
// Was the literal 0.30 in two places. Python reads cal.goal_min from this same file,
// so a calibration change would have moved one implementation and not the other.
const GOAL_MIN: number = GRAMMAR.calibration?.goal_min ?? 0.30
const W_GOAL = W.goal ?? 0.5
const W_DIST = W.distance ?? 0.3
const W_PROG = W.progress ?? 0.2

// The Worker BUNDLES the grammar at build time, so it cannot be missing at runtime — but
// it can be malformed, and a stopword set that silently arrives empty would change every Φ
// on the endpoint while every version string still matched. Fail the build, loudly.
if (STOP.size === 0) throw new Error('grammar.json carries no stopwords — refusing to serve a normaliser that drops nothing')

export const displacement = (
  s: { goal: string; progress: string; distance: unknown },
  g: { goal: string; progress: string; distance: number },
) => W_GOAL * jac(norm(s.goal), norm(g.goal)) + W_DIST * Math.abs(asDist(s.distance) - g.distance) / 10 + W_PROG * (s.progress === g.progress ? 0 : 1)


/**
 * The period of a repeating cycle at the tail of the trace, or 0.
 *
 * Falls out of x = [x, f(x)]: a fixed-point iteration either converges, diverges or
 * CYCLES. The harness had a verdict for the first two and nothing for the third, so an
 * agent bouncing between two grounds got a correct verdict every step and was never told
 * the SEQUENCE was the problem. Ported from the SDK 2026-07-27; check-drift-parity keeps
 * the two identical.
 *
 * Whole repeats only, and more than one distinct reading — a constant tail is a settled
 * state, not an oscillation.
 *
 * PERIODS 2..6, not 2..3 (widened 2026-07-27). The original range missed the canonical
 * example of the equation it was derived from: x = [sin, f(x)] with f = d/dx cycles
 * sin -> cos -> -sin -> -cos, period FOUR. Sixteen readings, four whole repeats, and this
 * returned 0. Nothing failed — a range that is too narrow does not throw, it answers "no
 * cycle", and every reading beneath it looks healthy.
 *
 * This is the FOURTH copy of the rule (SDK, local MCP server, grammar.json, here). The
 * first fix landed in the other three and left this one — which is what an agent on the
 * hosted endpoint actually calls, so the endpoint returned `stalled` where the package
 * returned `oscillating`, on identical input. Change all four or none.
 *
 * Ascending order matters: [a,b,a,b,a,b] is period 2 and also satisfies 4; the smaller is
 * the true one, so the first match wins. `need` is max(6, 2p) — two whole repeats with a
 * floor of six, which leaves p=2 and p=3 at exactly their previous behaviour.
 */
export function cyclePeriod(reasons: string[]): number {
  for (let p = 2; p <= 6; p++) {
    const need = Math.max(6, 2 * p)
    if (reasons.length < need) continue
    const tail = reasons.slice(-need)
    if (new Set(tail).size < 2) continue
    if (tail.every((r, i) => r === tail[i % p])) return p
  }
  return 0
}

export type Verdict = {
  drifting: boolean; reason: string; phi: number; advice: string; laserscore: string | null
  // How much of the goal just spelled is still the goal this run started with. Computed
  // here since the beginning to decide `goal-drift`, and reported only inside the advice
  // STRING at the moment it crossed the floor — so the one number saying how far the
  // SUBJECT had travelled could only be read once it had already gone too far. Φ asks
  // "how far from ground"; this asks "still the same errand?", and they differ: a faithful
  // goal sits at high Φ when the work is hard, and a low-Φ reading can belong to a task
  // nobody asked for.
  goal_score: number
  // A stable name for the work itself, identical to the SDK's context_id and the local
  // server's contextId. The same context reached through this Worker and through the
  // package must carry the same name, or the identifier is worse than none.
  context: string | null
  // Times this EXACT spelling has been written in this context. Present only when >1.
  repetition?: number
  // What only history knows: sessions BEFORE this one that opened this context, and the
  // closest it has ever come to done. Present only when the store has seen it before, so
  // their absence is "no prior sightings recorded", never a claim of a first visit.
  recurrence?: number
  ceiling?: number | null
  // Judgment, attached only when it is one that changes what to do next. See judgeRun.
  judgment?: { verdict: string; because: string; counsel: string }
}

/**
 * A stable name for the context a goal belongs to.
 *
 * FNV-1a over the canonical token string, byte-identical to `context_id` in the SDK and
 * `contextId` in lasermind/mcp-server.mjs — "build the parser" and "building a parser"
 * both name ctx_1sax889, in all three.
 *
 * This Worker is the surface most attached agents actually talk to, and it was the last
 * to gain the laserscore for exactly that reason. Adding the identifier here at the same
 * time as everywhere else is the point: an id that differs between implementations is
 * worse than no id at all.
 */
export const contextId = (goal?: string): string | null => {
  const toks = goal ? [...norm(goal)].sort().join('|') : ''
  if (!toks) return null
  let h = 0x811c9dc5
  for (let i = 0; i < toks.length; i++) {
    h ^= toks.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return 'ctx_' + h.toString(36)
}

/**
 * The written form, canonical: ⟨sorted|tokens⟩ progress dN.
 *
 * Added 2026-07-27. The SDK has returned this since 0.4.3 and the local MCP server
 * since 1.2.0, and grammar 1.2.1 — which this Worker itself serves via drift_grammar —
 * defines it. The Worker was the only surface that did not produce one, which is the
 * surface every attached agent actually talks to. Six scenarios were compared against
 * the SDK: all six verdicts matched exactly, and all six were missing the laserscore.
 *
 * Null exactly when ungrammatical, and that null is not an omission — it is the first
 * detection, arriving before any arithmetic exists.
 */
export const laserscore = (goal?: string, progress?: string, distance?: unknown,
                           parentGoal?: string): string | null => {
  if (!goal || !String(goal).trim() || !progress || !PROGRESS.has(progress)) return null
  const base = `⟨${[...norm(goal)].sort().join('|')}⟩ ${progress} d${asDist(distance)}`
  // A declared parent is part of the SPELLING, not just of the verdict. Python appends the
  // containment notation, and omitting it here made the two instruments disagree on the
  // laserscore while agreeing on every verdict and Φ — the kind of divergence that only
  // shows up once the vectors actually declare a parent.
  const pg = (parentGoal ?? '').trim()
  return pg ? `${base} ⊂ ⟨${[...norm(pg)].sort().join('|')}⟩` : base
}

// Advance one step. Returns the verdict AND the next state (caller persists it).
// st is not mutated; a new state object is returned.
/**
 * Judgment on the work, beside the measurement of the state.
 *
 * Φ is a distance and is silent on whether the journey is worth making. An agent can hold
 * a perfect goal score, report advancing honestly, sit at Φ=0.05 — and be twelve checks
 * into work that has not moved the distance once, which every verdict above calls
 * `advancing` because by its own definition it is.
 *
 * Verdicts and thresholds match `judgeWork` in lasermind/mcp-server.mjs and
 * `_Run.phronesis` in the SDK, including the ones that were wrong first and got fixed by
 * replaying the recorded corpus: `pace <= 0` is required before calling a repeating or
 * cycling run wrong-problem (it fired on a run that closed 5→1), the stall-driven narrow
 * needs `now >= 4` (it told runs at distance 1 to split the goal), and nothing hard fires
 * under three checks (two readings is a rumour).
 *
 * `mem` carries what only history knows — how many earlier SESSIONS opened this context
 * and the closest it has ever come. It arrives from the ContextStore DO and is null when
 * that store could not be reached, which is why every use of it is guarded: a memory
 * outage must degrade judgment rather than invent a fact. Absent memory reads as "no
 * evidence of recurrence", never as "definitely first time".
 *
 * IF YOU ADD `reground` HERE, ADD `groundAt` WITH IT. This Worker has no user-turn signal
 * and therefore no reground, which is the only reason `steps = trace.length` is safe below.
 * The SDK and the local MCP server DO reground, and both carried a bug for it: a reground
 * re-zeroes distHist but not the trace, so `steps >= 12 && closed <= 0` became true by
 * construction on the FIRST check of a replaced goal — handing an agent "stop, this is not
 * reachable" about work nobody had started. Observed live 2026-08-04; fixed there by
 * measuring progress from a recorded ground index while leaving the sequence rules
 * (oscillation, drifts-vs-regrounds) on the whole trace. See lasermind/test_windup.py.
 */
export function judgeRun(
  st: DriftState,
  mem?: { repetition: number; recurrence: number; ceiling: number | null } | null,
): { verdict: string; because: string; counsel: string } | null {
  const dh = st.distHist ?? [], trace = st.trace ?? []
  const steps = trace.length
  if (!st.ground || !steps) return null
  const started = dh[0], now = dh[dh.length - 1]
  const closed = (started != null && now != null) ? started - now : 0
  const pace = steps ? closed / steps : 0
  const reasons = trace.map((t) => t.reason)
  const count = (r: string) => reasons.filter((x) => x === r).length
  const stalls = count('stalled'), goalDrifts = count('goal-drift')
  const regrounds = count('reground')
  // NOT count('oscillating'): the trace holds the READING the cycle was found in and never
  // the word, so this was always 0 and the wrong-problem branch unreachable.
  const oscillations = st.oscFires ?? 0
  // Whole-run progress for the whole-run rule, from the run's WORST point so a reground to
  // a harder goal is not charged as lost ground.
  const da = st.distAll ?? []
  const runPace = da.length >= 2 ? (Math.max(...da) - da[da.length - 1]) / Math.max(1, steps) : 0

  let flat = 0
  for (let i = dh.length - 1; i > 0; i--) { if (dh[i] >= dh[i - 1]) flat++; else break }

  // In-run count as the floor, the store's cross-session count when it is available.
  // The store's is >= the run's by construction, since it has seen this run too.
  const spellings = st.scores ?? []
  const counts: Record<string, number> = {}
  for (const s of spellings) counts[s] = (counts[s] ?? 0) + 1
  const inRun = Math.max(0, ...Object.values(counts), 0)
  const repetition = Math.max(inRun, mem?.repetition ?? 0)
  const recurrence = mem?.recurrence ?? 0
  const ceiling = mem?.ceiling ?? null

  const judged = steps >= 3
  if (judged && steps >= 12 && closed <= 0)
    return { verdict: 'abandon',
      because: `${steps} checks. Distance began at ${started} and stands at ${now} — it has never once improved.`,
      counsel: 'Stop. Either the approach is wrong or the goal is not reachable as stated. Say plainly what is blocking it rather than taking a thirteenth run at it.' }
  if (judged && recurrence >= 2 && closed <= 0)
    // The reading no single run can produce. A run watching itself sees one attempt and
    // cannot know it is the fourth; only the store can say the context has been opened
    // before and closed none of those times.
    return { verdict: 'abandon',
      because: `This context has been opened in ${recurrence} earlier sessions and closed in none. Best distance ever reached is ${ceiling}; this run has closed ${closed}.`,
      counsel: 'A problem that resists three separate attempts is usually the wrong problem. Change the approach or hand it back before spending another session.' }
  if (judged && goalDrifts >= 3 && goalDrifts > regrounds && pace <= 0)
    return { verdict: 'wrong-problem',
      because: `The goal has failed its overlap check ${goalDrifts} times against only ${regrounds} legitimate re-grounds.`,
      counsel: 'You are not solving what you set out to solve. Either re-ground to the goal you actually have, or return to the original and finish it.' }
  if (judged && oscillations > 0 && runPace <= 0)
    return { verdict: 'wrong-problem',
      because: 'A repeating cycle was detected and the distance is not falling.',
      counsel: 'Returning again will land you here a third time. Change the approach, not the position.' }
  if (judged && repetition >= 3 && pace <= 0)
    return { verdict: 'repeating',
      because: `The identical state has been written ${repetition} times in this run. Goal, progress and distance are all unchanged.`,
      counsel: 'Not a slow patch — the same patch. Change what you are doing, or say plainly what is blocking it.' }
  if (judged && now != null && now >= 6 && flat >= 4)
    return { verdict: 'narrow',
      because: `Distance has sat at ${dh.slice(-flat).join(', ')} for ${flat} checks without falling, and ${now} is still far from done.`,
      counsel: 'The goal is too large to close in one move. Name the smallest piece that would genuinely reduce the distance and make that the goal.' }
  if (judged && stalls > 0 && pace <= 0 && now != null && now >= 4)
    return { verdict: 'narrow',
      because: `${stalls} stall${stalls > 1 ? 's' : ''} recorded and net distance closed is ${closed} over ${steps} checks, still at ${now}.`,
      counsel: 'Motion without progress. Pick one concrete sub-result you can actually finish, and make that the goal.' }
  return null   // continue / finish — the healthy majority, and a field present every step gets skimmed
}

/**
 * The judgment tool's full reading: the verdict `judgeRun` already decides, plus the
 * named scores it decided on and the context it belongs to.
 *
 * Several numbers rather than one blended score, because they disagree in ways a single
 * figure hides: a run can be perfectly faithful to its goal (`goal` 1.0) and going
 * nowhere (`pace` 0), and averaging those two produces a number that describes neither.
 *
 * Two verdicts here that judgeRun cannot return. It answers null for the healthy
 * majority — right for a field attached to every check, useless for a tool asked
 * "should I keep going", which must always answer. So null resolves to `finish` when the
 * run is nearly done and still closing, and to `continue` otherwise.
 *
 * `verify` is deliberately absent. The local server can return it because it watches a
 * runtime trace and can catch a self-report disagreeing with observed steps; the Worker
 * sees only what the agent spells. Listing a verdict this surface cannot reach would be
 * the same class of untruth the parity gate exists to catch.
 *
 * THE STALL VETO IS ABSENT FOR THE SAME REASON, added 2026-08-05.
 *
 * The SDK and the local server now decline to call `stalled` when every check in the window
 * is backed by observed work: a flat distance during execution is not a stall. Carrying a
 * thing across a room closes nothing on any single step. Measured on ARC-AGI-3, `stalled`
 * fired on 35 of 133 steps across five agent runs and ALL 35 reached a state never seen
 * before — it was right about the number and wrong about the run.
 *
 * That veto reads an evidence channel. THIS SURFACE HAS NONE — the Worker is stateless per
 * request and sees only the goal, progress and distance the agent spells. So the veto cannot
 * fire here, and for identical inputs the Worker's answer equals what the SDK and server
 * return with no evidence, which is unchanged behaviour. Parity holds BY CONSTRUCTION rather
 * than by luck, and that distinction is the reason this note exists: a future reader
 * comparing the three files will find the rule in two of them and needs to know whether that
 * is a bug. It is not — until someone gives the Worker an observation channel, at which
 * point it becomes one.
 */
export function judgeWork(
  st: DriftState,
  mem?: { repetition: number; recurrence: number; ceiling: number | null } | null,
): {
  verdict: string; because: string; counsel: string
  context: string | null
  scores: {
    goal: number; closure: number; pace: number; drift: number; steps: number
    recurrence: number; repetition: number; ceiling: number | null
  }
} {
  const dh = st.distHist ?? [], trace = st.trace ?? []
  const steps = trace.length
  const recurrence = mem?.recurrence ?? 0
  const ceiling = mem?.ceiling ?? null

  const spellings = st.scores ?? []
  const counts: Record<string, number> = {}
  for (const s of spellings) counts[s] = (counts[s] ?? 0) + 1
  const repetition = Math.max(Math.max(0, ...Object.values(counts), 0), mem?.repetition ?? 0)

  if (!st.ground || !steps) {
    return {
      verdict: 'ungrounded',
      because: 'No ground state — nothing has been measured yet.',
      counsel: 'Call check_state with your goal first; judgment needs a trace to judge.',
      context: null,
      scores: { goal: 1, closure: 0, pace: 0, drift: 0, steps: 0, recurrence, repetition, ceiling },
    }
  }

  const started = dh[0], now = dh[dh.length - 1]
  const closed = (started != null && now != null) ? started - now : 0

  // Jaccard of the current goal against the goal first stated — the same overlap
  // checkStep uses to decide goal-drift, so the tool and the gate cannot disagree.
  const fset = new Set(st.firstGoal ?? [])
  const gset = new Set([...norm(st.ground.goal ?? '')])
  let gi = 0
  for (const w of gset) if (fset.has(w)) gi++
  const goal = fset.size ? Number((gi / (new Set([...gset, ...fset]).size || 1)).toFixed(2)) : 1

  const scores = {
    goal,
    closure: started ? Number((closed / started).toFixed(2)) : (now === 0 ? 1 : 0),
    pace: steps ? Number((closed / steps).toFixed(2)) : 0,
    drift: trace.length ? trace[trace.length - 1].phi : 0,
    steps,
    recurrence, repetition, ceiling,
  }

  const hard = judgeRun(st, mem)
  if (hard) return { ...hard, context: contextId(st.ground.goal ?? ''), scores }

  const done = now != null && now <= 2 && closed > 0
  return {
    verdict: done ? 'finish' : 'continue',
    because: done
      ? `Distance is ${now} and this run has closed ${closed} over ${steps} checks.`
      : `${steps} checks, ${closed} closed, distance ${now}. Nothing in the trace argues against continuing.`,
    counsel: done
      ? 'Close it. Finish the remaining piece and state plainly what was done.'
      : 'Keep going, and keep spelling the state each step so the reading stays honest.',
    context: contextId(st.ground.goal ?? ''),
    scores,
  }
}

/**
 * `mem` is optional and the function stays SYNCHRONOUS without it.
 *
 * The store lives behind a Durable Object and every call to it is async, so the obvious
 * move is to make checkStep async and await inside. That would put I/O in the middle of
 * the instrument: the verdict would stop being a pure function of (state, input), it could
 * fail for reasons that have nothing to do with drift, and every one of the four call
 * sites would have to change. Fetching the memory OUTSIDE and passing it in keeps the
 * measurement deterministic and testable, and leaves the store a thing that can be absent.
 */
export function checkStep(
  prev: DriftState,
  input: { goal?: string; progress?: string; distance?: unknown; parent_goal?: string },
  mem?: { repetition: number; recurrence: number; ceiling: number | null } | null,
): { verdict: Verdict; state: DriftState } {
  // Spread FIRST, then deep-copy the arrays that get mutated below. This was an explicit
  // field list, and on 2026-07-27 `trail` was added to DriftState and not to the list — so
  // the ground trail was silently discarded on every call and the cycle detector saw a
  // one-element history forever. TypeScript could not catch it: `trail` is optional, as it
  // must be, because this state is persisted in a Durable Object and old sessions predate
  // the field. An enumerated copy is a list that has to be maintained in step with the
  // type and gives no signal when it isn't; a spread cannot fall behind.
  const st: DriftState = {
    ...prev,
    firstGoal: [...prev.firstGoal], distHist: [...prev.distHist], trace: [...prev.trace],
    trail: [...(prev.trail ?? [])], scores: [...(prev.scores ?? [])],
    // distAll copied for the same reason as the rest: a mutable array left out of this list
    // is shared with `prev`, so a push inside emit writes into the caller's state and
    // checkStep stops being pure.
    distAll: [...(prev.distAll ?? [])],
  }
  const { goal, progress, distance } = input
  // Did the PREVIOUS step already read as a drift condition? The soft modes
  // (stalled, self-report) only tell you to RETURN if the drift is sustained —
  // one noisy step is a watch, not a loop. Hard modes (ungrammatical, goal-drift)
  // fire immediately. This is the fix for the false-return failure: a single
  // off-reading no longer sends a working agent back to ground.
  const last = prev.trace[prev.trace.length - 1]
  const prevDriftReason = last ? isDrift(last.reason) : false
  const emit = (drifting: boolean, reason: string, advice: string, phi = 0): { verdict: Verdict; state: DriftState } => {
    // The trace records the READING; the cycle is a fact about the sequence of readings,
    // so the original goes in and `oscillating` is what comes out.
    st.trace.push({ step: st.trace.length + 1, reason, phi: Number(phi.toFixed(2)), drifting })
    if (distance !== undefined && distance !== null && typeof distance !== 'boolean') {
      (st.distAll ??= []).push(asDist(distance))
    }
    st.trail = [...(st.trail ?? []), goal ? [...norm(goal)].sort().join('|') : '']

    // GROUND FIRST, then readings. The ground is x and the verdicts are f(x); a cycle in x
    // is what this verdict was built to name. Checking it first means an agent that keeps
    // returning to the same goals is caught on that fact alone, rather than having to also
    // produce a periodic sequence of readings. The verdict pass is kept because a repeating
    // READING over a moving ground is a real pattern too — just not the same one.
    let period = cyclePeriod(st.trail)
    // THE READING FALLBACK IS RETIRED, 2026-08-04, on the corpus. It fired 16 times in
    // 1,823 recorded readings and was wrong all 16 — not one had a cycle in the GOALS.
    // Every window looked like A A A B: one goal worked, then another handed over, with
    // only the VERDICT sequence repeating. That is the ordinary rhythm of a session, so
    // the arm detected task switching and nothing else. Precision 0.00, and untunable —
    // the period it finds is a property of how often a user speaks.
    //
    // The GROUND arm stays: a cycle in x, which is what this verdict was built to name.
    const of = 'ground'
    const score = laserscore(goal, progress, distance, input.parent_goal)
    // Recorded in emit, the single exit every verdict passes through. Putting it on the
    // individual return paths is how `trail` came to be dropped from the state copy and
    // silently fed the cycle detector a one-element history.
    if (score) st.scores = [...(st.scores ?? []), score]
    const gset = new Set(norm(goal ?? '')), fset = new Set(st.firstGoal)
    let gi = 0; for (const x of gset) if (fset.has(x)) gi++
    const goal_score = fset.size ? Number((gi / (new Set([...gset, ...fset]).size || 1)).toFixed(2)) : 1
    const ctx = contextId(goal)
    const inRun = score ? (st.scores ?? []).filter((s) => s === score).length : 0
    const reps = Math.max(inRun, mem?.repetition ?? 0)
    const j = judgeRun(st, mem)
    const extra = {
      // THE FROZEN GROUND, ON EVERY VERDICT — not only when one fires. 2026-08-18.
      //
      // It came back before only inside a firing goal-drift, interpolated into the advice
      // string, so an agent on a healthy step never saw the goal it started with. That made
      // re-presentation conditional on a detector whose published precision is 4 of 50.
      //
      // The mechanism measured to work is unconditional: re-presenting the ground at every
      // step took rule survival across relayed hand-offs from 0/8 chains to 8/8 with no
      // detector in the loop, while a generic reminder fired just as often scored 0/6.
      // Exhortation is not transmission — the rule itself has to travel.
      //
      // It lives in `extra` because that object is spread into BOTH verdict returns below,
      // including the oscillating early return. Putting it on the individual returns is how
      // a fix comes to be written into one branch of two.
      //
      // Third of three implementations to get this, after the Python SDK and lasermind's
      // mcp-server.mjs. Hosted callers reach laserbrain through THIS worker, so the other
      // two alone were a half-ship.
      //
      // WHAT IT COSTS IS UNMEASURED. An earlier version of this comment said 11.9%
      // cheaper than carrying no constraint. That came from a cache-position test that did not
      // replicate — the identical manipulation measured -11.9% then +5.9%, within-arm variance
      // hit 101% of the mean, and no contrast cleared |t| = 2. The defect-prevention result is
      // unaffected: 0/8 relayed chains held a constraint without this, 8/8 with it.
      ground: st.ground?.goal ?? null,
      goal_score, context: ctx,
      ...(reps > 1 ? { repetition: reps } : {}),
      ...(mem && mem.recurrence > 0 ? { recurrence: mem.recurrence, ceiling: mem.ceiling } : {}),
      ...(j ? { judgment: j } : {}),
    }
    if (period && !st.osc) {
      st.osc = true
      st.oscFires = (st.oscFires ?? 0) + 1
      const what = of === 'ground'
        ? 'You have returned to the same goals in a repeating order'
        : 'Your reading has cycled'
      return { verdict: { drifting: true, reason: 'oscillating', phi: Number(phi.toFixed(2)),
        advice: `${what} with period ${period} — you have been told to return and have come back to the same place. Re-ground explicitly instead of returning again.`,
        laserscore: score, ...extra }, state: st }
    }
    if (!period) st.osc = false
    return { verdict: { drifting, reason, phi: Number(phi.toFixed(2)), advice, laserscore: score, ...extra }, state: st }
  }
  if (!goal || !String(goal).trim() || !progress || !PROGRESS.has(progress))
    return emit(true, 'ungrammatical', 'You cannot spell a clear goal and a valid progress. Stop and return to ground.')
  if (!st.ground) {
    st.ground = { goal, progress, distance: asDist(distance) }
    st.firstGoal = [...norm(goal)]
    st.distHist = [asDist(distance)]
    return emit(false, 'grounded', 'Ground state set — this is where you started. Continue, and check each step.')
  }
  const phi = displacement({ goal, progress, distance }, st.ground)
  // Soft: a self-report of stuck/circling only returns you if you have genuinely
  // moved from ground (Φ past a floor, not merely > 0) AND it is sustained.
  if ((progress === 'stuck' || progress === 'circling') && phi > 0.15) {
    return emit(prevDriftReason, `self-report:${progress}`,
      prevDriftReason
        ? `You reported ${progress} and have stayed off ground. Return to your goal.`
        : `You reported ${progress}. If it holds next step, return to ground.`, phi)
  }
  // Hard: the goal itself no longer overlaps the one you started with. Normalised,
  // so rephrasing the same goal no longer trips it.
  const g = norm(goal), first = new Set(st.firstGoal)
  let inter = 0; for (const x of g) if (first.has(x)) inter++
  const anchor = inter / (new Set([...g, ...first]).size || 1)
  if (anchor < GOAL_MIN) {
    // A DECLARED PARENT MAKES THIS A BRANCH, NOT A DEPARTURE. Added 2026-08-20: this file
    // could not produce `excursion` at all — no parent_goal anywhere — so the hosted API,
    // the hosted MCP and anything built from this shipped EIGHT of the nine verdicts while
    // the site documented nine. The parity gate stayed green because the generated vectors
    // contained no parent_goal step and never expected an excursion: a check cannot see a
    // verdict it never asks for. Semantics mirror __init__.py — Jaccard of the normalised
    // parent against the FROZEN first goal, not against the current one.
    const pg = (input.parent_goal ?? '').trim()
    let rejected: number | null = null
    if (pg) {
      const p = norm(pg)
      const union = new Set([...p, ...first]).size
      let pInter = 0; for (const x of p) if (first.has(x)) pInter++
      const pAnchor = union ? pInter / union : 0
      if (pAnchor >= GOAL_MIN)
        return emit(false, 'excursion',
          `On a sub-task (overlap ${anchor.toFixed(2)}) that still serves your ground goal ` +
          `(parent overlap ${pAnchor.toFixed(2)}). Not drift — but the parent is what you owe.`, phi)
      rejected = pAnchor
    }
    if (rejected !== null)
      return emit(true, 'goal-drift',
        `Your goal no longer matches the one you started with (overlap ${anchor.toFixed(2)}). ` +
        `You DID declare a parent, and it was measured at ${rejected.toFixed(2)} against your ` +
        `ground — below the ${GOAL_MIN.toFixed(2)} floor, so this reads as drift rather than an ` +
        `excursion. Either the parent is not the goal this serves, or it shares too little ` +
        `wording with it to be recognised. If the user redirected you, reset.`, phi)
    return emit(true, 'goal-drift', `Your goal no longer matches the one you started with (overlap ${anchor.toFixed(2)}). Return.`, phi)
  }
  // Soft: distance stopped falling — over a 4-step window (was 3), and only a
  // return if you were already off ground.
  st.distHist.push(asDist(distance))
  const dh = st.distHist
  if (dh.length > 4 && Math.min(...dh.slice(-4)) >= dh[dh.length - 5]) {
    return emit(prevDriftReason, 'stalled',
      prevDriftReason
        ? `Distance has stopped falling (${dh.slice(-5).join(', ')}) and you were already off ground — return.`
        : `Distance isn’t falling (${dh.slice(-5).join(', ')}). If it holds, return.`, phi)
  }
  return emit(false, 'advancing', `On track (Φ=${phi.toFixed(2)}). Continue.`, phi)
}
