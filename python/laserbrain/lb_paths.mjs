/* Where laserbrain keeps its state — the JS resolver.
 *
 * The mirror of lasergear/lb_paths.py, resolving identically:
 *
 *     1. a specific override where one exists (LASERBRAIN_DRIFT_LOG, ...)
 *     2. LASERBRAIN_HOME, relocating both trees at once
 *     3. the historical paths, unchanged
 *
 * ONE file, imported by mcp-server.mjs and dogfood-stats.mjs. There are already three
 * copies of this rule across three deployment units that genuinely cannot import each
 * other — the hooks must not depend on the SDK, and the published wheel cannot ship
 * lasergear. Two files in the SAME directory have no such excuse, and test_one_root.py
 * fails if a fourth copy appears here.
 *
 * The rule this protects: `user-turn` is one file at one path shared by every suite and
 * both agents, and a set flag turns `excursion` into `reground`. */
import { homedir } from 'os'
import { join } from 'path'

// `~` is expanded here because lb_paths.py:43 expands it — `pathlib.Path(h).expanduser()`.
// Without this the same LASERBRAIN_HOME resolved two ways: Python to
// /Users/you/lbtest/config, JS to a literal directory named "~". mcp-server.mjs:138
// names the stake: four files resolve the link log independently and must land on the
// same file, and when they do not, two agents sharing a channel each write to a
// different log and read an empty one — which "presents exactly as the other agent
// having said nothing."
const expandTilde = (v) => (v && v.startsWith('~')
  ? join(process.env.HOME || homedir(), v.slice(1))
  : v)

export const lbHome = () => expandTilde(process.env.LASERBRAIN_HOME) || null

export const configDir = () => {
  const h = lbHome()
  return h ? join(h, 'config') : join(homedir(), '.config', 'laserbrain')
}

export const sessionsDir = () => {
  if (process.env.LASERBRAIN_STATE_DIR) return process.env.LASERBRAIN_STATE_DIR
  const h = lbHome()
  return h ? join(h, 'sessions') : join(homedir(), '.claude', 'laserbrain')
}

export const config = (...parts) => join(configDir(), ...parts)
