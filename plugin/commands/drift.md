---
description: Check yourself against the goal this session started with, and say plainly whether you have left it.
---

Call `check_state` with your CURRENT working state, spelled honestly:

- `goal` — the goal you are pursuing **right now**, in your own words. Not the goal you were
  given; the one you would name if asked this second. The difference between those two is the
  entire measurement.
- `progress` — `advancing`, `stuck`, or `circling`.
- `distance` — 0 to 10, how far from done.

Then report what came back, including `phi` and `goal_score`, and — if the verdict is
`goal-drift` — say so plainly rather than explaining it away. A drifting agent feels
maximally coherent, because a goal restated is perfectly consistent with itself. The reading
is worth more than the feeling.

If the user redirected you, that is a `reset_task`, not a drift. If this is a sub-task of a
larger goal you have not abandoned, pass `parent_goal`.
