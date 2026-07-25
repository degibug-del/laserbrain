# laserbrain — launch copy

Working copy for the launch. The angle is honesty: **detection is a theorem; the
benefit we tried three times to show and couldn't, and we published the nulls.**
That is the differentiator in a crowded space — this crowd rewards "I proved X and
disproved my own Y." Keep the Riemann/consciousness paper OUT of the technical
launch (it reads as crank beside a product); share that separately, later, to a
different room.

Links: <https://phronesis.world/laserbrain> · research <https://phronesis.world/laserbrain/research>
· demo <https://phronesis.world/laserbrain/demo> · `pip install laserbrain`

---

## Positioning (the one line)

> **laserbrain — the smart recursion harness for AI agents.** Your agent drifts
> off its goal and keeps going, every step looking fine. laserbrain catches the
> drift and returns it to ground — so it stops spiraling and finishes.

Alternates (all lead with what it does, all carry the phrase):
- **Your AI agent wanders off its goal and doesn't notice. laserbrain is the
  smart recursion harness that catches the drift and pulls it back.**
- **laserbrain is a smart recursion harness for AI agents: it watches your
  agent against a fixed goal and returns it the moment it drifts — no more 40-step
  loops that end nowhere.**

(The proof and the published nulls are the *credibility payoff* lower in the post —
never the hook.)

---

## Show HN

**Title options** (pick one — each says what it does):
- `Show HN: Laserbrain – a smart recursion harness that catches AI agents drifting off-goal`
- `Show HN: Laserbrain – a smart recursion harness that pulls a drifting AI agent back to its goal`
- `Show HN: Laserbrain – a smart recursion harness so your AI agent stops looping and finishes`

**Body:**

Laserbrain is an external check for when an AI agent has drifted from its goal.
Each step, the agent spells its state — goal, progress, distance-to-done — and
laserbrain checks it against the ground state the run started from.

The reason it's external is a theorem. A monitor that compares an agent only to
its recent history provably cannot be both sound and complete at detecting drift:
after a few steps the starting point has scrolled out of the window, and you can
construct two runs — one that drifted far and one that never moved — with
identical recent histories. So no "agent reflects on itself" loop can catch this.
A single fixed, retained reference is necessary *and* sufficient. The full proof
and the metric are on the site.

The honest part, which is really why I'm posting: I could not show it makes agents
*better*. I ran three preregistered tests — a blind stronger-judge pilot,
ground-truthed coding tasks with hidden unit tests, and a powered three-judge panel
— and all three came back null or inconclusive. The core problem is that the
benefit would live exactly where open-ended answers have no ground truth to score,
so the judges can't reliably tell the returned answer from the control (the panel
agreed at κ=0.10). Every test was frozen before it ran and allowed to lose, and on
this it did. Detection is a theorem I'll defend; "returning to ground helps" is an
open question, and the nulls are published next to the proof.

Using it:
- `pip install laserbrain` — the check runs locally and free (a pure function, no
  key, no latency). `Harness().check(goal=..., progress=..., distance=...)`.
- Adapters for LangGraph, CrewAI, AutoGen, and the OpenAI Agents SDK — you map your
  state to (goal, progress, distance) and it watches from inside your loop.
- Or point any MCP-capable agent at one URL.
- Paid tiers add retained drift history, spiral alerts, a fleet dashboard, and
  human-in-the-loop escalation — you pay to *see* your agents drift over time, not
  for the check.

There's also a prototype extension to multi-agent teams (catching the echo/
agreement spiral a self-watching group can't see) — labeled a prototype, because
that one isn't a theorem yet.

Proof + every study (nulls included): https://phronesis.world/laserbrain/research
Watch it work: https://phronesis.world/laserbrain/demo

Happy to answer anything — especially where you think the benefit *could* be
measured on open-ended work, because that's the part I haven't cracked.

---

## X / Twitter thread

