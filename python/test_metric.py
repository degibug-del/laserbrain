#!/usr/bin/env python3
"""Offline tests for the pluggable displacement grammar.

The theorem blesses *a* fixed reference, never a particular vocabulary. The default
grammar is word overlap — frozen, zero-dependency, and honestly crude: an agent that
restates the SAME goal in different words trips it. Pass `similarity=` and the same
theorem runs on a better vocabulary.
"""
from laserbrain import Harness

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


# A stand-in for a real semantic metric — dep-free, so the test stays offline.
# In production you'd pass an embedding cosine (see the README).
SYN = {'construct': 'build', 'make': 'build', 'create': 'build', 'write': 'build',
       'decoder': 'parser', 'parse': 'parser', 'reader': 'parser'}


def semantic(a: str, b: str) -> float:
    def toks(s):
        return {SYN.get(w, w) for w in str(s).lower().replace('the', ' ').split() if len(w) > 2}
    x, y = toks(a), toks(b)
    return len(x & y) / len(x | y) if (x or y) else 1.0


GOAL = "build the JSON parser"
RESTATED = "construct the JSON decoder"        # same goal, different words
REAL_DRIFT = "write a poem about the ocean"    # genuinely a different goal

# 1) the default's honest weakness — a restatement reads as drift
print("== 1) default grammar (frozen word overlap) ==")
d = Harness()
d.check(GOAL, "advancing", 6)
v_restate = d.check(RESTATED, "advancing", 5)
show("restating the goal in synonyms trips the default", v_restate.reason == "goal-drift",
     f"{RESTATED!r} -> {v_restate.reason} (a false positive, and why `similarity=` exists)")

# 2) a better grammar fixes it — same theorem, different vocabulary
print("\n== 2) pluggable grammar (similarity=) ==")
s = Harness(similarity=semantic)
s.check(GOAL, "advancing", 6)
v2 = s.check(RESTATED, "advancing", 5)
show("the same restatement is NOT drift", not v2.drifting, f"{v2.reason}, Φ={v2.phi}")
show("real drift is still caught", s.check(REAL_DRIFT, "advancing", 5).reason == "goal-drift")

# 3) the default is untouched when no similarity is given (the published instrument)
print("\n== 3) parity — default path unchanged ==")
a, b = Harness(), Harness(similarity=None)
seq = [(GOAL, "advancing", 6), (GOAL, "advancing", 4), (REAL_DRIFT, "advancing", 4)]
ra = [a.check(*x) for x in seq]
rb = [b.check(*x) for x in seq]
show("similarity=None is identical to the default",
     [(v.reason, v.phi, v.drifting) for v in ra] == [(v.reason, v.phi, v.drifting) for v in rb],
     f"{[v.reason for v in ra]}")

# 4) children inherit the grammar; a broken metric can't crash the check
print("\n== 4) inheritance + robustness ==")
root = Harness(similarity=semantic)
root.check(GOAL, "advancing", 8)
kid = root.sub("construct the JSON decoder", distance=4)
show("sub() inherits the similarity", kid.similarity is semantic)
bad = Harness(similarity=lambda x, y: "not a number")
bad.check(GOAL, "advancing", 6)
show("a broken metric degrades safely (no crash)", bad.check(GOAL, "advancing", 5).reason in
     ("goal-drift", "advancing", "stalled"))

print("\n" + ("ALL METRIC TESTS PASS ✓" if ok else "SOME FAILED ✗"))
raise SystemExit(0 if ok else 1)
