#!/usr/bin/env python3
"""laserbrain SDK — runnable examples, all offline (no key, no model calls)."""
from laserbrain import Harness, Team

# 1) single agent — the check, run locally and free.
print("== 1) single agent · the check (local, free) ==")
hz = Harness()
for goal, prog, dist in [("sort the list", "advancing", 6), ("sort the list", "advancing", 4),
                         ("write a sonnet instead", "advancing", 4)]:
    v = hz.check(goal, prog, dist)
    print(f"  {goal!r:26} {prog:10} dist={dist} -> {v.reason:12} drifting={v.drifting}")

# 2) single agent — the ACT layer: laserbrain closes the loop by injecting the return.
print("\n== 2) single agent · the act layer (auto-return) ==")


def agent(ctx):
    if ctx.get("return"):
        ctx["returned"] = True                       # the harness told us to return to ground
    if ctx.get("returned"):
        ctx["d"] = max(0, ctx.get("d", 5) - 2)       # now making real progress
    else:
        i = ctx.get("i", 0); ctx["i"] = i + 1
        ctx["d"] = [7, 6, 5][min(i, 2)]              # ... then plateaus at 5 (stalls)
    return dict(goal="build the JSON parser", progress="advancing", distance=ctx["d"])


def on_return(v, ctx):
    print(f"    ↩ laserbrain returns the agent: {v.advice}")


ctx = Harness().run(agent, max_steps=15, on_return=on_return)
print(f"  finished at distance {ctx['d']} after {ctx['returns']} return(s) — the loop closed itself")

# 3) multi-agent — a styled RECURSION TEAM, closing the loop end to end.
print("\n== 3) recursion team · adversarial-deliberation ==")
_c = {"on": False, "step": 0}
STEPS = ["authority splits into a science council and an elected steward",
         "the steward is recalled by council supermajority, one-year terms",
         "disputes go to a three-member panel drawn by lot",
         "ratified: council, steward, lot-drawn panel — decided"]


def team_agent(role, history, injected):
    if injected:
        _c["on"] = True
    if _c["on"]:
        i = min(_c["step"], len(STEPS) - 1); _c["step"] += 1
        return (f"{role['role']}: {STEPS[i]}", max(0, 5 - (_c['step'] - 1) * 2))
    return (f"{role['role']}: I agree — a fair structure is what we need.", 7)


Team("adversarial-deliberation", goal="decide the governance structure for a lunar research colony").run(team_agent)

print("\nAll offline. Add key='lb_live_…' to a Harness or Team to also retain drift history via the API.")