**1/** 🧠🎯 Keep your AI agents locked on their goal — and finishing strong.

laserbrain is the smart recursion harness that catches drift the instant it
starts and guides your agent right back to ground. Fewer loops, more done. ⚡✅

`pip install laserbrain` 🚀

**2/** Here's the sneaky part 👀 — a drifting agent looks *productive* the whole
way. Every step makes sense next to the last one, while it quietly wanders miles
from the goal. Watching only its own recent history, it can't see it. 🌀

**3/** So laserbrain gives it something solid to check against: the ground it
started from. 🧭 And that's not a nice-to-have — it's provably *the* fix. A fixed
external reference is necessary AND sufficient to catch drift; nothing that only
watches itself can. 📐

**4/** Wiring it in is tiny 🔌 — each step your agent spells its state, laserbrain
checks it against ground, and flags the drift the instant it appears. Local + free
(it's a pure function ⚡), with drop-in adapters for LangGraph, CrewAI, AutoGen &
OpenAI Agents. 🧩

**5/** Straight with you 🤝: catching drift is proven. Whether *returning* makes the
final answer better is the open question — so I ran three preregistered tests and
published every result, nulls included, right beside the proof. 📊 What's true beats
what sells.

**6/** And it's all live today 🚀 — the SDK, a hosted dashboard 📈, human-in-the-loop
escalation 🙋, and a tamper-evident audit log 🔒. Detection's the theorem; everything
else is labeled for exactly what it is.

**7/** Take it for a spin 👇
🧠 `pip install laserbrain`
🎬 watch it work → https://phronesis.world/laserbrain/demo
📜 the proof + every study → https://phronesis.world/laserbrain/research
Free at small scale. Build agents that finish. ✅

---

## For the LangGraph / CrewAI / AutoGen communities (a shorter blurb)

Built on LangGraph or CrewAI? laserbrain drops into your loop: you map your agent's
state to (goal, progress, distance), and it watches a fixed reference from the
outside — catching drift a self-reflecting agent provably can't. There's a theorem
behind it, and I published the experiments where I couldn't show it improves answer
quality, so you know exactly what you're getting.

```python
from laserbrain.adapters import langgraph_node
g.add_node("laserbrain", langgraph_node(extract=lambda s: (s["goal"], "advancing", s["dist"])))
```

Free locally: https://phronesis.world/laserbrain

---

## The hard questions — answers ready

Drafted before they're asked. Concede the true part first; that's what earns the
rest. Never defend the benefit claim — we don't have it.

**"Why not just repeat the goal in the system prompt every turn?"** ← the most common
> That helps, and you should do it — but it's a different thing. Restating the goal
> reminds the agent; it doesn't *measure* whether the agent has left it. The model
> still judges its own progress, from inside the context that already drifted. The
> check is external and mechanical: it holds the first-spelled goal and computes the
> displacement, so it can fire when the agent is confidently reporting "advancing."
> The reminder is an input; the check is a measurement.

**"The theorem is trivial — of course you need to remember where you started."**
> Largely fair, and I'd rather state it plainly than dress it up. The content isn't
> "memory helps," it's the impossibility half: for *any* window width and *any*
> decision rule, there are two runs — one drifted, one that never left — with
> identical recent histories, so no self-referential monitor is both sound and
> complete. That rules out the whole class of "have the agent reflect on its recent
> steps," which is what most agent frameworks actually ship. Obvious in hindsight is
> the usual shape of a correct result.

**"Jaccard over stemmed words is a crude metric."**
> Yes. The grammar is the weakest part and I say so on the research page — the
> theorem blesses *a* fixed reference, never a particular vocabulary. Word overlap
> is what I could freeze, publish, and have you reproduce. A better displacement
> metric (embeddings, structured state) slots in without touching the result. If you
> have one, that's the most useful contribution to make.

**"You admit it doesn't improve outcomes. So why would I use it?"**
> Because detection and improvement are different products. What it gives you is
> *visibility*: you learn your agent left its goal at step 7, instead of reading a
> confident final answer to the wrong question. Whether the automatic return then
> makes the answer better is what I couldn't show — so the honest recommendation is
> to use it to see drift, and to decide for yourself whether to act on the return.
> If you measure it on your own workload, I'd genuinely like the data.

**"Isn't this just an eval / observability tool?"**
> It's observability with a proof about what's detectable, and the check runs
> in-loop rather than after the fact. It is not an eval: it never scores answer
> quality, and I'd distrust it if it claimed to.

**"Does this need my API key / send my data anywhere?"**
> No. The check is a pure local function — no key, no network, no latency. A key is
> only for the hosted history/alerts, and even then it sends the spelled state
> (goal, progress, distance), not your prompts or completions.

## How to run it (strategy)

- **Order:** post Show HN first (weekday morning US time), then the X thread linking
  the HN discussion once it has traction. Cross-post the community blurb to the
  LangGraph/CrewAI Discords/subreddits as a genuine "I built this, feedback welcome."
- **Engage, don't broadcast.** On HN the value is the comments — reply to every
  technical question, concede what you don't know, and steer people to the
  measurement problem (that's the open, interesting part). The nulls will do more
  for credibility than any feature list.
- **Don't** lead with pricing, funding, or the Riemann paper. Lead with the proof
  and the nulls. The rest follows if the first landing is credible.
- **Watch for real drift data.** Anyone who actually wires it up is a potential
  design partner and the first real evidence past the nulls — follow up personally.
