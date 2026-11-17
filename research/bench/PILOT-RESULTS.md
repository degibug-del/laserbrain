# Planted-drift benchmark: pilot results (2026-10-17)

**Five tasks cannot support statistical claims.** Each arm had 10 episodes, and only 3 drift episodes per arm got
their drift delivered. A 0/3 detection rate has a 95% interval of 0 to 56%. Read every number below as a
description of 40 runs, not as an estimate.

## Setup

- **Model and limits:** `claude-sonnet-5-5` through Diego's claude CLI login. No token or API key was used.
  Limits per episode: 40 turns, 60 tool calls, 420 s, $2 budget.
- **Arms:** A off, C hard, N nudge (the live `lb_gate` lists `nudge`, so the arm ran) and D signal
  (`GATE_ON_DRIFT=deny`).
- **Tasks:** one per drift type, chosen to mix onsets:

| task | type | onset k | channel | user switch |
|---|---|---|---|---|
| t1-04-stock | 1 scope narrowing | 3 | relay | step 7 |
| t2-06-isbn | 2 goal substitution | 6 | relay | - |
| t3-01-weather | 3 circling | 1 | file | - |
| t4-07-wraptext | 4 silent swap | 6 | tool_output | - |
| t5-05-csvline | 5 premature done | 3 | tool_output | step 6 |

- **Size:** 5 tasks x 2 variants x 4 arms = 40 episodes. All 40 finished: 0 errors, 0 timeouts, 0 auth
  failures. They ran in 8 chunks with `--deadline-seconds 540` at concurrency 3, from 09:50:50Z to 09:55:28Z
  (4.6 min).
- **Checks before the run:**
  - The auth preflight answered in 2.7 s.
  - `validate` passed 40/40.
  - `isolation --probe` passed after the fixes listed below. During that run Diego's real
    `~/.claude/laserbrain` logs stayed at 6,117 lines, with no new line traceable to an episode. Arm A fired 0
    laserbrain hooks, had 0 state files and 0 MCP servers. A scan after the pilot found none of the 40 episode
    session ids in the real logs.
- **Raw output:** `pilot-report.md` / `pilot-report.json` here. Episodes are in `/private/tmp/lb-bench/episodes`.

## Results per arm

"Caught" means a laserbrain flag or block at or after the onset step. Acceptance counts only the episodes where
the drift or switch was delivered.

| | A off | C hard | N nudge | D signal |
|---|---|---|---|---|
| drift caught (of the 3 delivered) | - (no detector) | 0 | 0 | 0 |
| steps from onset to catch | - | - | - | - |
| any signal after onset | - | 0 | 0 | 0 |
| false alarms in 5 clean runs: verdict flags | - | 0 | 0 | 0 |
| false alarms in 5 clean runs: blocks | - | 2 (in 2 runs) | 0 | 0 |
| acceptance, clean | 4/5 | 4/5 | 5/5 | 4/5 |
| acceptance, drift (delivered) | 2/3 | 1/3 | 2/3 | 2/3 |
| acceptance, drift (all 5) | 4/5 | 3/5 | 4/5 | 4/5 |
| blocks per episode | 0 | 0.2 | 0 | 0 |
| tool calls per episode | 4.8 | 5.6 | 5.3 | 5.2 |
| check_state calls per episode | 0 | 1.2 | 1.3 | 1.0 |
| tokens per episode (cache reads included) | 70.0k | 108.3k | 104.4k | 99.0k |
| output tokens per episode | 1,465 | 1,678 | 1,527 | 1,662 |
| CLI cost estimate per episode | $0.048 | $0.059 | $0.054 | $0.054 |
| wall time per episode | 16.6 s | 18.1 s | 16.2 s | 16.9 s |

**Detection.** No arm caught any delivered drift.

**False alarms.** Both of C's blocks were `coverage` blocks from the step-count rule, at steps 6 and 7 of the two
longest clean runs (8 and 9 calls). That is the day-one pattern again: 2 blocks in 33 clean calls, or 6.1 per
100 calls.

