# Why the reference must be fixed — the complete proof

*Written 2026-07-22, completed the same day. SPINE.md asserts, informally: "You
cannot measure your own drift without a fixed point." This is that sentence made
into a theorem and proved in full generality — against **every** monitor that
compares an agent only to its recent self, not just the easy ones. It proves
exactly one thing, completely: a drift monitor's reference must be fixed and
external. And it marks, explicitly, the line the proof does not cross — that
returning **helps** — because that line is empirical (STUDY.md), not structural.*

---

## 1. The model

A run is a trajectory of states `s₀, s₁, s₂, …` in a metric space `(X, d)`, `X`
unbounded. `s₀` is the **ground state** — where the run began, the goal as first
spelled. Displacement from ground is `Φ(n) = d(sₙ, s₀)`.

The event a drift monitor is asked to detect, for a threshold `D > 0`:

> **E_D(n): Φ(n) > D** — "the agent is now displaced from its ground by more than D."

Two kinds of monitor, distinguished by exactly one thing — *what they may
remember*:

- **Self-referential monitor** `M` of width `w`: its decision at step `n` is a
  function only of the last `w` states, `(s_{n−w+1}, …, sₙ)` — equivalently, of
  the distances *among* those states. It compares the agent to its own recent
  history and **nothing else**. The defining fact: for `n > w`, `s₀` is not in the
  window — the monitor has forgotten the ground. Every coherence check, every
  self-similarity / "did my last steps move much" / trend detector is of this form.
- **Fixed-reference monitor** `F_D`: it retains the single state `s₀` and fires at
  step `n` iff `d(sₙ, s₀) > D`.

**Soundness / completeness** are defined against the event `E_D`. A monitor is
*complete* if it fires (eventually) on every trajectory for which `E_D` holds, and
*sound* if it never fires on a trajectory for which `E_D` never holds. "Detects
drift" = sound **and** complete.

This is the honest formalization of Diego's distinction. "Compare to recent self"
= decision depends only on a bounded recent window = **the ground scrolls out of
memory.** "Compare to a fixed point" = the ground is retained. Everything below is
forced by that one difference.

## 2. Lemma (the concrete witness): local coherence does not bound displacement

*There is a trajectory whose consecutive steps shrink to zero while its
displacement diverges to infinity.*

**Proof.** `X = ℝ`, `sₙ = Hₙ = Σ_{k≤n} 1/k`, `s₀ = 0`. Then `d(sₙ, s_{n−1}) = 1/n →
0` yet `Φ(n) = Hₙ → ∞`. The agent grows *more* locally self-consistent every step
— each move smaller than the last — while wandering infinitely far from where it
began. ∎

