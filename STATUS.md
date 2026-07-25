# Where we are — the smart recursion harness (resume from here)

*Log written 2026-07-23 so the next session continues without re-deriving. This is
the snapshot + how-to-resume. Deeper detail lives in the docs named below.*

## What laserbrain is now

- **phronesis** rebranded to **"AI, tailored"** — a modern design studio + thinktank
  tailoring AI for agents. **laserbrain** is a **subbrand** (descriptor: "active,
  adaptive, dynamic") with a software line and a robotics line.
- The drift-fixer's product name is the **smart recursion harness** (renamed from
  "adaptive"; canonical everywhere as of 2026-07-23).

## Live and verified

- **Remote MCP** — `laserbrain-mcp.degibug.workers.dev/mcp`. Tools: `check_state`,
  `get_history`, `reset_task`, `drift_grammar` (+ field tools). Stateful per session
  via a Durable Object (holds ground state, distHist, run trace). All four triggers
  verified live (grounded / self-report / goal-drift / stalled); `get_history`
  returns the run trace. Worker: `phronesis-world/workers/laserbrain-mcp-remote`.
- **Local MCP** — `phronesis/lasermind/mcp-server.mjs` (stdio, offline, in-process
  state). Same four harness tools added. It's the connected `laserbrain` MCP in
  Claude Code — **the new tools activate on the next session restart** (MCP spawns at
  session start; the running one is the old field-only version).
- **Grammar** free at `phronesis.world/api/laserbrain/grammar` (findable, immutable).
- **Site**: `/laserbrain` leads with the harness (`check_state` on "Attach it");
  `/laserbrain/robotics` (3 modes + fascial-driven research); laserbrain in the nav
  sitewide; rebrand swept through home, /about opening, meta, /identity/make.
- **Token result**: folded harness = **~91% fewer tokens vs an unmonitored spiral**
  (real; N=3). Honest caveats: a dumb budget is marginally cheaper; H1 (does the stop
  keep the answer) still unproven. `cost_harness.py`.

## Docs (all in this dir)

PROOF (detection theorem, complete) · SUBSTRATE (the metric) · STUDY (H2 coverage +
amendments) · GRADER (H1 pilot, inconclusive) · CLAIM (what may/may-not be said) ·
REVENUE (sell history, not per-call) · ROBOTICS (placement robot + fascial vision) ·
IDEAS (roadmap) · SPINE (mechanism — **needs the theory below folded in**).

## Theory produced but NOT yet written into SPINE.md