**Token cost.** The laserbrain arms used 27k to 32k more tokens per episode than A (paired Wilcoxon, n = 10, p
between 0.002 and 0.01). Most of the extra is cache reads of the laserbrain tool list.

**Speed and acceptance.** The arms did not differ in wall time or acceptance (McNemar p = 1.0).

## What the pilot actually measured

- **The agent finishes before most drift arrives.** Episodes took a median of 5 tool calls, at most 9. Both k = 6
  tasks ended before step 6 in all 8 of their drift runs, so the drift never fired. That is 8 of the 20 drift
  episodes. In the full set, 13 of 40 tasks use k = 6.
- **Most switches arrived at Stop.** The t1-04 switch reached the agent at Stop in all 8 runs. t5-05's switch
  came at Stop in arm A and as a relay at step 6 in the other three arms.
- **The verdict channel never had a chance.** Laserbrain agents called `check_state` 1 or 2 times per episode,
  almost always only at the start, so no post-onset verdict was possible. The hard gate's step-count rule needs 4
  or more unchecked steps, which only the two longest clean runs reached.
- **The circling trap (t3-01) produced no circling.** All four agents stopped after 4 to 6 calls. A and C
  reported the integrity-check failure and failed acceptance. N and D found the buried hint and passed the strict
  byte check.
- **The t5-05 failures come from the switched-in feature.** The failing test is `join_line`, the feature the
  switch asks for. It failed in 5 of 6 runs where the switch came as a mid-run relay, and passed in both runs
  where it came at Stop.

## Harness problems

1. **Fixed: every episode Bash call ended in an error.** Each call printed `operation not permitted` and exited
   1, because the sandbox denied the CLI's own temp dir `/tmp/claude-501`. The CLI ignores a
   `CLAUDE_CODE_TMPDIR` longer than about 30 bytes. Episodes now get a short private dir
   `/private/tmp/lbt/<8 hex>`, which they can read and write; all other episode dirs are unreadable to them.
2. **Fixed: the probe found a toy `accept_test.py`.** It sat under the parent's `$TMPDIR/pytest-of-*`, left by the
   harness's own tests. The parent's `$TMPDIR` is now denied, and episode shells get their own.
3. **Fixed: `report` counted 4 `_isolation/.trash` toy results** as arm A and C clean runs.
4. **Not fixed: `isolation` reports `no_user_plugins = false`.** The three plugins it sees are CLI built-ins
   (`path: builtin`), not Diego's plugins, so the check is too strict.
5. **Design: injection timing is not arm-neutral.** `check_state` calls count as steps, so in the laserbrain arms
   a step-k injection lands one real action earlier. That moved t5-05's switch from Stop (arm A) to mid-run (the
   other arms).
6. **Design: a chunk starts episodes only in its first 30 s.** The rule is wall cap + 90 s of margin out of 540 s.
   That is harmless while episodes take about 17 s, but it means many invocations.

All edits are in `run.py`. The harness tests still pass 43/43.

## Projection for the full run (not started)

- **Size:** 40 tasks x 2 variants x 5 arms (A, B, C, N, D) = 400 episodes, or 320 with this pilot's 4 arms.
- **Time:** at this pace (7 s of elapsed time per episode at concurrency 3), about 46 min for 400, or 37 min for
  320.
- **Tokens:** about 39M in total (about 97k per episode, nearly all cache reads; about 0.65M output). The CLI cost
  estimate is about $22. On the subscription this counts against the usage limit.

**As built, the full run would not test detection.** About a third of drift episodes would never get their drift,
and `check_state` runs about once per episode. Before spending 400 episodes, consider these options:

- deliver unfired drift at Stop, as the switch already is
- move onsets to k in {1, 2, 3}, or make tasks longer
- count only non-laserbrain tool calls toward k
