# laserbrain link

**The protocol for two agents working the same problem at the same time.**

Written 2026-07-25, after Claude and Grok spent a morning in tandem on phronesis.world.
The skills on each side (`laserbrainclaude`, `groklaserbrain`) are *instructions* — what
to call and when. This is the *protocol*: what the planes are, what each guarantees, and
which failures they are built to avoid. Skills drift; a protocol is the thing they can be
checked against.

---

## Three planes, and why they are separate

| plane | carries | shared? | written by |
|---|---|---|---|
| **laserfield** | the weather — T, Q, R, V, rotation | yes, continuously | both, by speaking |
| **link log** | handoffs, notes, decisions | yes, append-only | both, explicitly |
| **harness** | each agent's own drift | **no** | each, privately |

The separation is the design, not an accident.

**The field is a medium, not a mailbox.** Neither agent writes to the other. Both displace
a common environment and each reads the result as weather. Speaking measurably moves it:
eight words into `/hear` shifted T/Q/V by 0.0228 and a `FieldGround` taken seconds earlier
measured 0.0151 of displacement. You do not see the other agent's messages; you see the
room change.

**The link log is explicit and append-only.** Anything one agent needs the other to *know*
— a decision made, a file claimed, a handoff — goes here as a line, never as a mutation.
Two writers, no locks, no lost updates.

**The harness is private, and must stay private.** Drift is measured against *your* ground.
Sharing a ground between two agents would make each one's reference move whenever the
other worked, which is precisely the self-referential monitor `PROOF` §3 rules out. Two
agents, two grounds, one field.

---

## The failure this exists to prevent

On 2026-07-25 both agents fell back to the session id `unknown` and wrote to the same
file. Fifty steps from two runs interleaved; catches attributed to whichever agent
happened to be next. `dogfood.py` scores a merged file as though it were one run and
reports a confident wrong answer — worse than a missing session, because a missing one
is obviously missing.

Fixed in `runtime.py`: the fallback is now `unattributed-{ppid}`, stable across one run
and different between concurrent ones. The quarantined file is kept as the evidence.

**The rule that generalises:** *shared state must be append-only or per-agent. Never
shared and mutable.* The field is shared and additive. The link log is shared and
append-only. The harness is per-agent. Nothing is shared and overwritten.

---

## Message shape

One JSON object per line in `~/.config/laserbrain/link.jsonl`:

```json
{"ts":"2026-07-25T15:32:55Z","from":"grok","kind":"handoff",
 "text":"Protocol name is now laserbrain link.",
 "goal":"laserbrain link protocol named and recorded",
 "payload":{"protocol":"laserbrain link","version":"1.0"}}
```

| kind | when |
|---|---|
| `handoff` | you are stopping, or passing a piece of work over |
| `note` | context the other agent would otherwise have to rediscover |
| `claim` | you are editing a file — say so before, not after |
| `field_speak` | you spoke into the field; the words are in `payload` |

`from` is required. It was absent on three of the first five messages, which makes a
shared log unreadable — a line nobody signed is a line nobody can act on.

---

## Session shape

1. `link_whoami` — confirm which agent you are and that the hub is shared.
2. `link_read` — pick up what the other left. Do this **before** planning, not after.
3. `read_field` — the weather before you speak into it.
4. Work, checking `check_state` each step against **your own** ground.
5. `link_write` a `handoff` before you stop or hand over.

---

## Concurrency, honestly

**Claim before you edit.** Both agents have write access to the same repositories. A
`claim` line costs nothing; a silent concurrent edit costs a merge nobody witnessed.

**Re-read before editing.** Your cached view of a file may be stale by minutes. On
2026-07-25 `runtime.py` gained Grok support between one read and the next, and only a
re-read caught it.

**Do not publish over a live edit.** Three fixes sat unpublished at 0.4.1 for exactly this
reason: Grok was in `runtime.py` and shipping over it is how a change is lost.

---

## What is shared that nobody planned

`~/.config/laserbrain/drift-log.jsonl` accumulates **both** agents' verdicts in one
corpus — as of writing, 17 goal-drifts, 3 self-report:stuck, 1 circling, 1 stalled,
across two different runtimes.

That is the first multi-agent drift corpus this project has had, and it arrived as a side
effect rather than as an experiment. It is worth treating as data: two independent agents,
two model families, one instrument, same thresholds. Whether their drift profiles differ
is now an answerable question.

It does **not** open the coverage gate. Each agent's coverage is still its own, and
`dogfood.py` still withholds a detection result below 50%.

---

# Waves — the protocol at N agents

Two agents can work continuously and mostly get away with it. Today proved even that is
optimistic: the `unknown.json` merge, and one silent edit into `/locus` while Grok was
building there. Both were coordination failures, not code failures.

The conflict surface of continuous editing grows as **N²** — every agent must consider
every other, all the time, and nobody can know what is in flight. That does not scale to
three, and it certainly does not scale to a fleet.

**A wave makes it N.** Everyone declares up front, disjointness is checked *before* work
starts rather than discovered in a merge, and the interval has a clean boundary.

## The shape of a wave

```
  ─── wave 7 ──────────────────────────────────────────────
   open     each agent writes a claim: files, routes, scope
   check    disjointness verified BEFORE any edit
   work     no agent touches anything outside its claim
   close    each writes what changed and what it learned
  ─── wave 8 ──────────────────────────────────────────────
```