- **Meaning as ground state.** A task is a sentence grounding toward meaning ("the
  cat sat on a mat"); recursion is the return to it. Entities are the anchor, the
  relation is what grounds; distance = groundedness.
- **Syntax vs meaning grammar.** Syntax = well-formedness (`grammatical()`, decidable
  locally, *saturates* — a spiral spells valid JSON). Meaning = grounding (displacement
  vs the fixed reference, *not* locally decidable — the proof). Every "agent reflects
  on itself" loop is a syntax check, hence provably blind. laserbrain is a meaning
  check. Current schema = syntax grammar + first-order meaning grammar bolted on; the
  frontier is a native meaning grammar (measure concreteness of the relation directly).
- **Harness for agentic dialogue.** A dialogue is collective grounding toward shared
  resolution; drift modes = echo/agreement spiral (circling), topic-drift, deliberation
  stall. Turn-coherence saturates; you need the fixed goal to see the spiral. Closes
  back to phronesis's founding thesis (coherence = correlation of two, held over time).

## ReactBench — set up, oracle-GREEN, awaiting the run

The benchmark to get a **ground-truthed H1 number** (Pass@1 + tokens/turns), no LLM
judge. Repo: `~/reactbench`. Status:

- Cloned; `uv sync --python 3.13` (3.14 breaks litellm's Rust build — **must pin 3.13**).
- Docker: **Docker Desktop for Mac cannot run it** — ReactBench needs nftables egress
  control (allowlist the model API, block the rest); Docker Desktop's kernel lacks
  `CONFIG_NFT_FIB_INET`. **Fix: Colima** (`brew install colima`, `colima start --cpu 4
  --memory 8 --disk 60`) — real Ubuntu kernel 6.8, works. **Docker context is now
  `colima`** (switch back: `docker context use desktop-linux`; the benchmark needs
  `colima`). **The VM stops between sessions** — if "Docker not reachable", run
  `colima start` (fast; the VM persists); `brew services start colima` auto-starts it.
- **Oracle passes reward 1** on Colima (`uv run --python 3.13 harbor run -p
  tasks/hello-react -a oracle`, 2m). Harness grades correctly end-to-end.
- **Next (needs funded ANTHROPIC_API_KEY):** run `claude-code` on N tasks control vs
  harness, score Pass@1 + turns/tokens. Inject the drift-fixer as (a) a CLAUDE.md
  discipline first, then (b) bundle `mcp-server.mjs` into the agent (offline). The
  agent adapter is `harbor/agents/installed/claude_code.py`.
- **Integrity:** ReactBench ships a canary and asks its task contents stay out of
  training corpora — keep task instructions/solutions out of transcripts.
- Honest caveat: coding tasks *have* a criterion; our finding says recursion needs its
  absence, so it may show little effect — but a ground-truthed either-way is the point.

## The immediate next moves (pick up here)

- ✅ **DONE — theory in SPINE.md** (syntax-vs-meaning grammar, meaning-as-ground-state
  cat→mat, the agentic-dialogue frame that closes phronesis's coherence thesis).
- ✅ **DONE — observability MVP.** `/v1/drift` ingest (auth'd, per-account, tier-gated
  retention: free 1h / paid 30d) + read-back (`/v1/drift/runs`, `/v1/drift/run?id=`),
  verified on the free path (mint key → post steps → runs → trace). Dashboard at
  `/laserbrain/dashboard` (paste key → runs → per-run Φ timeline), linked from
  /laserbrain. Shared check in `workers/laserbrain-mcp-remote/src/drift.ts`. Paid 30d
  retention is coded and gated by `tier.name` but untested (no paid key). Next layer:
  alerts + fleet view (the paid features), and auth the MCP's check_state to persist
  too (right now only `/v1/drift` persists; the MCP session trace is ephemeral).
- ⏭ **NEXT — run the ReactBench experiment (needs a funded ANTHROPIC_API_KEY).**
  Script written + validated (turnkey): `~/reactbench/laserbrain_experiment.sh` +
  `~/reactbench/drift-discipline.md` (the injection). Runs `claude-code` **control vs
  harness** (harness = `--append-system-prompt` the drift discipline) on N tasks,
  reads Pass@1 from `result.json` + best-effort tokens, prints the comparison. Run:
  `read -rs K && ANTHROPIC_API_KEY=$K bash ~/reactbench/laserbrain_experiment.sh`
  (knobs: `MODEL=... TASKS="a b c"`). **First-run caveat:** confirm Harbor forwards
  `--append-system-prompt` on `run` — if not, the harness log says so; pass the flag
  via your Harbor version's agent-config and rerun. Oracle-green on Colima; `docker
  context` is `colima`. Honest expectation: coding tasks have a criterion, so it may
  null — but a ground-truthed either-way is the point.
  - **ReactBench blocked on this Mac (2026-07-23).** The run surfaced two things: the
    injection flag isn't a `harbor run` option (needs a JobConfig `-c`, small), and —
    the real wall — the agent can't reach the model API through the container's
    egress-control sidecar on Colima: `UNKNOWN_CERTIFICATE_VERIFICATION_ERROR` (0
    tokens, $0; the oracle passed only because it never calls a model). Mac/Colima-
    specific egress-TLS wall; the networked clean-room is a Linux thing. Left set up +
    oracle-green for whenever a Linux box exists.
  - **PIVOT → `codebench.py` (this dir): the local H1 harness, validated, awaits the
    key.** 3 debug/loop-prone coding tasks with hidden unit tests (Pass@1), control vs
    harness (harness injects return-to-ground on drift). Runs on the Mac (agent hits
    the API directly, no egress), never shows the agent the tests. Ground truth proven
    (buggy starts fail, correct solutions pass). Run:
    `read -rs K && ANTHROPIC_API_KEY="$K" python3 lasermind/codebench.py`
    (knob: `SEEDS=n`, default 3).
  - **First pilot run (2026-07-23, haiku, 1 seed each) — LOOKED like a win, was
    confounded; DO NOT bank it.** control Pass@1 2/3, harness 3/3, ~14× fewer tokens.
    But the only decisive task (balanced-brackets) was solved by the harness run at
    STEP 1 — before drift can be detected (needs ≥2 steps) — so the intervention NEVER
    FIRED. Step 1 uses an identical prompt in both arms; the harness "win" is first-draft
    sampling luck, not the mechanism. The other 2 tasks nulled (both one-shot). Real
    datum: control DID spiral on balanced-brackets (12 steps, 26k tok, never solved) —
    the phenomenon is real in haiku; but the harness's own run didn't spiral, so the fix
    is untested. **Upgrade shipped:** codebench now runs `SEEDS` replicates and reports
    the **mechanism isolated** — of harness runs where the intervention actually FIRED,
    how many recovered — vs control's per-task spiral rate. That block, not overall
    Pass@1, is the H1 signal. Next: run `SEEDS=5` (or more) to get fired runs.
  - **SEEDS=5 run (2026-07-23, haiku, N=15/arm) — NEGATIVE for H1 on this benchmark.**
    control 15/15 Pass@1 @ 26k tok (barely spirals: 0/5 per task); harness 12/15 @
    115k tok (4.4x). Mechanism isolated: fired 4/15, recovered 1/4; all 3 ceiling-
    failures were harness fired-runs, control 0. No upside, downside signal (3-vs-0,
    ~p=0.11 — suggestive not significant). Read: these tasks HAVE a criterion (unit
    tests), so the baseline doesn't spiral — the stall rule then false-fires on a
    distance plateau and the nudge derails a productive run. **Theory-consistent** (the
    docs predicted a null on criterion-present tasks; we now have the sign, and it is
    negative). Recorded in [[CLAIM]] H1 ledger. **Implication: coding/oracle benchmarks
    are the WRONG bed — the harness's domain is criterion-ABSENT, long-horizon agentic
    work with no unit-test oracle. Testing H1 for real needs such a task set.** Do NOT
    tune detector thresholds to rescue this number (p-hacking); change the test bed.
- Loose ends: `styler.html` prototype unpublished; `.mcpb` bundle for distribution;
  SpreadsheetBench V2 as a second benchmark.
