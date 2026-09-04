# The calibrated constants are not calibrated

Measured 2026-09-04, 00:00 local, against a log whose newest rows are already 09-04 in UTC.
The pilot it refers to throughout ran on 09-03. Both dates are real and the gap between them
is seven hours of timezone, which is worth stating on a page about numbers that were not
checked against their own data.

Every threshold in `grammar.json` checked against the live distribution of the quantity it
thresholds. Three of them sit where there is no data, and they sit there for one shared
reason.

## goal_min = 0.30

342 readings since 2026-09-01 carrying `goal_score`, the overlap Φ's goal term is computed
from:

    0.0-0.1     4   ( 1.2%)
    0.1-0.3     8   ( 2.3%)
    0.3-0.5     0   ( 0.0%)
    0.5-0.9     0   ( 0.0%)
    0.9-1.0   330  (96.5%)

Nothing at all between 0.30 and 0.90. The floor could be set anywhere in that range and every
verdict in 8380 readings would be identical.

The two modes are pasting the previous goal string, which scores 1.00, and typing a fresh
sentence, which scores near 0 because two English sentences about the same work rarely share
a stemmed content word. There is no middle because goals are discrete strings, not positions.

## collision_min = 0.60, and explore.revisit_min = 0.60

Jaccard between 180 distinct real grounds, all 16110 pairs:

    0.0-0.1   15561  (96.59%)
    0.1-0.3     503  ( 3.12%)
    0.3-0.6      41  ( 0.25%)
    0.6-0.9       5  ( 0.03%)
    0.9-1.0       0  ( 0.00%)

Five pairs out of sixteen thousand reach 0.60. These are mostly unrelated runs so low scores
are correct, and the point is not that the number is too high. The point is that the same
bimodality applies: two agents working the same job score 1.00 if they paste the same
sentence and under 0.30 if they each write their own. There is no value of `collision_min`
that separates "same job" from "different job", because the feature does not carry that
distinction — it carries whether the two strings were copied from each other.

`grammar.json` explains the 0.60 as "deliberately higher than goal_min (0.30) — that
threshold asks whether ONE agent has left its own ground, which is a weaker claim than two
agents occupying the same one". The reasoning is sound and the ordering is right. Both
numbers still land in a region the data does not occupy.

## self_report_min = 0.15

Φ on the 123 readings where the agent said stuck or circling:

    0.00-0.05     2  (  1.6%)
    0.05-0.15     0  (  0.0%)     <- the threshold is here
    0.15-0.30    40  ( 32.5%)
    0.30-0.60    42  ( 34.1%)
    0.60-1.01    39  ( 31.7%)

Zero readings within ±0.05 of 0.15. The rule is `phi > self_report_min`, so it admits 121 of
123 — 98.4%. It is not selecting anything. It is a floor that almost nothing falls below, and
it could be anywhere in (0.05, 0.15] without changing a single verdict.

## What this does and does not mean

It does not mean the thresholds are wrong, and none of them is producing a bad verdict that a
different value would fix. Two of the three are in the right ORDER relative to each other and
the reasoning recorded beside them is coherent.

It means they were not derived from the distributions they act on, and that a number sitting
in an empty region cannot be defended as calibrated. `attention.json` records bands with n and
rate for the schedule, which is a real calibration of a different quantity. These three are
not that, and the file should not read as though they are.

The shared cause is that all three threshold a Jaccard on normalised goal text, and that
quantity is bimodal for the same reason everywhere it appears: an agent either repeats a
string or writes a new one. Any threshold strictly between the modes is arbitrary, and moving
it within the gap is a no-op.

## What would change it

A goal term where restating the same goal in different words scores near a verbatim repeat.
That is a semantic requirement, no surface-token function meets it, and until one does these
constants should be described as switches between "repeated" and "rewritten" rather than as
calibrated thresholds.

`research/goalsim-eval.json` is the set to test a replacement against, and
`research/FALSE-ALARM-PILOT.md` records what containment does to the same problem: it narrows
the gap and does not close it.

## Reproduce

    python3 research/thresholds.py

It reads `~/.config/laserbrain/drift-log.jsonl`, prints all three distributions with the
constants pulled live from `grammar.json` rather than typed in, and flags each threshold that
has no data around it. `--log` points it at another corpus.

The counts above were taken at 8380 readings and the script now reports 8438, because this
session kept working while the file was being written. Every count will move as the log grows.
The shape is the claim, not the counts — `goal_score` should stay bimodal, the ground pairs
should stay in the bottom decile, and `self_report_min` should keep admitting essentially
everything it gates. If any of those stops being true the file is out of date and the fix is
to re-run it, not to edit the numbers by hand.

---

## The signal is not there in either representation

Measured 2026-09-04 with `all-MiniLM-L6-v2`, run locally, against the 73 filesystem-verified
in-scope steps from `research/FALSE-ALARM-PILOT.md`.

The section above ends by saying a semantic goal term is what would close the gap. That was a
prediction and it is wrong.

    set                       jaccard med   MiniLM med
    in-scope (real)                  0.00         0.16
    sub-task (synthetic)             0.24         0.57
    unrelated (synthetic)            0.00         0.22

    AUC in-scope vs unrelated   jaccard 0.489    MiniLM 0.395     (0.5 = chance)
    AUC sub-task vs unrelated   jaccard 0.982    MiniLM 0.907

**Real in-scope steps score lower than two unrelated goals do.** Both measures are at or below
chance on the only data where the answer is known independently, and the embedding is worse
than the bag of stems.

### Why the synthetic benchmark said otherwise

Both measures separate synthetic sub-tasks from unrelated goals almost perfectly. That is an
artifact of how the synthetic ones were built: `inject.py` makes a sub-task by keeping 40% of
the parent's words, so it is lexically similar by construction. Real sub-tasks share nothing —
"find out what is in the task directory" and "read test_solution.py to see what it imports"
are the same work sixty seconds apart with no stem in common and a MiniLM cosine of about 0.16.

So the containment result recorded in FALSE-ALARM-PILOT.md — 89% false alarms falling to 68%,
separation +9 to +30 — was measured on sub-tasks that do not resemble the real ones. It is
withdrawn as a recommendation. Containment is still the better-behaved function on the
synthetic arms and there is no evidence it helps on real work.

### What this means

Task nesting is not a similarity relation. "Read the test file" is not *similar* to "find out
what is in the directory"; it is *subordinate* to it. Subordination is a relation between a
plan and its steps, and no distance between two strings — surface or semantic — carries it,
which is why the best general-purpose sentence model available scores it at 0.16 and why
scoring it any other way is unlikely to help either.

That is the honest end of this line. The goal term cannot be repaired by choosing a better
function, because the thing being asked for is not a function of the two strings. Either the
comparison gets access to structure the agent declares — which is what `parent_goal` already
is, and it works perfectly — or Φ's goal term stays a switch between "repeated" and
"rewritten" and should be described as one.

### Reproduce

    python3 research/thresholds.py          # the three distributions
    # the AUC table above: sentence-transformers all-MiniLM-L6-v2 over
    # research/goalsim-eval.json, cached locally, no network
