# PATCH · goal-drift must not fire on user redirection

*Diego, 2026-07-25: "fix goal-drift so it doesn't fire on user redirection."*

**Status: specified, measured, NOT applied.** Both files belong to Grok in the open wave
(`phronesis/lasermind/mcp-server.mjs`, `phronesis/lasermind/hooks/lb_coverage.py`).
Handed off on the link rather than taken. Everything below is ready to apply as-is.

## The evidence

`goal-drift` is **24 of 35 fires** in the recovered corpus — 69% of every fire this
instrument has produced — and coincided with an independently-caught error **0 times**.
**22 of those 24 were the first check after Diego spoke.** The rule reports that the
subject changed. It did. The user changed it.

## Rules tested, against the real 24

| rule | suppresses | true positives lost |
|---|---|---|
| A · previous check was healthy | 17/24 (71%) | 0 |
| **B · first check after the user spoke** | **22/24 (92%)** | **0** |
| A or B | 24/24 (100%) | 0 |
| A and B | 15/24 (62%) | 0 |

**A or B suppresses everything, which is a warning and not a result** — a rule that never
fires has been deleted, not fixed. **B is the recommendation:** it targets exactly the
known-spurious cause and leaves the two mid-task fires standing, which are the only
candidates in the corpus for a genuine wander.

Note what the table cannot tell you: goal-drift has **no measured true positives at all**,
so no rule here can lose one. These numbers measure reach, not safety. The safety argument
has to come from the shape of the rule — B suppresses only where the user just spoke, and
is silent otherwise — and must be re-measured once the corpus contains a real wander.

## A rule that does NOT work, so nobody retries it

"Near-zero overlap is a replacement; partial overlap is a drift" is intuitive, needs no new
plumbing, and is **wrong**. The anchor values at the 24 fires:

```
0.00 0.00 0.00 0.00 0.00 0.00 0.03 0.03 0.04 0.04 0.05 0.05
0.07 0.07 0.07 0.08 0.09 0.09 0.11 0.11 0.12 0.14 0.15 0.29
```

Continuous from 0 to 0.29, no gap, no bimodality — and every one of them is a redirection.
Any threshold is just "weaken the rule", and would suppress a genuine drift landing at 0.10
exactly as readily. **The discriminator is not in the tool's inputs.** `check_state` sees
`(goal, progress, distance)`, and whether the goal moved because the user said so is not
derivable from those three. That is why B needs a signal from outside the tool, and why it
is worth the plumbing.

## The patch

### 1 · `lasermind/hooks/lb_coverage.py` — mark that the user spoke

In the `UserPromptSubmit` branch, beside where the goal is captured:

```python
        if prompt is not None and not tool:
            if not s.get('goal'):
                s['goal'] = str(prompt)[:400]
            # The next check_state is a RE-GROUND, not a drift. check_state sees only
            # (goal, progress, distance) and cannot tell "the agent wandered" from "the
            # user changed the subject" — 22 of 24 goal-drift fires on 2026-07-25 were
            # the first check after Diego spoke, and none coincided with a real error.
            # This is the missing bit of information, written where the tool can read it.
            try:
                FLAG.parent.mkdir(parents=True, exist_ok=True)
                FLAG.write_text(_now())
            except Exception:
                pass                      # fail open: a missing flag only restores today
            path.write_text(json.dumps(s, indent=2))
            return
```

with, near the other paths:

```python
FLAG = pathlib.Path.home() / '.config/laserbrain/user-turn'
```

### 2 · `laserbrain/mcp-server.mjs` — consume it, once

Replace lines 355–359:

```js
    const g = toWords(goal), first = new Set(drift.firstGoal)
    let inter = 0; for (const x of g) if (first.has(x)) inter++
    const anchor = inter / (new Set([...g, ...first]).size || 1)
    if (anchor < 0.30)
      return record(true, 'goal-drift', `Your goal no longer matches...`, phi)
```

with:

```js
    const g = toWords(goal), first = new Set(drift.firstGoal)
    let inter = 0; for (const x of g) if (first.has(x)) inter++
    const anchor = inter / (new Set([...g, ...first]).size || 1)
    if (anchor < 0.30) {
      // A goal that changed right after the user spoke was REPLACED, not drifted away
      // from. Consuming the flag matters as much as reading it: it must license exactly
      // one re-ground, or an agent that wanders for twenty steps after a redirection
      // stays permanently exempt.
      if (consumeUserTurn()) {
        drift.ground = { goal, progress, distance: asDist(distance) }
        drift.firstGoal = [...g]
        drift.distHist = [asDist(distance)]
        return record(false, 'reground', 'New instruction — ground reset to the goal you just stated.')
      }
      return record(true, 'goal-drift', `Your goal no longer matches the one you started with (overlap ${anchor.toFixed(2)}). You are solving something else — return.`, phi)
    }
```

and near the top:

```js
import { existsSync, unlinkSync } from 'node:fs'
const USER_TURN_FLAG = `${process.env.HOME}/.config/laserbrain/user-turn`
/** True at most once per user turn. Deleting it is the point — see the call site. */
const consumeUserTurn = () => {
  try {
    if (!existsSync(USER_TURN_FLAG)) return false
    unlinkSync(USER_TURN_FLAG)
    return true
  } catch { return false }          // fail open: behave exactly as today
}
```

## How to know it worked

Re-run `python3 recover_corpus.py <transcript>` then `python3 dogfood.py --score`. The
prediction, stated before the change so it can be wrong:

- goal-drift fires fall from 24 to ~2 in a comparable session
- overall precision rises from 3/35 = 9% to roughly 3/13 = 23%
- `stalled`, `self-report:stuck` and `self-report:circling` counts are **unchanged** — if
  any of them moves, the patch reached further than it should have

The new `reground` verdict is deliberately not silence. It is a non-drifting verdict that
still appears in the record, so re-grounds stay countable and the suppression can be
audited later rather than vanishing.
