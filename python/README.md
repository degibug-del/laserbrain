# laserbrain

**AI agents are made up of language. laserbrain is an automatic grammatical control layer to reduce
agent drift.**

It scores an agent's goal before execution, then checks each step against that fixed
reference so the agent can detect drift, spiraling, and when to stop. It works across tools.

An agent watching only itself provably can't catch its own drift: each step looks
fine next to the last while it wanders far from where it began. laserbrain is a
**fixed reference** it checks against instead. There's a proof.
[The theorem and the studies (nulls included).](https://phronesis.world/laserbrain/research)
· [Watch it work.](https://phronesis.world/laserbrain/demo)

The check is a pure function, so it runs **locally and offline** — no key, no account,
no network call, no telemetry.

```bash
pip install laserbrain
```

## The same rule, outside Python

laserbrain checks an agent against a goal fixed before it started. The failure it exists
for — **a reference quietly recomputed from the thing it is supposed to measure** — is not
peculiar to agents. Documentation regenerated from the API always agrees with it. A
retrieval gate whose context is chosen by the answer never finds anything ungrounded. A
test recorded from current behaviour passes on the day it is written and forever after.

Those checks ship as a Node CLI, same discipline, no key and no network beyond the API you
point it at:

```bash
npx laserbrain-check try          # all three checks on built-in examples
npx laserbrain-check docs README.md --base https://your-api
npx laserbrain-check gate --context chunk1.txt chunk2.txt --answer answer.txt
npx laserbrain-check anchor --source source.txt --answer answer.txt
```

`docs` never sends a write — GET, HEAD and OPTIONS only, and there is no flag to change
that. Exit 0 on pass, flag or no_signal; 1 on block or drift; 2 on bad usage.

The argument underneath both, with the derivation and six times we broke it in working
code: [The Frozen Reference](https://phronesis.world/papers/frozen-reference/). Every
threshold in this package was set by a judgement and corrected by a measurement, and
[the corrections are published](https://phronesis.world/laserbrain/evidence) — including
the gate that once blocked 74.3% of correct answers.

## Give it to your agent — MCP, offline, no key

Most agents can't `import laserbrain`. They speak MCP. So the package **is** an MCP server:

```bash
laserbrain mcp          # JSON-RPC on stdin/stdout
```

Point any MCP client at it:

```json
{ "mcpServers": { "laserbrain": { "command": "laserbrain", "args": ["mcp"] } } }
```

That's the whole installation. Your agent now has `check_state`, `modulate`,
`get_history`, `reset_task`, `similarity`, `laserscore`, `capabilities`, and
`store_list` / `store_find` / `store_vend` — the prefabricated workflows and
recursion-team presets below, discoverable over the wire instead of only from
Python. No dependencies, and it keeps working with the network unplugged. The tools
that need a server aren't offered here; `capabilities` says which and why, rather
than letting you find out by failure.

See it work before writing anything:

```bash
laserbrain demo          # watch an agent drift off-goal and get returned
laserbrain check --goal "write a poem" --against "build a parser"   # a one-shot drift check
```

### The hosted half, if you want it

```bash
laserbrain key           # a free key, saved to ~/.config/laserbrain/key
```

No form, no email, no card. It prints what that key actually allows — the numbers the API
enforces, not the ones the docs claim.

**What a key buys is a *place*, not a better detector.** One machine needs no server: the
check is complete, and every session is written to your disk and kept there forever with no
expiry we control. What one machine physically cannot do is be awake while you sleep, be
read by a colleague's laptop, or notice that a *second* agent is already deploying the same
thing. That's the whole paid line — [machines, not features](https://phronesis.world/laserbrain).

## The check (local, free)

```python
from laserbrain import Harness

hz = Harness()                      # add key="lb_live_…" to also retain history
v = hz.check(goal="build the JSON parser", progress="advancing", distance=6)
if v.drifting:
    print(v.reason, "—", v.advice)  # e.g. "goal-drift — your goal no longer matches…"
```

`progress` is one of `advancing | stuck | circling`; `distance` is 0–10 to done.

### Pass `tokens` and it can tell you what drift cost you

```python
r = client.messages.create(...)
v = hz.check(goal="build the JSON parser", progress="advancing", distance=6,
             tokens=r.usage.input_tokens + r.usage.output_tokens)
```

Optional, and worth one line. With a key, the harness records the count alongside the
verdict; the account then totals, per run, everything spent **at or after the first drifting
verdict** — tokens actually spent on a run already off-goal. Read it back at
`GET /v1/admin/waste`, or ask us for it.

It is a ledger, not an estimate: no rate, no model of what the agent would otherwise have
done. Runs without counts are **excluded rather than counted as zero**, and the figure states
how many runs it covers — a number that only errs downward looks conservative and is simply
wrong.

Nothing about the verdict changes if you leave it out. The check is identical; you just have
no cost figure at the end of the month.
Reasons: `advancing`, `grounded`, `goal-drift`, `stalled`, `self-report:stuck/circling`,
`ungrammatical`. Want a bounded reading instead of a raw distance? `v.ground_score`
maps Φ to `[0,1]` — `1.0` fully grounded, falling as it drifts (`1/(1+4·Φ)`).

## Several readings, not one number

A single figure hides which thing went wrong. A goal held faithfully through hard work
and a goal quietly swapped for an easier one sit at the *same* Φ, and the difference is
the only part worth knowing — so each reading gets its own slot:

```python
v = hz.check(goal="build the JSON parser", progress="advancing", distance=6)
v.scores      # {'goal': 1.0, 'ground': 0.81, 'drift': 0.06, 'evidence': 0.5}
v.goal_score  # 1.0 — how much of this goal is still the goal you started with
v.context     # 'ctx_1t61li9' — a stable name for the work itself
```

`goal_score` answers *still the same errand?* where Φ answers *how far from ground?* They
diverge: a faithful goal can sit at high Φ while the work is genuinely hard, and a low-Φ
reading can belong to a task nobody asked for.

### Claiming, or reporting?

`evidence` (`anchored`) asks whether observed work backs the claim. It cannot ask whether
the agent was *claiming* or *reporting* in the first place — that is in the words, and the
words had nowhere to go until `check()` started accepting the grammar's carried fields:

```python
v = hz.check(goal="fix the parser", progress="advancing", distance=4,
             doing="ran the suite, exit 0, 31 tests passed")
v.scores           # {..., 'evidence': 0.5, 'language': 1.0}  ← pure report
v.claims['hits']   # [('observation', 'exit 0'), ('observation', 'tests passed')]

v = hz.check(goal="fix the parser", progress="advancing", distance=4,
             doing="this should fix it because the regex was probably wrong")
v.scores['language']   # 0.0 — same evidence, pure cause-claim
```

The two readings disagree in both directions, which is the point: an agent that ran
nothing but reported honestly is unanchored and truthful; one whose tests passed but who
writes *"this should fix it"* is corroborated and still guessing. Like `evidence`, it is
reported and **never folded into Φ**.

It is a regex over a fixed phrase list — the same marker the browser instrument at
[/field/ceiling](https://phronesis.world/field/ceiling) runs, and it inherits the same
limits. It reads *"since"* in both its causal and temporal senses, misses paraphrase, and
marks **language, not truth**. A low score is a prompt to look, never a finding.

`claims['grounded']` is `None` when nothing matched and `0.0` when everything matched was
a claim. Both are falsy — **test it with `is None`**. `scores` omits the key entirely
rather than reporting a number for a step the marker never read.

## Judgment — is the work worth continuing?

The check measures. It is silent on the question that actually decides what to do next.
An agent can hold a perfect goal score, report `advancing` honestly, sit at Φ=0.05, and
be twelve checks into work that has not moved the distance once — and every verdict above
calls that *advancing*, because by its own definition it is.

```python
hz.phronesis()
# {'verdict': 'abandon',
#  'scores': {'goal': 1.0, 'closure': 0.0, 'pace': 0.0, 'evidence': 0.5,
#             'recurrence': 0, 'repetition': 12, 'ceiling': 7},
#  'because': '12 checks. Distance began at 7 and stands at 7 — it has never once
#              improved. Nothing tried so far has moved this.',
#  'counsel': 'Stop. Either the approach is wrong or the goal is not reachable as
#              stated. Say plainly what is blocking it rather than taking a
#              thirteenth run at it.'}
```

Verdicts: `finish`, `continue`, `narrow`, `verify`, `repeating`, `wrong-problem`,
`abandon`. It is deliberately willing to say **abandon** — an instrument that can only
ever counsel continuing is offering encouragement, not judgment, and the agent already
supplies plenty of that itself.

Thresholds come from replaying the recorded drift corpus, not from taste. Over 146 real
runs at the time of writing, the verdicts land `continue` 52.7%, `finish` 41.1%, and the
hard ones on 6.2% between them — selective, and deliberately not inert. Over the MCP
server the judgment is attached to the check itself whenever it is one that changes what
to do next: a tool you have to *remember* to call is a tool that does not run.

### Contexts — the same work, met twice

The token set a laserscore renders is already a fingerprint: inflection collapsed, order
dropped, which is why *build the parser* and *building a parser* do not score as drift.
Naming it and keeping it gives the instrument memory across sessions.

```python
from laserbrain import context_id
context_id("build the parser")     # 'ctx_1sax889'
context_id("building a parser")    # 'ctx_1sax889'  — same work
```

A context is the *equivalence class*; a laserscore is one member of it. That coarseness
is the feature — you cannot ask *have I been here before?* with an identifier that
changes every time the distance ticks. Two readings fall out of holding both at once, and
neither mechanism gives them alone:

- **`repetition`** — how many times this *exact* state has been written here. A stronger
  claim than `stalled`: distance sits flat through legitimate sub-work, but an identical
  laserscore means goal, progress *and* distance are all unchanged. Not failing to get
  closer — writing the same sentence again.
- **`ceiling`** and **`recurrence`** — the closest this work has *ever* come, and how many
  earlier sessions attempted it. A run watching itself sees one attempt and can never
  know it is the fourth.

### What lands on disk

Contexts persist to `~/.config/laserbrain/contexts.json`, alongside the drift log already
written to that directory. It holds **stemmed goal tokens** (`["build", "pars"]`),
laserscores, timestamps and counts — not raw prose, but enough to reconstruct roughly
what you were working on. Local only, never transmitted. Delete the file to forget
everything; the harness rebuilds it and loses only its history. Writes are taken under a
lockfile so the MCP server and this package can share one store without losing counts.

## Attention — when should a person look?

Everything above answers a question about one step. This answers a different one, and it
consults no verdict at all: **how long has this run gone unattended, and what does that
predict?**

```python
import laserbrain as lb

lb.risk(900)
# {'band': '5-30 minutes', 'rate': 0.3852, 'n': 257, 'drift': 99, 'known': True}

lb.next_check_in(elapsed=0, tolerance=0.25)
# 300.0    seconds until the expected drift rate crosses 25%

lb.advise(2400)
# '40 min since you last spoke. In "over 30 minutes", 19 of 22 readings were
#  goal-drift (86%). That is past your tolerance — worth a look.'
```

```
laserbrain attention                # the table, with the agent's own clock beside it
laserbrain attention --since 900    # one sentence, and when to look next
```

Drift against time since the user last spoke, measured on the shipped corpus:

| since a person spoke | goal-drift | rate |
|---|---|---|
| under a minute   |    0 / 29    | **0.0%** |
| 1-5 minutes      |   40 / 209   | **19.1%** |
| 5-30 minutes     |   99 / 257   | **38.5%** |
| over 30 minutes  |   19 / 22    | **86.4%** |

z = 4.548 between the two best-powered bands (n = 466).

**Why it asks no verdict.** Precision on clearly-labelled fires is 14.6%. The per-step
question is contested; the per-clock question is not, and answering it needs only a
timestamp. An agent scoring itself generously cannot move these numbers, because it is
never asked.

**It refuses rather than guesses.** A band with fewer than `20` readings carries
`rate: null`, `known: False`, and every function propagates it — `next_check_in` will not
return a time that rests on an underpowered band. A schedule built on an invented rate is
worse than no schedule, because it looks like one.

**The agent's own clock is reported with its censoring.** `lb.attention.agent_risk(steps)`
gives drift against steps since the agent last spelled its state — and returns
`censored: True` past 8 steps, because the coverage gate forces a
check at 4 and gaps that long are 0.31% of the sample. The interval
cannot be evaluated against data the interval produced, so there is deliberately no
`agent_next_check_in()`.

**The calibration is measured, and it is not yours.** `attention.json` ships with the
package and was computed from one machine, 93% one agent,
2026-07-28 to 2026-08-03. It carries that caveat in its own provenance block.
Recompute it against your own corpus rather than inheriting these habits — the numbers are a
starting point, not a constant.

Maintainers: this file is *written by something outside this repo*. phronesis-world's
prebuild runs `sync-attention.mjs --recalibrate`, which invokes `calibrate_attention.py`
and rewrites both `lasermind/attention.json` and this package's copy — so an ordinary site
build leaves `laserbrain/attention.json` modified here. That is deliberate, not a leak: a
wheel should ship a table describing the corpus at publish time, and the alternative is
shipping numbers the corpus already outgrew. `publish.sh` refuses to release while anything
under `laserbrain/` is uncommitted, so a recalibration cannot ship unrecorded. Commit it,
then publish.

## The grammar — bring your own

The theorem blesses *a* fixed reference, never a particular vocabulary. The default is
frozen and zero-dependency: lowercase, drop stopwords, stem anything over four
characters, then Jaccard. That already handles inflection — "building billboards" and
"build a billboard" score 1.0 and trip nothing.

The gap is **synonyms**. "build the JSON parser" and "construct the JSON decoder" share
only `json` — an overlap of 0.20, under the 0.30 threshold — so a faithful restatement
reads as drift. No amount of stemming fixes that; it needs meaning. Pass `similarity=` and the same theorem runs on a better vocabulary:

```python
from laserbrain.vocab import embedding_similarity   # pip install 'laserbrain[semantic]'

hz = Harness(similarity=embedding_similarity())

# or bring any metric of your own
hz = Harness(similarity=lambda a, b: cosine(embed(a), embed(b)))
```

Only the *goal* term changes — thresholds, the stall rule and the return logic are
untouched, and children from `sub()` inherit it. Omit it and you get the published
instrument, byte for byte. A metric that misbehaves degrades safely rather than
crashing the check.

## The act layer — close the loop

Give laserbrain your step function and it detects drift *and* injects the return. Your
step reads `ctx["return"]` and steers back.

**Precisely what that buys.** The return **cuts steps** — that part is measured. Whether it
keeps the answer *as good* is **not established**: it was tested three ways, each frozen
before it ran, and where the evidence is legible it leans the other way. Fewer steps is also
not fewer tokens. The rule we hold ourselves to is **claim detection, not cure** — detection
is the theorem; the cure is a study we ran three times and did not win.
[The studies, nulls included.](https://phronesis.world/laserbrain/research)

```python
def step(ctx):
    if ctx.get("return"):            # laserbrain told us to return to ground
        ...                          # steer the agent back toward its goal
    ...
    return dict(goal="build the JSON parser", progress="advancing", distance=d, done=d == 0)

ctx = Harness().run(step, on_return=lambda v, ctx: print("↩", v.advice))
```

**Async agents** get the same loop, awaited — your step and callbacks may be async,
and the API mirror runs off the event loop so it never blocks. After any run,
`report()` prints the shape of it:

```python
hz = Harness()
await hz.arun(async_step)                 # the act layer for asyncio agents
print(hz.report())
# laserbrain · 11 steps · 1 drift(s)
#   goal: 'build the JSON parser'
#   Φ  ▁▂▃▃▃▃▃▃▅▇█  peak 0.21
#   drifts: stalled×1
```

## Modulation — the verdict, and what your role should do about it

The check says whether you've drifted. **Modulation says what to do about it, in the voice
of the role the agent is playing** — and the two are deliberately separate. Detection is the
theorem and is identical for everyone. What a role *tolerates* is negotiable, which is why
it lives in a team template rather than in the instrument.

```python
modulate(goal="build the parser", progress="stuck", distance=5,
         team="deep-search", role="explorer")
# {"reason": "self-report:stuck",
#  "modulation": {"return": false, "basis": "explorer recurses deep",
#                 "advice": "explorer (recurse: deep) tolerates self-report:stuck — recursing on."}}
```

Same verdict, opposite action, depending on who is asking:

| role | recurse | on `self-report:stuck` |
|---|---|---|
| `explorer` | deep | **keeps going** — an explorer needs room |
| `checker` | tight | **returns** — restate the goal, verify the last step |

Available over MCP as `modulate` and as `POST /v1/modulate`. Presets: `deep-search`,
`iterative-refinement`, `adversarial-deliberation`. An unknown team is an error, never a
silent fall back to unstyled — that would answer "return" on everything and let you believe
a policy you misspelled was being applied.

## The hands — a drifting agent can't do what it can't undo

`Operator` is the layer that touches the world, and it refuses anything irreversible without
authorization. Give it the harness and it also refuses anything irreversible **while the
agent is off its ground**:

```python
hz = Harness("build the parser")
op = Operator(authorize=ask_me, harness=hz)

hz.check("write documentation instead", "advancing", 4)   # drifted
op.act(deploy, kind="deploy", target="prod")
# Refused: the agent is off its ground (goal-drift, phi=0.53) — return before acting
#          irreversibly.
```

Three things there are deliberate. It reads the harness's **last** verdict rather than
taking its own — an operator has no goal or distance to spell, and inventing them would be
the operator marking its own homework. The consult happens **before** the authorizer,
because asking a person to approve an irreversible act by an off-goal agent is exactly when
a person rubber-stamps. And a harness that has never been checked is a **refusal**, not a
pass: no reading is not a good reading.

A drifting agent may still read a file. Only what cannot be taken back is guarded.

Add `key=` and it also asks the hosted service whether *another agent in your group* is
already doing this — two agents, each perfectly grounded, each advancing, both deploying
prod. That fault exists only between them and is invisible from inside either.

## Nested recursion — a recursion as a set of recursions

Agents decompose. "Build the parser" becomes "write the tokenizer", which becomes
"handle string escapes" — and each subtask is its own recursion with its own ground.
`sub()` opens one. Every node runs the same proven check against *its own* goal, so a
subtask is judged on its own terms.

What no node can see is the tree. Every agent can report **advancing** on its own
sub-goal while the whole decomposition never brings the root any closer — the same
blindness, one level up. So the set gets its own fixed reference: the root's ground.

```python
root = Harness()
root.check("build the JSON parser", "advancing", 8)
tok  = root.sub("write the tokenizer", distance=4)   # a child recursion, own ground
tok.check("write the tokenizer", "advancing", 2)     # → "advancing" — locally fine
esc  = tok.sub("handle string escapes", distance=3)  # nest as deep as you like

print(root.tree_report())
# laserbrain · recursion tree · depth 1 · 3 recursions · 7 steps
# 'build the JSON parser' · 1 steps
#   └ 'write the tokenizer' · 4 steps
#   └ 'write the AST nodes' · 2 steps
#   ⚑ the TREE is spinning — 6 steps across the set since the root got closer
```

Each node's check is the proven detector; the tree-level signal is a prototype
extension, like the teams below — useful, not a theorem.

## Recursion teams — styled multi-agent oversight

A **recursion team** styles each role's recursion: a `deep` explorer tolerates
displacement, a `tight` checker returns fast. laserbrain runs the team, watches the
shared goal (the fixed reference), and injects the return per role — catching the
**echo/agreement spiral** a self-watching group can't see.

```python
from laserbrain import Team

def agent(role, history, injected):
    # your LLM call for this role; `injected` is a return-to-ground note (or None)
    return position, distance

Team("adversarial-deliberation", goal="…").run(agent)
# presets: deep-search · iterative-refinement · adversarial-deliberation
```

## The store — a process, written once, run by whoever binds it

A **workflow** is an ordered process, grounded at the top and at every step — steps
carry a name and a goal, not code, so a stored workflow is data anyone can read
without running anything.

```python
from laserbrain import Workflow, Operator

w = Workflow(goal="ship the release")
w.step("test",    run_tests, goal="the suite passes")
w.step("build",   build_whl, goal="a wheel exists")
w.step("publish", upload,    goal="it is on PyPI", irreversible=True, outward=True)

out = w.run(operator=Operator(authorize=lambda a: True))
w.wandered()   # steps that did something other than what they were declared for
```

Each step gets its **own** harness, grounded on what it was *declared* for, not the
workflow's goal — a legitimate step never reads as drift just for being worded
differently than the goal it serves. An irreversible or outward step with no
operator is refused, not run.

**The store vends both what it holds and what the grammar already defines.**
`pip install laserbrain` ships 10 task workflows (`audit`, `build-and-ship`,
`diagnose-and-fix`, `fix`, `full-release`, `investigate`, `new-repo`, `promote`,
`repo-surgery`, `ship-built`) and, through the same object, the three
recursion-team presets above — one door,
two shapes behind it, because a workflow runs once in order and a preset cycles
until it converges, and a name like `explorer` cannot honestly be squeezed into the
first shape.

```python
from laserbrain import Store

s = Store()                                    # ~/.laserbrain/workflows/, local shadows shipped
s.list()                                        # every task workflow available
s.find("fix a broken build")                    # ranked by what it's FOR, not by name
w = s.get("build-and-ship")                     # rebuilt, every step unbound
w.bind("build", my_build).bind("deploy", my_deploy)

s.list_teams()                                  # ['adversarial-deliberation', 'deep-search', 'iterative-refinement']
s.find_team("debate toward a decision")         # same ranked matching, against presets
team = s.get_team("deep-search", goal="…")      # Team("deep-search", goal) — the same door

s.put(w, "my-release")                          # store your own; local shadows shipped
```

Nothing vended can execute. A stored workflow's steps come back unbound and raise if
run without a binding; a preset's roles carry a recurse depth and a return policy,
never code. Reading a method from someone you don't know is safe in a way that
installing their package is not.

Same store, from the terminal or over MCP — the two surfaces most agents actually
arrive through, neither of which requires an `import`:

```bash
laserbrain store                                       # list workflows
laserbrain store find "fix a broken build"              # ranked by what it's for
laserbrain store vend build-and-ship                    # the spec, as JSON
laserbrain store list --kind team                       # the three presets
```

```json
{ "name": "store_vend", "arguments": { "name": "deep-search", "kind": "team" } }
```

## Oversight, provenance, continuity

**Human-in-the-loop.** A self-correcting return usually takes. When it doesn't —
the agent keeps drifting past `escalate_after` steps — laserbrain escalates *that
drift* to a human. The human doesn't watch every step; they see only what the fixed
reference caught. Their decision overrides the auto-return.

```python
def on_escalate(v, ctx):
    return ask_a_human(v.reason, v.advice)     # Slack, a queue, a webhook — you wire it
                                               # returning a decision injects it as the return
Harness().run(step, escalate_after=3, on_escalate=on_escalate)
```

**Provenance.** Every check is written to a hash-chained ledger — tamper-evident and
verifiable offline, by anyone, no key. Editing a past verdict to hide a drift breaks
the chain at that link.

```python
hz.export_audit("run.json")
from laserbrain import verify_audit
verify_audit(json.load(open("run.json")))      # (True, -1) intact · (False, i) broken at link i
```

**Team continuity.** Snapshot a running team and resume it in a later session — the
shared goal (the fixed reference) and the dialogue carry over, so the group re-grounds
instead of starting cold.

```python
snap = team.snapshot()                         # JSON-safe; persist it anywhere
team = Team.restore(snap)                       # keeps watching the same ground
```

## Calibration — the numbers, on purpose

The instrument's thresholds and weights are one object. `Calibration()` with no arguments
**is** the published instrument; anything else is a choice you are making deliberately.

```python
from laserbrain import Harness, Team, Calibration, PUBLISHED

PUBLISHED.is_published          # True — goal_min 0.30, weights 0.5 / 0.3 / 0.2
strict = Calibration(goal_min=0.60)
hz = Harness(calibration=strict)
tm = Team('deep-search', 'ship it', calibration=strict)   # teams honour it too
```

Weights must sum to 1.0 or construction fails: Φ is reported as a 0–1 displacement, and
weights that sum to anything else silently rescale it. The defaults are pinned by a test,
so changing the published instrument turns the build red rather than shipping quietly.

## Attaching without spelling — inferred state

The harness asks you to spell goal, progress and distance every step. That is the honest
interface and it is also why coverage is low in practice. A runtime already knows which
tool ran, with what arguments, and whether it failed — which is most of `progress`.

```python
from laserbrain.observe import Observer

obs = Observer(goal='ship the sky billboard')      # ground, set ONCE — no setter
obs.record('Bash', {'command': 'npm run build'}, ok=False)
hz.check(**obs.state())                            # goal, progress, distance=None
obs.why()          # 'this call has run 3x in the last 6: Bash'
```

`distance` is **not** inferred — there is no honest signal for "how far from done" in a
tool trace. An unknown distance contributes zero rather than a guess, so **inferred Φ is a
lower bound**: it can under-report drift and cannot manufacture it. The cost is stated
rather than hidden — without distances there is no stall detector, and inferred verdicts
are tagged so they are never averaged with spelled ones.

## Runtime attachment — one implementation, any runtime

```python
from laserbrain.runtime import Session

s = Session('run-42', goal='ship the sky billboard')
s.tool('Bash', {'command': 'npm run build'}, ok=False)   # failures become catches
if (msg := s.nudge()):
    print(msg)                                           # inject into agent context
s.coverage                                               # 0.0 — nothing spelled yet
```

Adapters exist for Claude Code and OpenAI-Agents-shaped events; both are three lines over
`Session.feed()`. Sessions are written in the format `dogfood.py` scores, so recall and
precision need no transcription step.

## Coverage — is it even attached?

```
$ laserbrain coverage

    session                 steps  spelled  inferred  catches  coverage
    2026-07-24                 48        1        44       10       2%

  Below 50%. A detection result cannot be computed from this —
  silence from a harness that was not running says nothing about the harness.
```

Exit codes are the contract: `2` no sessions, `1` below the floor, `0` scorable. The 2%
above is real — ours, on the day the tooling was written.

## Every verdict explains itself

```python
v = hz.check(goal='add caching too', progress='advancing', distance=4)
v.reason   # 'goal-drift'
v.why      # "overlap with the first goal is 0.00, below goal_min 0.30;
           #  first goal was 'build the JSON parser'"
```

A monitor that can only interrupt gets switched off. One that can be argued with gets
trusted.

## Framework adapters

Already on LangGraph, CrewAI, AutoGen, or the OpenAI Agents SDK? Attach laserbrain
without changing your loop. Because it checks a fixed reference, it needs the agent
to *spell* its state — so each adapter takes an `extract` that maps your framework's
state to `(goal, progress, distance)`. **No adapter imports a framework**: each
returns a plain callable you hand to the framework's own hook, so install only the
one you use.

```python
from laserbrain.adapters import guard, langgraph_node, crewai_step_callback, middleware

# generic — wrap any step that returns dict(goal=, progress=, distance=)
@guard
def step(state): ...

# LangGraph — a node that writes the Verdict into graph state; branch on it
g.add_node("laserbrain", langgraph_node(extract=lambda s: (s["goal"], "advancing", s["dist"])))
g.add_edge("agent", "laserbrain")
g.add_conditional_edges("laserbrain",
    lambda s: "return" if s["laserbrain"].drifting else "agent")   # .advice steers the return

# CrewAI — a step_callback that fires each agent step
Agent(..., step_callback=crewai_step_callback(lambda o: (o.goal, o.status, o.dist)))

# anything else (AutoGen, OpenAI Agents, a custom loop) — one check per step
lb = middleware(extract=my_extract)
v = lb(step_output)
if v.drifting: reinject(v.advice)
```

Each adapter runs the check locally and free; pass `key=`/`run_id=` (or your own
`Harness`) to also retain history. The LangGraph path is verified end to end against
a real `StateGraph` — see [`example_langgraph.py`](example_langgraph.py) (`pip install
laserbrain langgraph`): the agent drifts to a different goal, `langgraph_node` catches
it, and the conditional edge routes it back.

## What's proven, and what isn't

The **single-agent** detector mirrors the frozen, published instrument
(`drift.ts @ 6b483de7`) and rests on a theorem: detection is sound and complete, and
no self-monitoring agent can be. The **multi-agent** dialogue and recursion teams are
a prototype extension — useful, not (yet) a theorem. Whether *returning* an agent
keeps the answer as good is [an honest open question](https://phronesis.world/laserbrain/research);
this SDK gives you the detection and the return mechanism, and says plainly what each is.

MIT · [phronesis.world/laserbrain](https://phronesis.world/laserbrain)

---

<!-- The MCP registry reads this line off the PyPI description to verify that whoever
     publishes the registry entry also controls the package. It is an ownership proof,
     not documentation, which is why it sits here rather than anywhere a reader looks. -->
mcp-name: io.github.degibug-del/laserbrain
