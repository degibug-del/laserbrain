# The blind probe — pre-registration

> ## ENDED 2026-08-21, SHORT OF THE STOPPING RULE, AND READ ANYWAY
>
> **The probe is disabled.** `LASERBRAIN_BLIND_PROBE=1` was removed from the four hook
> commands in `~/.claude/settings.json`; `blind_arm` now returns `sighted` for every unit.
> `blind-arms.jsonl` is kept, not deleted.
>
> **It stopped at 8 blind / 6 sighted, against a pre-registered 20/20** — and two of the
> six sighted units are junk (`unknown#0`, `t#0`), so the real count is 8 / 4. Diego chose
> to lower the target to what it reached and read the outcome. That is the one move this
> document argues against most directly — *"a threshold moved once the data is visible is
> fitted to it"* — and it is recorded here rather than quietly applied. **What follows is a
> post-hoc look, not the result this file asked for.** No future blind probe can be run
> clean on this corpus by anyone who has read it.
>
> ### The specified outcome measure could not be computed at all
>
> Ending it early is not what stopped this from being an answer. The primary measure —
> *drift rate per unit, from the session records, joined to an arm through
> `blind-arms.jsonl`* — has no join. Three routes, all closed:
>
> | route | why it fails |
> |---|---|
> | unit → check | units are keyed `session#segment`; checks carry `run`, a different id space. **0 of 14** units match any run. |
> | via segments | the segment index is `len(segments)`, and the arm file records `#0`–`#13` — but the store holds **2 segments in total**, both from July, and **none** for this session. |
> | via timestamps | only **4** checks in the whole store carry a `ts`, all from July, before the probe window opened. (The store is live and grows; the 4 is the stable figure, the denominator is not.) |
>
> So the assignment side was recorded faithfully and the outcome side was never recorded in
> a form that could be joined to it. This was true for the whole restarted run. The
> 2026-08-16 restart fixed a moving frozen ground; it did not fix this, because nobody had
> looked yet — which is precisely what a no-interim-looks rule costs when the instrument
> itself is unverified. **A pre-registration protects against reading the data too early.
> It does not protect against never being able to read it.** That is the durable lesson
> here, and it is worth more than the number below.
>
> ### What was computed instead, and why it is WITHDRAWN
>
> The drift log carries both `ts` and `drifting`, so each reading was joined to whichever
> arm `current-arm.json` held at that moment. A first version of this section reported
> blind 0.1888 against sighted 0.2356 and called it the harness-does-not-help outcome.
> **Those numbers are withdrawn.** A review on 2026-08-21 found two defects in the join and,
> more importantly, that the estimate is not stable under either correction.
>
> The join compared naive LOCAL assignment stamps (`lb_gate.py` writes
> `datetime.now().isoformat()`, no tzinfo) against UTC reading stamps, applying every arm
> window seven hours early. And two rows in `blind-arms.jsonl` are not sessions at all —
> `unknown#0` and `t#0` — whose windows absorbed most of the sample.
>
> | variant | blind | sighted | sighted − blind |
> |---|---|---|---|
> | as first reported (naive, junk kept) | 0.1888 | 0.2924 | **+0.1035** |
> | timezone corrected, junk kept | 0.2011 | 0.3087 | **+0.1076** |
> | timezone corrected, junk dropped, window closed at the probe's end | 0.2308 | 0.0172 (n=58) | **−0.2136** |
>
> Three defensible variants, two signs. Dropping two junk rows collapses the sighted arm
> from 1350 readings to 58 against blind's 1681 — so the comparison rests on which stretches
> of one session happened to fall inside two mislabelled windows. **This is not an
> underpowered result, it is a sign-unstable one**, and an estimate that changes direction on
> a judgement call about two rows is not evidence in either direction.
>
> So the pre-registered question is unanswered, and nothing here should be quoted as
> bearing on it — in particular not the first table's direction, which was reported before
> the instability was known and repeated in this file for several hours.
>
> ### If this is ever run again
>
> Record the arm ON the check, at write time, in the session record — one field, decided
> where the reading is produced. Every failure above is the same failure: the arm and the
> outcome were written by different processes into different files with no shared key.
> Verify the join produces rows **before** collecting, on a handful of units. A probe whose
> analysis has never once been executed end to end is not collecting data; it is collecting
> the belief that it is.

