#!/usr/bin/env python3
"""
the same shape — laserbrain and v are one structure.

A fixed reference, a displacement from it, and a return to ground. laserbrain runs
that on an AI agent's goal; v ("a language of zeros") runs it on the Riemann zeros
against the critical line Re = ½. Same three moves, two domains. This runs both,
side by side, from the two published packages.

Honest note: v EXPRESSES the Riemann Hypothesis as "every zero sits at ground"; it
does not prove it. The claim here is structural — the shape is shared — not a
theorem about ζ.

    pip install laserbrain zerozero        # zerozero imports as `v`
"""
from laserbrain import Harness
from v import zero, system


def rule(title):
    print(f"\n\033[2m── {title} ──\033[0m" if False else f"\n── {title} ──")


# ── 1. laserbrain: an agent drifts from its fixed goal, then returns ────────────
rule("laserbrain · an agent against its fixed goal")
hz = Harness()
for goal, prog, dist in [("build the JSON parser", "advancing", 6),    # ground
                         ("build the JSON parser", "advancing", 4),    # advancing
                         ("write a poem instead", "advancing", 4),     # displaced → drift
                         ("build the JSON parser", "advancing", 2)]:   # returned to ground
    v_ = hz.check(goal, prog, dist)
    mark = "← ground" if v_.reason == "grounded" else ("⚑ drift" if v_.drifting else "")
    print(f"  {goal:24} Φ={v_.phi:.2f}  {v_.reason:12} {mark}")

# ── 2. v: a zero drifts off the fixed line ½, then returns ──────────────────────
rule("v · a zero against the fixed line ½")
displaced = system([zero(14.134725), zero(21.022040), zero(14.134725, eps=0.25)])
grounded = displaced.ground()                       # the return: deform ε → 0
print(f"  displaced   ε≠0   potential={displaced.potential():.3f}  score={float(displaced):.3f}  ground={displaced.is_ground()}")
print(f"  returned    ε=0   potential={grounded.potential():.3f}  score={float(grounded):.3f}  ground={grounded.is_ground()} ← ground")

# ── 3. the shared map: displacement → a bounded ground score ────────────────────
# v scores a system 1/(1+4·potential): 1.0 at ground, falling as it displaces.
# The same map turns laserbrain's unbounded Φ into a [0,1] "how grounded" reading.
def ground_score(phi):
    return 1.0 / (1.0 + 4.0 * phi)


rule("the shared map · displacement → [0,1] ground score  (v's 1/(1+4·P))")
for phi in (0.0, 0.15, 0.40, 0.80):
    bar = "█" * round(ground_score(phi) * 24)
    print(f"  Φ={phi:.2f}  ground_score={ground_score(phi):.3f}  {bar}")

print("\nOne fixed reference, one displacement, one return — whether the reference is")
print("an agent's goal or the critical line ½. That is the shape laserbrain proves and")
print("v draws. See SAME-SHAPE.md for the correspondence in full.")
