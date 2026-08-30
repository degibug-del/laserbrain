# laserbrain — product directions, iterations, ideas, ideals

*Started 2026-07-22, kept open. Diego: "keep coming up with product design,
direction, iteration & ideas and ideals." A living list. Each item says honestly
whether it rests on something proven or is a bet. Grounded by [[CLAIM]] (say only
what's proven), [[REVENUE]] (free standard, paid observability), [[PROOF]].*

---

## Virtual context windows (Diego, 2026-07-23) — TOP post-H1 build

The continuity layer built 2026-07-23 (`/v1/self` + `remember_self`/`resume_self`)
**already is a cross-session virtual context window**: an agent's `now`/`mind`/`ground`
persist in the account KV and reload next session, so its effective context outlives
any single token window. And within a session, drift history externalises the trace
(`get_history`), so the agent needn't hold its whole trajectory in-context.

**The generalisation to build (after the H1 freeze lifts):** a general external
scratchpad keyed to the account — arbitrary context offload + **relevance retrieval**
(pull back the slice that matters for the current step, not the whole store). That is
a true virtual context window: the agent works against far more context than its literal
window holds, laserbrain storing and serving the rest. Rests on: the same account/KV/tier
infra; the same "sell retained state" model ([[REVENUE]]). Honest boundary: this is a
memory/retrieval layer (like a keyed RAG/scratchpad), NOT the proven drift detector —
keep the claims separate ([[CLAIM]]). Do not build before the H1 run is reported (freeze).

## Brand architecture (Diego, 2026-07-23)

**laserbrain is a subbrand of phronesis**, not a single product — its own line of
AI **software and robotics** products for agents. So:

- **phronesis** — **a design studio laboratory.** Diego's words, 2026-07-26, arrived at
  across three corrections: "phronesis is the thinktank", then "a design laboratory",
  then "a design studio laboratory". The line this replaces read *the modern design
  studio + thinktank ... funds the thinktank*, which made it two entities with a
  transfer between them. It is one thing, and it IS the thinktank — nothing separate is
  being funded.
- **laserbrain** — the subbrand / product line for agents. Under it:
  - *the drift-fixer* — an adaptive stop for agents (proven; the flagship).
  - *the field / "redtooth agent coupler"* — one shared live state agents read and
    write, coupling them through it ("two devices, one rhythm" — the redtooth idea,
    turned on agents). Whether coupling does more than correlate is the open,
    honest question; sell it as a shared reproducible state, not as sync-that-works.
  - *robotics* — active now as prototypes, not shipped hardware. The **adaptive
    alarm clock** (a motorized bedside clock that scans the sleeper and repositions
    within comfortable reach — displacement logic in hardware) has a live interactive
    prototype. **Grown fascial robots** — soft robots grown from fascia-like tissue —
    is the research vision behind the line (ties to the tissue-displacement thread).
    Keep robotics as prototype/roadmap on the site; don't claim shipped hardware.

**laserbrain's own descriptor (Diego, 2026-07-23): "active, adaptive, dynamic."**
Distinct from phronesis's "AI, tailored" — it names what every laserbrain product
is: the drift-fixer, the coupler, the alarm clock, all active/adaptive/dynamic
systems that read a state and move on it. Candidate subbrand tagline.

Also filed: **the smart recursion harness, as an MCP** — the folded token-
minimizer harness delivered as an attachable MCP (the `drift_grammar` tool is its
seed); an agent attaches and gets the adaptive stop, not just the grammar.

The site reflects this: phronesis is the studio; laserbrain the product line. Copy
says "our line of AI products for agents," honest that software is live and robotics
is ahead.

## Directions — the big bets

1. **Agent observability, drift-first.** The decided revenue path ([[REVENUE]]).
   The category exists in 2026; the wedge is the *only* drift detector with a
   completeness proof under it. Own "when and where does my agent spiral" the way
   Sentry owns errors. Everything below serves this or seeds it.
2. **The open standard play.** The grammar is free and findable (the proof demands
   it). Push it to *become* the standard way an agent spells its state — so that
   "laserbrain-grammatical" is a thing agents are, like "OpenAPI-described." The
   standard is the moat's foundation; the service is the moat.
3. **The proof as the marketing.** Most agent tools assert; laserbrain proves. The
   theorem ("your agent cannot catch its own drift — here's why") is stronger
   content than any feature list. Lead with it everywhere.

## Iterations — near-term builds, in rough order

1. **Observability MVP.** `POST /v1/drift` ingest (an agent posts its spelled
   state), store on KV/D1, a `/laserbrain/dashboard` page: per-agent drift
   timeline, the step it drifted, a spiral alert. This is the paid product's first
   real surface. Reuses the keys/tiers already built.
2. **A drift score, 0–1.** One legible number per run from the four signals +
   displacement Φ. Teams track it, alert on it, chart it. A metric is easier to
   sell than a mechanism.
3. **Client SDKs, tiny.** Python + TS: fetch the grammar, help spell state, run the
   four checks locally. Makes "attach it" a two-line import — the adoption barrier
   is friction, and this removes it.
4. **Framework adapters.** Middleware for the Claude Agent SDK first (home turf),
   then LangGraph / CrewAI: auto-spell state each step, auto-check drift. Meet
   agents where they already run.
5. **The `drift` skill, distributable.** Package the skill (already live for us) so
   any Claude Code user adds laserbrain in one line. First real adoption vector,
   costs nothing.

## Ideas — features, smaller

- **Drift replay / postmortem.** When an agent spirals, show the replay: the step
  it drifted, the state there, the return-cost curve climbing. A debugger for agent
  failure, not just an alarm.
- **Fleet view.** Which tasks induce drift, which agents drift most, drift rate over
  time. The observability tier's killer feature for teams.
- **Custom grammars registry.** Teams host their own state schema with the same
  findable-immutable guarantee. A paid feature, not a new product.
- **Public benchmark + leaderboard.** Turn the open H1 question into engagement:
  invite others to test "does drift-fixing help on task X." Community answers what
  one lab pilot couldn't, and generates data.
- **Live demo on the page.** An animated agent spiraling, laserbrain catching it —
  the four signals firing in real time. Show, don't tell, on the marketing page.
- **Site: the four signals as one diagram.** A single clear visual of the loop
  (spell → check → return). Legibility, made visual.

## Ideals — what it must stay true to

- **Free where the proof requires it.** The grammar is findable and unchangeable,
  therefore free, forever. Never paywall the reference; that breaks the mechanism.
- **Claim only what's proven.** Detection (theorem) and fewer steps (measured) —
  never "smarter" or "cheaper" until shown. The honesty is the brand, not a
  constraint on it. The `<i>what we don't claim</i>` box stays on the page.
- **It's phronesis's first principle, shipped.** *Return to ground* is the whole
  studio's idea; laserbrain is that made into infrastructure — an agent that knows
  when it's lost and comes home. The "feels math" mission, applied to machines.
- **A rung on the consciousness ladder.** An agent measuring itself against a fixed
  external invariant is a minimal, concrete model of metacognition — self-monitoring
  that provably can't be done from the inside. laserbrain is the thinktank's
  question ([[consciousness-is-the-goal]]) made small enough to run. That's not
  marketing copy; it's why this is worth doing beyond revenue.

## Open decisions (Diego's, not mine to make)

- **Papers + 961 deposits: nav or not?** They're deliberately minimal reading
  surfaces. Adding the product link means editing the generators and trading against
  that minimalism. A design call.
- **Monetize the drift-fixer directly, or keep it a free standard funding the studio
  by credibility?** [[REVENUE]] picks observability-as-service; whether to push that
  now or let the standard spread free first is a timing call.
