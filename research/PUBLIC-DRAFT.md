# DRAFT — public write-up for review (NOT deployed)

*For Diego. This is the copy I'd propose for the site — either a new paper
(`/papers/returns-sooner`) or an expansion of the "what's proven" section on
`/laserbrain`. Nothing is live. Edit freely; on your OK I'll port it and deploy.*

---

## Returns sooner. We could not show it returns as good.

laserbrain catches an agent's drift and tells it to return to its goal. That the
**detection** works is a theorem: a fixed outside reference is necessary and
sufficient to tell when an agent has left the goal it started with, and an agent
watching only its own recent thinking provably cannot. That part is settled, and we
sell it.

The open question was never detection. It was **whether returning helps** — whether
an agent that stops sooner still arrives at as good an answer, and whether it costs
fewer tokens once you count the harness's own overhead. We call it H1. We tried to
answer it three times. It is not established in any of them, and where the evidence
is legible it leans the other way. Here is the whole of it, because a claim is only
worth the boundary printed next to it.

### Three tests

**The pilot (N=12).** A blind, stronger judge, every pair scored in both orders. By
the preregistered rule it read "supported" — but the judge disagreed with itself on
42% of pairs. Judging open-ended answers with no right answer is close to a coin
flip. Among the pairs where the harness actually acted, three were ties (same
quality, less cost) and two were clean losses (the early return produced a worse
answer). Consistent with the hope, dominated by noise, not a result.

**Coding tasks with hidden tests (N=15).** Here there *is* a right answer, so no
judge is needed. The harness did not help — it matched or trailed the control at
several times the tokens, and every ceiling failure was a run where it intervened.
That is exactly what the theory predicts: a task with its own built-in criterion
does not need an outside reference, and the harness's nudge derails a run that was
fine. So we say plainly: **laserbrain is not for well-specified, test-backed work.**

**The powered re-run (N=16, its own domain).** We ran it only on open-ended tasks —
the harness's actual claim — with a three-judge panel and a rule fixed before any
data: if the judges cannot agree (Fleiss κ below 0.4), the result is *inconclusive*,
full stop, no verdict squeezed from a noisy measure. The panel's agreement came in
at **κ = 0.10.** So the honest output is **inconclusive** — and it is the pilot's
problem confirmed at scale: answers with no ground truth cannot be reliably judged,
even by three models. What *was* legible pointed the same way as before: the harness
acted on only 2 of 16 runs, and both of those, where the judges could agree, went to
the control.

### The bind, stated plainly

The harness would help, if it helps, exactly where quality has no ground truth to
measure it against — that is what "open-ended" means. And where quality *can* be
measured, it does not help. So the benefit sits in the one place a benefit is hardest
to prove, and that is not a flaw in our experiment; it is the shape of the problem.

### What this means for what we sell

We sell what we can stand behind: **detection** (a theorem), and the **observability**
around it — retained drift history, alerts, a fleet view. You pay to *see* your agents
drift, not for a promise that stopping them makes them smarter. We do not claim
laserbrain makes your agent better, or that it is cheaper on tokens. We tried to show
the first three times and could not, and we would rather tell you that than sell you a
result we do not have.

### Why you can trust the negative

Every one of these tests was written down before it ran — the rubric, the rule, the
kill condition, the metric — and frozen. The re-run's rule was *built to be allowed to
lose*, and on H1 it did not win. The same discipline that would have let us claim a
victory is the reason the null is honest. If a better way to measure quality on
open-ended work appears, we will run it and report whatever it says.

*Full protocol, data, and the preregistrations: the laserbrain protocol
(detection proof, the three studies, and the claim ledger).*
