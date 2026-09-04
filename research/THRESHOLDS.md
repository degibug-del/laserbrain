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

    python3 - <<'EOF'
    # goal_score distribution, from ~/.config/laserbrain/drift-log.jsonl
    # ground-pair Jaccard, from the same file's distinct runs
    # phi on stuck/circling readings, same file
    EOF

The three distributions above come from that log directly; every number is a count over rows
in it, and re-running against a longer log should move the counts and not the shape.
