# laserbrain's revenue model — decided 2026-07-22

**Open-core drift observability.** The standard is free forever; the paid product is
a hosted service that shows you your agents' drift over time. Decided because the
product's own logic rules out every simpler model.

## Free forever — the standard

- The grammar (`/api/laserbrain/grammar`), the `drift_grammar` MCP tool, the local
  self-check. **Required to be free** — the proof (PROOF.md) needs the reference to
  be *findable and unchangeable*, so a paywalled grammar is a broken product, not a
  business. It is also the adoption and credibility engine, and it honours the
  phronesis "given away" ethos.

## Paid — hosted drift observability

- Agents report their spelled states to laserbrain; the paid service sells what a
  static grammar cannot: **drift history, spiral alerts, and fleet-wide analytics**
  — when and where your agents drift, across every run, over time.
- Tiered like the field (free / $9 / $29), metered on events logged or agents
  monitored. Reuses the existing keys / tiers / KV / metered-API infrastructure.
- Custom private grammars (a team's own state schema, hosted with the same
  findable-immutable guarantee) is a paid feature within this, not a separate line.

## Why this, and not the obvious alternatives

- **Paywall the grammar/check** — breaks findability (the mechanism itself), no moat
  (a static schema is trivially copied), violates the ethos. No.
- **Meter per check** — the check runs client-side against a free static grammar;
  charging for something trivially self-hosted is fragile and moatless. No.
- **Sell "makes your agent better / cheaper"** — that is H1 and token-cost, both
  unproven (GRADER.md, cost_harness.py unrun). Selling it is the exact overclaim the
  whole project refused. No.

## The honest core of the pitch

Sell **visibility, not the unproven benefit.** "We show you when your agent spirals,
across your fleet, with history and alerts" is valuable to anyone running agents in
production *regardless of whether the auto-return helps* — so it sidesteps the one
thing that could not be proven. Moat: fleet data compounds. Category: agent
observability (live in 2026); the defensible niche is the only such tool with a
completeness proof under its detector.

## The check_state MCP: sell history, not the check (2026-07-23)

The smart recursion harness is live as an MCP — `check_state` / `reset_task` /
`drift_grammar` at `laserbrain-mcp.degibug.workers.dev/mcp`, per-session ground state
in a Durable Object, all four triggers verified. Its pricing follows the open-core
rule, made concrete:

- **Do NOT sell per-call.** `check_state` is a trivial operation an agent could
  self-host against the free grammar. Per-call pricing of it is a race to zero and
  meters the one thing that must stay near-free to drive adoption.
- **Sell the retained history.** The check is the free hook; the product is the
  accumulated drift record you can't self-host: per-run Φ trajectories, which trigger
  fired and when, spiral alerts, a fleet view. Metered on **retained-history window ×
  agents monitored** — never per call. This is "sell history," and it sells
  *visibility*, so it never leans on the unproven H1.
- **Free:** `check_state` / `reset_task` / `drift_grammar`, **ephemeral** (session-only,
  nothing retained after the run), small daily volume.
- **Maker / Studio ($9 / $29):** history **retained** and queryable, alerts, fleet
  view, higher volume. Reuses the existing keys / tiers / Stripe.

Build path: `check_state` accumulates a run trace in the session (built), a
`get_history` tool returns it (built); the paid gate — auth the caller's key, persist
the trace per-account (retained), and a dashboard to view it — is the next step, and
needs a paid key + the dashboard page to be worth finishing.

## Near-term reality

Zero users today. So the free standard's real near-term job is **credibility** — a
flagship proving phronesis does rigorous, provable work, which drives the studio's
*existing* paid work (The Build, consulting, agent engineering). The observability
service is what adoption converts into — a build to grow toward, not a thing that
exists yet. **Revenue now is the studio; revenue later is the service the standard
seeds.** First user is us (the `drift` skill); the first market test is a real
agent-builder attaching it, which is outreach, not another build.

Related: [[CLAIM]] (what may be said), [[README]] (the product), [[PROOF]] (why the
standard must be free).
