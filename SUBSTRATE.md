# The substrate: is displacement even defined on the JSON grammar?

*Written 2026-07-22. [[PROOF]] is grammar-agnostic — it assumes a metric space of
states and proves the fixed reference is the only sound-and-complete displacement
detector. That leaves one honest gap, flagged in [[SPINE]] and [[CLAIM]]: does the
particular grammar laserbrain uses actually carry a metric, so that `Φ(n) =
d(sₙ, s₀)` means anything concrete? This closes it for the "spelling with JSON"
grammar: it exhibits the metric, proves the axioms, and shows the harness's
triggers are thresholds on it — so mcp_harness is a literal instance of `F_D`, not
an analogy to one.*

---

## The state space

`X` = the set of **grammatical** schema instances (JSON objects that pass
`grammatical()`: a non-empty `goal` and a `progress` in `{advancing, stuck,
circling}`). We measure states on their three load-bearing, proof-relevant fields;
`doing`/`next`/`blocked` are narrative and excluded from the metric (see the
pseudometric note below).

For a state `s` write `G(s)` = the set of word-tokens in `goal`, `p(s)` =
`progress`, `r(s)` = `distance` (an integer clamped to `0..10`).

## The metric

For states `s, s'` and fixed weights `α, β, γ ≥ 0`:

> **d(s, s') = α·J(G(s), G(s')) + β·|r(s) − r(s')|/10 + γ·[p(s) ≠ p(s')]**

where `J(A,B) = 1 − |A∩B|/|A∪B|` is the Jaccard distance on token sets (with
`J(∅,∅) := 0`), and `[·]` is the indicator (1 if the progress labels differ, else
0). Each term lands in `[0,1]`, so `d` is bounded by `α+β+γ`.

## Theorem — (X, d) is a pseudometric space, and a metric on the quotient

*`d` satisfies `d ≥ 0`, `d(s,s)=0`, symmetry, and the triangle inequality. Hence
`Φ(n)=d(sₙ,s₀)` is a well-defined displacement, and [[PROOF]] applies verbatim.*

**Proof.** A non-negative linear combination of (pseudo)metrics is a
(pseudo)metric — non-negativity, symmetry and `d(s,s)=0` are inherited termwise,
and the triangle inequality adds:
`Σ wᵢ mᵢ(s,s'') ≤ Σ wᵢ (mᵢ(s,s')+mᵢ(s',s'')) = Σwᵢmᵢ(s,s') + Σwᵢmᵢ(s',s'')`. So it
suffices that each term is a (pseudo)metric on its field:

1. **Jaccard distance `J`** is a metric on finite sets — the standard
   Levandowsky–Winter result; the triangle inequality is the non-obvious part and
   is classical. On goal-token sets it gives `α·J` a pseudometric on `X` (two
   states with identical goal wording are at `J`-distance 0).
2. **`|r(s)−r(s')|/10`** is the Euclidean metric on `ℤ∩[0,10]`, rescaled by a
   positive constant — a metric.
3. **`[p(s)≠p(s')]`** is the discrete metric on the 3-point set `{advancing,
   stuck, circling}` — a metric.

So `d` is a pseudometric on `X`. It is a **true metric** on the quotient `X/∼`,
where `s ∼ s'` iff they agree on `(G, r, p)` — i.e. once states are identified by
their proof-relevant content, `d(s,s')=0 ⟹ s=s'`. A pseudometric is all
[[PROOF]] needs: every step there used only non-negativity, symmetry and the
triangle inequality, never `d(s,s')=0 ⟹ s=s'`. ∎

**Why a pseudometric is the honest object.** Two spellings can differ in their
`doing`/`next` prose yet be the same reasoning state for drift purposes. Collapsing
them to distance 0 is correct, not a defect: displacement should not count reworded
narration as movement. The metric lives on the content, which is what "drift" is
about.

## The harness is F_D, concretely

With `s₀` = the first grammatical spelling and `Φ(n)=d(sₙ,s₀)`, the triggers in
`run()` are exactly threshold tests on `d` and its components:

- **goal drift** — fires when `J(G(sₙ),G(s₀)) > 1 − GOAL_ANCHOR_MIN`, i.e. a
  threshold on the `α`-component of `Φ`. This *is* a partial `F_D`.
- **distance-stall** — fires when the `r`-component shows no net decrease over the
  window: `Φ`'s distance term stops falling. A displacement-plateau test.
- **self-report** — fires when `p(sₙ) ∈ {stuck, circling}`: the state lands on a
  point of the discrete `p`-metric that the agent itself marks as non-advancing.

So the harness does not *resemble* the proof's detector — under `d` it is one, on a
space now shown to carry a genuine metric. That is the bridge from the abstract
theorem to the running product: the thing being thresholded is a real displacement
on a real metric space, not a metaphor.

## What this does and does not settle

**Settles:** displacement is well-defined on the JSON grammar; [[PROOF]]'s
guarantee is not vacuous here; the harness computes an actual `Φ`. The [[CLAIM]]
"substrate — is the grammar rich enough" line moves from *open* to *the metric
exists and the axioms hold.*

**Does not settle:** that this particular `d` (these fields, these weights) is the
*best* reference for reasoning drift — weights `α,β,γ` are a modelling choice, to be
fixed before data like the threshold `D` ([[STUDY]]), not tuned to a run. And it
says nothing about the *weather-field* grammar; this is the JSON grammar's metric
only. The mechanism survives the substrate; here is one substrate it demonstrably
lives on.