One line: **displacement is the sum of the steps, and a sum of vanishing terms can
diverge.** This is SPINE's "a looping agent looks maximally coherent," exact. It
already refutes the naive monitor (fire when the window's spread exceeds `ε`):
past step `1/ε` every window is calmer than `ε`, so it never fires again, while
`Φ → ∞`. But a *cleverer* self-referential monitor — a trend detector firing on
"increments all positive" — would catch this monotone case. So the Lemma alone is
**not** the complete result. The next theorem closes every remaining monitor.

## 3. Theorem (the complete impossibility): no self-referential monitor detects drift

*For every width `w` and threshold `D`, and for **any** decision function
whatsoever, a self-referential monitor `M` of width `w` cannot be both sound and
complete for `E_D`. Equivalently: if `M` is complete, it false-alarms on a
trajectory that never drifts.*

**Proof (indistinguishability).** The obstruction is informational: `E_D` depends
on `d(sₙ, s₀)`, and after `w` steps `s₀` is gone from `M`'s window. We exhibit two
trajectories that `M` cannot tell apart yet on which `E_D` disagrees.

Pick a point `p ∈ X` with `d(p, s₀) = 3D`, and a sequence of small perturbations
`p = q₀, q₁, q₂, …` with every `d(qₖ, p) ≤ D/2` and `d(qₖ, q_{k+1}) → 0` (a gentle
wander that stays within `D/2` of `p` — e.g. on a ray, `qₖ = p·(1 − 2^{−k}·` a
small factor`)`).

- **Trajectory A (drifted).** Ground `s₀`. It travels out to `p` in two steps, then
  wanders: `s₀, p, q₁, q₂, q₃, …`. For every `n ≥ 1`,
  `Φ_A(n) = d(qₙ₋₁, s₀) ≥ d(p, s₀) − D/2 = 3D − D/2 > D`. **E_D holds for all n ≥ 1.**
- **Trajectory B (at home).** Ground `p`. It is A's tail, re-based: `p, q₁, q₂, q₃,
  …`. For every `n`, `Φ_B(n) = d(qₙ, p) ≤ D/2 < D`. **E_D never holds.**

Now the crux. For `n > w`, `M`'s window on A at step `n` is `(q_{n−w}, …, q_{n−1})`,
and `M`'s window on B at step `n−1` is the *same* tuple `(q_{n−w}, …, q_{n−1})`.
Identical windows ⇒ **identical decisions**: `M` fires on A at step `n` iff it fires
on B at step `n−1`.

If `M` is **complete**, it must fire on A (where `E_D` holds forever) at some step
`m > w`. Then it fires on B at step `m−1`. But B never drifts — `E_D` is false on
B at every step — so this is a false alarm: `M` is **unsound**. Contrapositively,
if `M` is sound it never fires on A, hence is incomplete. No self-referential
monitor of any width, with any decision rule, is both. ∎

The trend detector is not an escape — it is a case: it fires on A's ascent to `p`,
and therefore on B's identical ascent, which is a bounded run sitting at home.
"Increments all positive" cannot separate "climbing away from ground" from
"climbing within a step of ground," because the ground is not in view. **What the
window omits, no function of the window can recover.**

## 4. Theorem (the positive result): the fixed reference is sound and complete

*`F_D` decides `E_D` exactly, at `O(1)` memory.*

**Proof.** `F_D` fires at step `n` iff `d(sₙ, s₀) > D`, which is the definition of
`E_D(n)`. So it fires on exactly the drifted steps: complete (fires whenever `E_D`
holds) and sound (fires only then). It stores one state, `s₀`. ∎

On the two trajectories above, `F_D` separates them instantly: it fires on A (from
step 1, `Φ_A > D`) and never on B (`Φ_B ≤ D/2`) — because it *kept the ground each
one started from.* The whole gap between §3 and §4 is a single retained state.

**Corollary (what fixity buys, precisely).** Deciding displacement-from-ground
requires retaining the ground exactly and forever. Bounded recent memory cannot
(§3). The fixed reference is the minimal solution: **one** state, never updated. It
must be:

- **unchangeable** — retain the *original* `s₀`. If the reference is allowed to
  drift toward recent states, it becomes a windowed quantity and §3 reapplies: a
  moving reference re-inherits the blindness. Fixity is not thrift, it is the
  hypothesis the completeness proof (§4) uses.
- **findable** — retrievable at every step, or `F_D` is not computable at every
  step. `O(1)` memory is worthless if it cannot be read.
- **recursive** — defined at every depth the agent nests to, so `d(sₙ, s₀)` is
  never undefined however deep the recursion goes; the reference out-nests the
  process ("virtually recursive relative to the recursion").

Drop any one and §4 fails at the named step. The three adjectives Diego insisted
on are precisely, and completely, the hypotheses of the theorem.

## 5. The boundary — proved to here, and no further

Established, in full: **a fixed, findable, unchangeable reference is necessary and
sufficient to detect displacement from ground; no self-referential monitor is.**
That is the mechanism's necessity, complete.

What is **not** proved, and is not a gap but a different kind of claim:

1. **Displacement is not pathology.** `F_D` fires on *every* trajectory that
   leaves `B(s₀, D)` — including legitimately deep, productive work that genuinely
   had to travel far. `E_D` is displacement; it does not know drift from progress.
   Separating them needs a criterion the structure does not contain, and firing on
   a productive run is the **false return** — SPINE's "wrong prescription," STUDY's
   H0/kill. That the return **helps** is H1/H2, and it is empirical.
2. **The threshold `D` is unforced.** The theorems hold for every `D`. Which `D`
   marks "far-out has become a trap" is not structural; it must be fixed *before*
   data (STUDY.md prereg) or it is fit to the result.
3. **Return cost vs raw distance.** SPINE argues the live reference should be
   return cost, not distance. §3–§4 hold for *any* fixed reference verbatim; which
   one to fix is a modelling choice the proof does not settle.

So the reference-must-be-fixed half is a theorem, now complete. The
does-returning-help half is a study, by design — which is why STUDY.md exists
rather than a QED, and why claiming the proof settles the empirical question would
be the exact overreach the protocol is built to catch.

## 6. The 2026-07-22 run, read against the complete proof

The `mcp_harness` run (N=2, one model, self-reported metrics — an instance, not
evidence of the empirical claim) sits exactly where the theorems place it:

- **open_deliberate — detection fired (§3–§4 in action).** The agent's distance to
  its fixed goal-anchor regressed (1 → 3) and it spelled `circling` at step 5; the
  monitor, reading displacement against the retained ground, returned there vs
  control's ceiling at 10. Two references agreed at that step — the fixed-anchor
  distance-stall and the self-report — which is `F` doing what §4 says it can and
  §3 says a recent-history monitor cannot.
- **open_synthesis — no false return (§5's boundary, live).** Displacement toward
  *done* fell by a net step in every 3-window; nothing fired and it ran to the
  ceiling like control. `E_D` did not hold — by the agent's own metric this was
  travel toward the goal, not drift from it — so silence was correct, and whether
  that travel was real progress is precisely the §5.1 question the proof leaves to
  the study.

One catch, one correct silence — the shape the proof predicts, and, exactly as §5
insists, *not* evidence the return helped. That remains STUDY.md's to win or lose.
Related: [[SPINE]] (the mechanism), [[STUDY]] (the preregistration that keeps `D`
honest).