> ## RESTARTED FROM ZERO, 2026-08-16
>
> **The first collection is void and was not looked at.** 21 assignments had accumulated,
> 10 blind and 10 sighted, about half the pre-registered 20-per-arm. They are archived at
> `~/.claude/laserbrain/blind-arms.faulty-window-2026-08-08_2026-08-16.jsonl` rather than
> deleted, because they are now evidence about the fault rather than about the question.
>
> **Why.** For the whole of that window the MCP server had a defect that moved the frozen
> ground: subagents share one server process and one `_state`, every agent is told to call
> `reset_task` when it starts new work, and `reset_task` deleted whatever ground was live —
> usually not the caller's. A parent's next check, passing a byte-identical goal string,
> then read `goal-drift` at 0.02 and escalated to `wrong-problem`. Fixed the same day in
> lasermind's `mcp-server.mjs` (shared lane suspends instead of discarding) and in
> laserbrain 0.51.0 for the Python package.
>
> That is not a nuisance for this probe, it is fatal to it. The probe asks *does seeing the
> verdict change the work* — and for those days some verdicts were false, produced by a
> reference that had moved. The sighted arm was therefore reading a partly fictional
> instrument, which is the one thing the comparison cannot survive. Whether it biased the
> arms symmetrically is unknown and unmeasured, and "probably symmetric" is not a standard
> this file is written to.
>
> **No interim look was taken before discarding**, and none should be taken of the archive
> while the restarted probe runs: reading it would reintroduce exactly the knowledge the
> pre-registration exists to keep out.
>
> Nothing below changed. Same question, same unit, same assignment rule, same stopping rule,
> same failure conditions. The count starts again at zero on the fixed server.

**Written 2026-08-10, before any result was read.** Every number below was chosen while the
answer was unknown, which is the only condition under which choosing them is free. Values
marked *proposed* are Diego's to change — but they must be changed **now**, not after a
first look. A threshold moved once the data is visible is fitted to it.

Implemented in `lb_gate.py`: `blind_arm`, `publish_blind_arm`.

---

## The question

Every session in the corpus to date ran with the harness visible. There has never been an
arm in which the instrument measured without also intervening, so *"does it help?"* has
been asserted and never answered. Diego's own read on 2026-08-07 was "yes, noticeably
better" — which is exactly the kind of belief that needs a control rather than a
testimonial.

**Does seeing the verdict change the work?**

## Design

| | |
|---|---|
| **unit** | one segment — the work between two `reset_task` calls, i.e. one task under one frozen ground |
| **assignment** | `sha256('blind:' + unit) % 2` — deterministic, 50/50, not re-rollable |
| **gate** | `LASERBRAIN_BLIND_PROBE=1`; otherwise every unit is sighted and nothing is running |
| **treatment** | the agent is told its reading |
| **control** | the reading is withheld: `{blind: true, …}`, work continues |
| **excluded** | anything with `LASERBRAIN_ARM=open` — that is a test harness, not a session |

The two arms differ **only in whether the agent is told.** The checks happen either way, Φ
is computed either way, and both are recorded either way. That is what makes the arms
comparable, and it is why the harness is not simply switched off for the control: a control
that recorded less Φ would be a different measurement, not a comparison.

## The record

Each assignment appends one line to `~/.claude/laserbrain/blind-arms.jsonl`:
`{session, unit, segment, blind, at}`.

**This did not exist until 2026-08-10.** The probe ran from 08-08 writing only
`current-arm.json`, which is overwritten per unit — so the first two days produced no
separable record and are excluded. The sample starts at the first line of that file.

## The outcome measure

**Primary: drift rate per unit** — the fraction of that unit's checks with
`drifting: true`, read from the session records in `~/.claude/laserbrain/*.json`, joined to
an arm through `blind-arms.jsonl`.

This is the right measure precisely because Φ is computed identically in both arms. The
control agent is not told it is drifting; the drift is still recorded. So the comparison
asks the question directly: **when an agent is told, does it drift less?**

**Secondary, reported but not decisive: catches per unit** — errors something independent
found (failed commands, logged by the hook). A treatment that reduces measured drift while
leaving real errors untouched would be moving the number rather than the work, and that is
worth being able to see.

## Sample and stopping rule

- **20 units per arm** (*proposed* — matches the sibling `probe_arm` pre-registration).
- **Stop when both arms reach 20.** Not when one does; not at a round date; not when the
  gap looks convincing.
- **No interim looks.** The first read of the outcome happens at n=20/20 and not before.
  This is the clause the whole document exists for: an experiment that can be stopped when
  the numbers please is measuring patience.
- If the probe is disabled or the design changes before n=20/20, the run is void and the
  file is restarted. A partial run is not a small result; it is no result.

## What would mean it does not help

Stated concretely, in advance, so it is recognisable if it happens:

> **The harness does not help if the sighted arm's mean drift rate is not lower than the
> blind arm's** — a difference of zero, or in the wrong direction, at n=20/20.

Any of these is that outcome and none of them is to be explained away:

- sighted ≥ blind on mean drift rate;
- a difference smaller than **0.05** (*proposed*) in drift rate — present but too small to
  justify a per-step instrument;
- a drift-rate difference with no matching movement in catches, which would say the reading
  changes what gets *recorded* rather than what gets *done*.

## What this cannot settle

**n=20 per arm is underpowered for a small effect.** It can detect a large difference and
will not resolve a subtle one, and no amount of running past 20 fixes that after the fact —
extending the sample once the result is visible is the same fault as moving a threshold.

The unit is one person's tasks on one machine. It measures whether *this* agent, doing
*this* work, drifts less when told. It is not a claim about agents in general, and the
write-up should not make one.

Both arms are the same agent, aware the probe exists. An agent that knows it is sometimes
blinded is not a naive control, and nothing here removes that.

---

*If any value above is wrong, change it before the first read. After that, it is the record
of what was decided when the answer was still unknown — which is all a pre-registration
ever is.*
