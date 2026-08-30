# Nuanced and variegated — a diagnosis of the goal term

_Written 2026-07-25, from a session in which `goal-drift` fired four times on work that was
not drifting. The terms are Diego's; the failure they name is the detector's._

## The pair

**Nuanced** — linear, closed, differences of DEGREE. A bounded set with fixed axes, where
every member is comparable to every other because they share a type. Gaps exist between
points, but the points lie on a line.

**Variegated** — branched, differences of KIND, each branch internally nuanced. A tree
whose every limb is its own nuanced line, and which offers no guaranteed type across limbs.

The field is nuanced going in and variegated coming out, and this is checkable rather than
poetic. `mcp-server.mjs:82` holds a hard-coded 40-word table — four groups of ten: ground,
wind, form, change — and line 271 throws on any word outside it. So input is a closed
vocabulary in which `bone`, `stone` and `slow` differ by degree within one element. Line
276 posts to the hub and returns the reply UNFILTERED. On 2026-07-25 the reply was:

    in    ground stone bone deep dark cold slow earth
    out   boundary shift shift another dark cross phosphorus earth heat same before flow

Six of those twelve — `boundary another phosphorus heat same before` — are not in the 40.
The hub speaks from a wider source that no endpoint exposes (`/vocab` is 404 on both
localhost:1618 and fly.dev). So: **laserdictionary on the way in, unenumerable corpus on
the way out.**

## Why the distinction has teeth

Nuanced data can be scored; variegated data cannot be, by the same means. Jaccard over a
closed 40-word vocabulary is meaningful — bounded denominator, every term typed. Jaccard
over free English is a coin toss on phrasing.

Which is exactly what Φ's goal term does. `norm()` lowercases, strips stopwords and stems
anything over four characters, trying to flatten variegated English into a comparable set.
It works when two phrasings differ by degree. It fails when they differ in kind, and
`vocab.py` says so in its own docstring:

> "build the sky billboard" and "construct the aerial hoarding" share no stem and score
> 0.0, so the default calls a faithful restatement drift. No amount of stemming fixes
> that; it needs meaning, which needs a model.

**The defect stated properly: Φ's goal term treats variegated data as if it were nuanced.**
Not a bug in the arithmetic — a category error in what the arithmetic is applied to.

## The evidence from 2026-07-25

Ground was `distance 5`, `advancing`, goal *"Verify the 7 leaderboard ids in App Store
Connect match the code"*. Three steps in, a real defect was found INSIDE that task (SOLO's
leaderboard was still displaying "Best Score" from when it was the only board), and the
goal was restated to *"Fix SOLO's display name from Best Score to Solo"* at `distance 3`,
still `advancing`:

    goal      overlap 0.19  ->  0.5 x (1 - 0.19)  = 0.405
    distance  |3 - 5| / 10  ->  0.3 x 0.2         = 0.060
    progress  advancing = advancing -> 0.2 x 0    = 0.000
                                               Φ  = 0.465

    {"drifting": true, "reason": "goal-drift", "phi": 0.46,
     "advice": "Your goal no longer matches the one you started with (overlap 0.19). Return."}

The goal term did 0.405 of 0.465. Restating the objective moves Φ more than any amount of
honest struggle. Restating the ORIGINAL goal, with the same work in flight, returned
`advancing` at Φ 0.28 — same step, opposite verdict, and the only thing that changed was
the wording.

## Two gaps, and only one of them is periodic

Diego's third line was "data gaps may be traversed with sine or cosine waves". That holds
for one of the two gaps here and not the other, and the split is the useful part.

**The synonym gap is not periodic.** "sky billboard" to "aerial hoarding" is a jump in
meaning space. There is no cycle between synonyms to interpolate along, and no basis
function finds one. This needs embeddings — which is why `embedding_similarity` exists in
`vocab.py` as an opt-in, and why the proof blesses *a* fixed reference and never a
particular vocabulary.

**The excursion gap is periodic.** Leave the goal, do a sub-task, return. Displacement
rises and falls. What distinguishes an excursion from an abandonment is WHETHER IT RETURNS,
and that is phase.

**Φ is a magnitude with no phase.** It compares this step to ground and to nothing else —
it has no memory of the previous step, so it cannot tell "moving away" from "on the way
back". A sub-task is a half-cycle and Φ only ever sees the outbound leg.

The asymmetry is already in the instrument: the stall detector HAS time
(`stall_window=4`, it reads the distance series — *"Distance stopped falling (1, 1, 1, 2)"*)
while Φ is memoryless. Half the detector looks at a sequence; the other half at a point.

## Precedents — recorded because omitting them is how a coinage becomes a claim

The vocabulary is new to this project. The underlying distinction is not, and anyone who
reads this should hear the precedents from us rather than find them later:

- **Stevens' levels of measurement** (1946) partitions roughly along the same seam —
  nominal / ordinal / interval / ratio. "Differences of kind" versus "differences of
  degree" is that partition.
- **Hierarchical / nested categorical data** and multi-level models are built for exactly
  "branched, each branch internally nuanced".
- **Closed vs open word classes** is the same idea in linguistics.
- **Fourier and harmonic interpolation** is the traversal of gappy series by periodic
  basis functions, and is very old.

None of that has been checked against the drift-detection literature specifically. Until
someone does, the honest claim is that we have named a failure mode, not discovered a
paradigm.

## What is plausibly ours, and how it could be wrong

Not the taxonomy — the **diagnosis**, which makes a prediction the taxonomy alone does not:

> **False `goal-drift` fires should CLUSTER AT BRANCH POINTS** — steps where the agent
> opened a legitimate sub-task and restated the goal to match it — rather than being
> scattered through the run. And Φ should be well-behaved wherever the goal is restated in
> stable language, however badly the work is going.

That is falsifiable against the recovered corpus. If the 31 `goal-drift` fires are spread
evenly across step positions and goal-restatements, the framing is a pair of nice words and
should be dropped. If they sit on restatements, it has earned something.

The second claim is narrower and sharper: **the information that resolves these false
positives currently exists only inside the agent.** The agent knows whether it intends to
return; the displacement does not contain that. Either the agent reports it — which
reintroduces the self-observation the theorem says cannot ground itself — or the detector
infers intent-to-return from the trajectory. Kuramoto's order parameter does exactly that
for oscillators, and `test_kuramoto.py` is already in this tree with a case that proves it
can fail. Nothing does it for goals: grepping the SDK for `sin|cos|phase|omega` returns
nothing at all.

## Before any of this ships

A **return term** — tracking the goal-overlap series rather than the point, and treating
rising-then-falling displacement as excursion rather than drift — must be measured against
the corpus first.

The reason is specific. Precision is **9%** and `goal-drift` sits at **0/31**. A term that
quietly suppresses fires would RAISE precision while detecting less, and precision alone
cannot see that. Only the corpus can, and only if the change is scored against it before
it is believed.

## Jargon (adopted 2026-07-25)

- **nuanced** — closed, linear, differences of degree; scoreable by overlap.
- **variegated** — branched, differences of kind; not scoreable by overlap.
- **laserdictionary** — the 40 words the field ACCEPTS (`mcp-server.mjs:82`).
- **laserscore** — the field's spoken reply to eight words.
- **excursion** — displacement that returns; currently indistinguishable from drift.