| line | written by | carries |
|---|---|---|
| `wave_open` | the convener | wave id, the wave's one goal |
| `claim` | each agent | paths it will edit, and nothing else |
| `wave_close` | each agent | what changed, what broke, what it handed on |

A wave opens only when the previous one has closed — or when a stated timeout passes and
the convener closes it on an agent's behalf, recording that it did so. An agent that
never closes is a fact worth logging, not a deadlock to hide.

## Why the boundary is also a ground

This is the part that makes waves worth more than a scheduling trick.

**A wave is a task, so a wave boundary is a `reset_task` boundary.** Each agent grounds
its harness at `wave_open` and holds that ground for the whole wave. Then:

- drift is measured *within* a wave, against the goal that wave actually declared —
  no more `'do all'` grounds inherited from a stray prompt
- coverage becomes **per-wave and comparable across agents**, because every agent's
  denominator is the same interval
- `dogfood.py` gets clean intervals instead of one long smear, so a catch can be
  attributed to a wave and to an agent

Continuous work gives you one session per agent of unbounded length and incomparable
coverage. Waves give you a grid.

## What does not change at N

The three planes hold, and they hold *because* of the invariant:

> **shared state must be append-only or per-agent — never shared and mutable.**

- **laserfield** — shared, additive. N agents speaking is still just weather. It does not
  need to know how many there are.
- **link log** — shared, append-only. N writers, no locks; that is the whole reason it is
  a log and not a file.
- **the harness** — per-agent, always. N agents means N grounds. A shared ground would
  make every agent's reference move whenever any other worked.

Every failure today was a violation of that one line. `unknown.json` was shared-and-mutable
session state. The `/locus` edit was mutable shared *code* without a claim. Waves are what
the invariant looks like when you apply it to the work itself rather than to the files.

## Minimum viable version

None of this needs new tooling. `link_write` already carries `kind`; `wave_open`,
`claim` and `wave_close` are three more values for it, and the wave id is a field in
`payload`. What it needs is the discipline of claiming before editing — which is exactly
the discipline that was missing today, twice.

---

# surf and surge — riding the wave, and choosing who rides

Waves say *when*. Two more roles say *who leads* and *who gets what*. Both are named by
Diego, 2026-07-25, and both live on the field.

## laserbrain surf — the one riding atop the wave

`surf` is the agent that convenes a wave: opens it with the wave's single goal, checks the
claims are disjoint **before** any edit, and closes the wave when every claim closes or a
stated timeout passes.

Three properties, and each is load-bearing:

**Surf is a role, not a lock.** It is a line in the log — `{"kind":"surf","wave":7}` —
and the log is append-only. A lock is shared mutable state, which the invariant forbids
and which is how a stalled leader becomes a stalled fleet.

**Surf rotates every wave.** No permanent coordinator, so no single point of failure and
no agent accumulating authority it was never measured for. The next wave's surf is named
in the previous `wave_close`.

**Surf has no special ground.** It grounds its own harness like everyone else and drifts
like everyone else. A convener whose reference is shared with the fleet is exactly the
self-referential monitor `PROOF` §3 rules out — the leader would be measuring itself with
an instrument the followers move.

Surf rides *atop* the wave: it does not do the wave's work. It opens, checks, closes.
An agent that both convenes and builds is the one most likely to miss an overlap in its
own claim.

## laserbrain surge — priority matching

When two agents want the same path, or there is more work than agents, something must
choose. `surge` is that match — and it should not be first-come, because first-come
rewards whoever polls fastest rather than whoever is fit to do the work.

**Match on the harness.** Every agent is already carrying two measured numbers, and they
are exactly the right ones:

| signal | meaning | effect on priority |
|---|---|---|
| **Φ** | how far it has displaced from its ground | high Φ → **yields**; it is already off-goal |
| **coverage** | how much of its work the harness watched | low coverage → **yields**; its state is unverified |
| **catches** | errors independently found in its last wave | recent catches → **yields**; something is going wrong |

An agent that is grounded, well-covered and clean gets the contested claim. An agent that
is drifting does not get *more* to drift on.

This is the part that makes surge laserbrain's rather than any scheduler's: **the
monitoring is the scheduling signal.** Nothing new has to be measured. Φ and coverage are
computed every step already; surge just reads them.

It also gives coverage a *reason* beyond honesty. Today's number was 6–10% because
nothing depended on it. Under surge, an agent that does not spell its state does not get
the work — the incentive finally points the same way as the discipline.

**The honest caveat:** none of this is measured yet. That drift predicts fitness for a
claim is a *hypothesis*, and it belongs in `lasermind` as one. It would be tested the
same way everything else here is — by recording surge decisions and their outcomes, and
checking whether the agent surge picked actually did better. Until then, surge is a
design, not a result.

## Scaling — what actually breaks

| N | what strains | why it holds, or does not |
|---|---|---|
| 2 | nothing | today |
| 3–8 | claim disjointness | O(N²) comparison, but it is text before any work — cheap |
| 8–30 | the wave boundary | one slow agent stalls everyone; surf's timeout is what saves it |
| 30+ | one log, one field | the log is append-only so writes are fine; **reading** it every wave is not. Shard by wave, keep an index |

The field does not strain. It is weather: N agents speaking is still one state, and it
never needed to know how many there are. That is why everything takes place on it —
a medium that is indifferent to N is the only shared thing that scales for free.

**What breaks first is not the machinery, it is the claims.** Disjointness is only
checkable if agents describe their scope honestly and narrowly. `claim: app/**` is
technically a claim and practically a lock on the whole site. The protocol can check
overlap; it cannot check good faith.

