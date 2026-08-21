#!/usr/bin/env python3
"""Offline tests for the ecosystem additions: audit/provenance, escalation, team
continuity (no key, no model calls)."""
import json
from laserbrain import Harness, Team, verify_audit

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


# 1) AUDIT / PROVENANCE — a hash-chained ledger, independently verifiable + tamper-evident.
print("== 1) audit / provenance ==")
hz = Harness(run_id="job-42")
hz.check("build the parser", "advancing", 6)
hz.check("build the parser", "advancing", 4)
hz.check("write a poem instead", "advancing", 4)     # goal-drift, recorded
chain = hz.audit()
show("every check is logged", len(chain) == 3, f"{len(chain)} records")
show("intact chain verifies", verify_audit(chain) == (True, -1))
# tamper: someone edits a past verdict to hide the drift
tampered = json.loads(json.dumps(chain))
tampered[2]["drifting"] = False
tampered[2]["reason"] = "advancing"
bad_ok, bad_i = verify_audit(tampered)
show("tampering is caught", (not bad_ok) and bad_i == 2, f"first bad link @ {bad_i}")
show("survives JSON export round-trip", verify_audit(json.loads(json.dumps(chain))) == (True, -1))
# TRUNCATION — the easier way to hide a drift, and the one the chain cannot catch alone.
# Deleting the last records leaves something still perfectly self-consistent, so this
# verified as intact until 2026-08-21. It is closed only by pinning the head outside the
# chain; with nothing pinned the old answer is still the honest one, and stays the default.
short = json.loads(json.dumps(chain))[:1]
show("truncation passes when nothing is pinned", verify_audit(short) == (True, -1),
     "documented limit, not a regression")
head = chain[-1]["hash"]
t_ok, t_i = verify_audit(short, expect_head=head)
show("truncation is caught when the head is pinned", (not t_ok) and t_i == 1, f"breaks @ {t_i}")
show("truncation is caught when the length is pinned",
     verify_audit(short, expect_len=len(chain)) == (False, 1))
show("an empty chain no longer verifies as intact", verify_audit([], expect_head=head) == (False, 0))
show("pinning the right head still passes an intact chain",
     verify_audit(chain, expect_head=head, expect_len=len(chain)) == (True, -1))

# 2) ESCALATION — drift that a return can't fix escalates to a human, whose call is injected.
print("\n== 2) human-in-the-loop escalation ==")
events = {"escalated": 0, "decided": None}


def stubborn(ctx):
    # ignores the auto-return and keeps stalling — until a human decision arrives
    if ctx.get("decision"):
        ctx["d"] = 0                                  # human said stop/resolve → done
    else:
        ctx["d"] = 5
    return dict(goal="migrate the database", progress="advancing", distance=ctx.get("d", 5))


def on_escalate(v, ctx):
    events["escalated"] += 1
    events["decided"] = "Human: stop and hand back to me."
    return events["decided"]                          # the human's decision overrides the auto-return


ctx = Harness().run(stubborn, max_steps=12, escalate_after=3, on_escalate=on_escalate)
show("escalated after the return failed to take", events["escalated"] == 1, f"streak→{ctx.get('returns')} returns")
show("human decision was injected + resolved", ctx.get("decision") == events["decided"] and ctx["d"] == 0)

# 3) TEAM CONTINUITY — snapshot a running team, resume it cold, keep the same ground.
print("\n== 3) team-level continuity ==")
STEP = ["a science council and an elected steward split authority",
        "the steward is recalled by council supermajority",
        "disputes go to a panel drawn by lot"]
_c = {"i": 0}


def agent(role, history, injected):
    i = min(_c["i"], len(STEP) - 1); _c["i"] += 1
    return (f"{role['role']}: {STEP[i]}", max(0, 6 - i * 2))


team = Team("adversarial-deliberation", goal="decide the colony's governance", key=None)
team.run(agent, max_turns=2, verbose=False)          # session 1: two turns
snap = json.loads(json.dumps(team.snapshot()))       # persist across a "restart"
resumed = Team.restore(snap)
same_goal = resumed._dlg.goal == team._dlg.goal and len(resumed._dlg.goal) > 0
carried = len(resumed._dlg.turns) == len(team._dlg.turns)
show("shared ground (goal) carried over", same_goal, f"goal={sorted(resumed._dlg.goal)}")
show("dialogue history carried over", carried, f"{len(resumed._dlg.turns)} turns restored")
before = len(resumed._dlg.dist_hist)
resumed.run(agent, max_turns=2, verbose=False)       # session 2: continues watching the same reference
show("resumed team keeps watching the same reference", len(resumed._dlg.dist_hist) > before)

print("\n" + ("ALL ECOSYSTEM TESTS PASS ✓" if ok else "SOME FAILED ✗"))
raise SystemExit(0 if ok else 1)
