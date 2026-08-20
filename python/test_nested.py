#!/usr/bin/env python3
"""Offline tests for nested recursion — a recursion as a set of recursions.

The point: each sub-recursion runs the proven flat detector against its OWN goal, so
every node can report "advancing" while the whole decomposition never brings the ROOT
any closer. No node can see that. The set needs its own fixed reference.
"""
from laserbrain import Harness

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


# 1) THE BLIND SPOT — busy subtasks, root never closes.
print("== 1) every node on-track · the tree still spinning ==")
root = Harness()
root.check("build the JSON parser", "advancing", 8)          # root ground

tok = root.sub("write the tokenizer", distance=4)            # child recursion, own ground
local = [tok.check("write the tokenizer", "advancing", d) for d in (3, 2, 0)]

ast = root.sub("write the AST nodes", distance=5)
local += [ast.check("write the AST nodes", "advancing", 3)]

show("no individual node reports drift", not any(v.drifting for v in local),
     f"local verdicts: {sorted({v.reason for v in local})}")
# the root reports again and is no closer than it started — without a second root
# reading there is no evidence of a stall, and calling it one invents alarms.
root.check("build the JSON parser", "advancing", 8)
s = root.tree_status()
show("the TREE is caught spinning", s["stalled"],
     f"{s['steps']} steps across {s['nodes']} recursions, depth {s['depth']}, root closed {s['since_progress']} steps ago")
print("\n" + "  " + root.tree_report().replace("\n", "\n  ") + "\n")

# 2) DEEPER NESTING — a recursion inside a recursion inside a recursion.
print("== 2) depth · the reference is defined at every level ==")
deep = tok.sub("handle string escapes", distance=3)          # depth 2
deep.check("handle string escapes", "advancing", 1)
d = root.tree_status()
show("depth tracked through the whole tree", d["depth"] == 2, f"depth={d['depth']}, nodes={d['nodes']}")
show("each node keeps its own ground", deep._audit[0]["goal"] == "handle string escapes")
show("a child still drifts on its own terms",
     deep.check("write a poem instead", "advancing", 1).reason == "goal-drift")

# 3) HEALTHY TREE — the root actually closes, so no tree-stall.
print("\n== 3) when the root does close ==")
r2 = Harness()
r2.check("ship the release", "advancing", 8)
c = r2.sub("write the changelog", distance=3)
c.check("write the changelog", "advancing", 0)
r2.check("ship the release", "advancing", 4)                 # ← the root got closer
s2 = r2.tree_status()
show("progress at the root clears the tree-stall", not s2["stalled"], f"since_progress={s2['since_progress']}")

# the false positive fixed in 0.3.4: a healthy tree whose root has only reported once
# has no evidence of stalling, and must not alarm.
r3 = Harness(); r3.check("ship the thing", "advancing", 8)
for i in range(3):
    k = r3.sub(f"task {i}", distance=6); k.check(f"task {i}: on thesis", "advancing", 2)
s3 = r3.tree_status()
show("a healthy tree with one root reading does not alarm", not s3["stalled"],
     f"root_checks={s3['root_checks']}, drifting_nodes={s3['drifting_nodes']}")

print("\n" + ("ALL NESTED TESTS PASS ✓" if ok else "SOME FAILED ✗"))
raise SystemExit(0 if ok else 1)
