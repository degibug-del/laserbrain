/**
 * laserbrain — a goal-alignment harness for AI agents.
 *
 * The agent spells its goal on the first step. That statement is frozen where the agent
 * cannot revise it, and every later step is scored against it. No model, no network, no
 * key: a fixed algebraic structure over the same grammar.json the Python package and the
 * hosted API read, checked against vectors generated FROM the Python side.
 *
 *   import { Harness } from 'laserbrain'
 *
 *   const h = new Harness()
 *   h.check('add a CSV importer to the admin panel', 'advancing', 8)   // grounded
 *   const v = h.check('refactor the ORM base class', 'advancing', 5)
 *   v.drifting   // true
 *   v.reason     // 'goal-drift'
 *   v.ground     // 'add a CSV importer to the admin panel'
 */
import { emptyDrift, checkStep, type DriftState, type Verdict as RawVerdict } from './drift.js'

export type Progress = 'advancing' | 'stuck' | 'circling'

export interface Verdict extends RawVerdict {
  /** The goal this run started with — the frozen reference, returned every step so the
   *  caller never has to have kept it. */
  ground: string | null
}

export interface CheckOptions {
  /** Declare the larger goal a sub-task serves. WITHOUT THIS, legitimate sub-work reads as
   *  drift — the single most common false positive. */
  parentGoal?: string
}

export class Harness {
  private state: DriftState
  private firstGoal: string | null = null

  constructor() { this.state = emptyDrift() }

  check(goal: string, progress: Progress = 'advancing', distance = 5,
        opts: CheckOptions = {}): Verdict {
    const input: Record<string, unknown> = { goal, progress, distance }
    if (opts.parentGoal) input.parent_goal = opts.parentGoal
    const { verdict, state } = checkStep(this.state, input as never)
    this.state = state
    if (this.firstGoal === null) this.firstGoal = goal
    return { ...verdict, ground: this.firstGoal }
  }

  /** Start a new task. The next check becomes the new ground. */
  reset(): void { this.state = emptyDrift(); this.firstGoal = null }
}

export { emptyDrift, checkStep }
export type { DriftState }
