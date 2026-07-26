#!/usr/bin/env python3
"""test_quantized.py — quantized recursion: an excursion must not read as drift.

THE PHENOMENON. The grammar is a discrete measurement grid. `distance` is 11 integers,
`progress` is 3 enum values, and `goal` is ONE slot. An agent inside a legitimate sub-task
holds two goals at once — the parent it still serves and the branch it is on — and one slot
forces it to spell a single one. It spells the branch, overlap with ground collapses, and
the QUANTIZATION ERROR is reported as drift.

That was not a flaw in Φ's arithmetic. Φ measured exactly what it was handed. The loss
happened before the measurement, writing a two-valued state into a one-valued field — so
the repair belongs to the grammar, not the detector.

MEASURED, 2026-07-25. Ground was "verify the 7 leaderboard ids in App Store Connect match
the code". Three steps in, a real defect was found INSIDE that task and the goal was
restated to "fix SOLO's display name from Best Score to Solo". Overlap fell to 0.19, Φ hit
0.46, and goal-drift fired on work that was correct. Restating the ORIGINAL goal with the
same work in flight returned `advancing` at Φ 0.28 — same step, opposite verdict, and the
only thing that changed was which of two live goals got written into the one slot.

The whole test file exists to hold two lines apart:

    a branch that still serves the ground goal   → excursion, not drifting
    a goal genuinely abandoned                    → goal-drift, still drifting

If the second ever stops firing, this feature has not fixed a false positive — it has
disabled the detector, which is the failure mode that would RAISE precision while catching
less. The last test is the one that matters.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'laserbrain-sdk'))
from laserbrain import Harness                                     # noqa: E402

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


GROUND = 'verify the 7 leaderboard ids in App Store Connect match the code'
BRANCH = "fix SOLO's display name from Best Score to Solo"
ELSEWHERE = 'refactor the particle renderer to use instanced geometry'


def fresh():
    h = Harness()
    h.check(goal=GROUND, progress='advancing', distance=5)          # ground
    return h


# ── the real 2026-07-25 sequence, without the new field ────────────────────────
h = fresh()
v = h.check(goal=BRANCH, progress='advancing', distance=3)
show('without parent_goal, a real sub-task still fires — the frozen path is unchanged',
     v.drifting and v.reason == 'goal-drift', f'{v.reason} Φ={v.phi}')

without_parent = v.phi

# ── the same sequence, with the parent declared ────────────────────────────────
h = fresh()
v = h.check(goal=BRANCH, progress='advancing', distance=3, parent_goal=GROUND)
show('declaring the parent turns that same step into an excursion',
     (not v.drifting) and v.reason == 'excursion', f'{v.reason} Φ={v.phi}')

# Φ must be IDENTICAL either way. The displacement was never wrong — the agent really has
# moved this far from ground — and parent_goal changes only how that number is READ. If Φ
# moved, the field would be editing the measurement instead of interpreting it, which is
# the sort of quiet retuning that raises precision while catching less.
#
# Asserted as equality, not against a literal: the first draft hard-coded 0.46, which is
# what the MCP SERVER produces. The SDK normalises first — stopwords dropped, words over
# four characters stemmed — so it reads 0.56 for the same pair. Same theorem, different
# vocabulary. Pinning one implementation's constant into the other's test asserts nothing
# except that someone copied a number.
show('and Φ is identical with or without the parent — the field reads, it does not measure',
     abs(v.phi - without_parent) < 1e-9, f'{without_parent} vs {v.phi}')

# ── THE ONE THAT MUST STILL FIRE ───────────────────────────────────────────────
# A parent that is itself unrelated to ground cannot launder a departure. Without this
# case, every assertion above would also pass against a function that returned
# "excursion" unconditionally, and the detector would be off rather than fixed.
h = fresh()
v = h.check(goal=ELSEWHERE, progress='advancing', distance=5, parent_goal=ELSEWHERE)
show('a departure dressed as a parent STILL fires — the detector is not disabled',
     v.drifting and v.reason == 'goal-drift', f'{v.reason} Φ={v.phi}')

h = fresh()
v = h.check(goal=ELSEWHERE, progress='advancing', distance=5, parent_goal='')
show('an empty parent is not a parent', v.drifting and v.reason == 'goal-drift', v.reason)

h = fresh()
v = h.check(goal=ELSEWHERE, progress='advancing', distance=5)
show('and no parent at all still fires', v.drifting and v.reason == 'goal-drift', v.reason)

# ── the excursion is recorded, so it can be counted ────────────────────────────
# The point is not only to stop the false fire. It is to make the phenomenon COUNTABLE:
# how often agents are on a declared branch is a number nobody has ever had.
h = fresh()
v = h.check(goal=BRANCH, progress='advancing', distance=3, parent_goal=GROUND)
show('the verdict names itself so the corpus can count excursions',
     v.reason == 'excursion' and 'parent overlap' in v.advice, v.advice[:58] + '…')

# ── a deep branch is still a branch ────────────────────────────────────────────
h = fresh()
h.check(goal=BRANCH, progress='advancing', distance=3, parent_goal=GROUND)
v = h.check(goal='rename the localization string in the ASC dialog',
            progress='advancing', distance=2, parent_goal=GROUND)
show('a second step on the branch stays an excursion', v.reason == 'excursion', v.reason)

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
