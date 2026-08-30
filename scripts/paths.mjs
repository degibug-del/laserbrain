/**
 * Where things are, resolved from this repository rather than from a home directory.
 *
 * WHY THIS EXISTS. These gates were written in phronesis-world, a private repository, and
 * resolved laserbrain through `join(homedir(), 'laserbrain')`. That works on one machine.
 * It means anyone who clones this repository gets the code and none of the checks that keep
 * it honest — and every divergence found on 2026-08-30 was found by a check, not by reading.
 *
 * Resolved from import.meta.url, so a clone anywhere works and no environment variable is
 * required.
 */
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

/** The contract: grammar.json, attention.json, drift-vectors.json, tools.json. */
export const CONTRACT = join(ROOT, 'json')
/** The local stdio MCP server and its tests. */
export const SERVER = join(ROOT, 'javascript')
/** The Python package. */
export const SDK = join(ROOT, 'python')
/** The importable package itself. */
export const SDK_PKG = join(SDK, 'laserbrain')
/** The measurement and study algorithms. */
export const RESEARCH = join(ROOT, 'research')
