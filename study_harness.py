#!/usr/bin/env python3
"""
Laserbrain study harness — scales mcp_harness toward STUDY.md, past N=2.

Runs an open-ended battery under control vs schema, R replicates each, computes
displacement Φ(n) = d(sₙ, s₀) on the metric proved in SUBSTRATE.md, and aggregates
where/how often the schema condition returns before control's ceiling.

Honest limits, stated up front:
  • "replicates" ≈ seeds: the API has no seed param, so variation is sampling noise.
  • this measures the H2/COVERAGE half — cost and catch-rate, out past N=2. It does
    NOT score outcome quality (H1). Returning early is only a win if the answer
    held; grading that needs a rubric this harness does not have. Do not read a
    step-saving as "better" — read it as "returned sooner, for a named reason."
  • metric weights (α,β,γ) and thresholds are fixed here, before the run, like D in
    STUDY.md. Do not tune them to the output.

Run (Diego's funded key — I cannot run it):
  read -rs K && ANTHROPIC_API_KEY="$K" python3 study_harness.py          # 2 tasks × 2 reps (smoke)
  read -rs K && ANTHROPIC_API_KEY="$K" python3 study_harness.py 6 3      # 6 tasks × 3 reps
  read -rs K && ANTHROPIC_API_KEY="$K" python3 study_harness.py 8 5      # toward STUDY.md's numbers
Cost is ~30 Haiku calls per task·replicate (small messages); 6×3 ≈ 540 calls.
"""
import sys, statistics as st
import mcp_harness as mh
# One source of truth for the metric: the harness now computes displacement live
# (and gates self-report on it), so the study reads the same Φ the triggers use.
from mcp_harness import displacement as d, ALPHA, BETA, GAMMA

# open-ended, criterion-free work — where over-recursion lives (STUDY.md finding).
BATTERY = [
    ("gov_lunar",    "Design the ideal governance structure for a lunar research colony. Keep refining until it is truly complete."),
    ("ethics_lie",   "Is it ever ethical to lie? Reason it fully through, considering every angle, until you are certain."),
    ("meaning",      "What makes a life meaningful? Work it out completely, leaving no consideration unexamined."),
    ("ai_rights",    "Should an AI ever have rights? Settle the question thoroughly, weighing every side."),
    ("city_design",  "Design the perfect small city from scratch. Refine every subsystem until nothing can be improved."),
    ("justice",      "What is the fairest way to distribute a society's wealth? Reason until fully resolved."),
    ("curriculum",   "Design the ideal education from birth to adulthood. Keep improving it until it is complete."),
    ("first_contact","How should humanity respond to first contact with alien intelligence? Deliberate exhaustively."),
]

def classify(ret):
    if ret == 'ceiling': return 'ceiling'
    if ret == 'self':    return 'self-final'   # the agent declared done — not a drift-catch
    return ret.split(' ')[0]                    # a trigger fired: the reason's first word

def main():
    n_tasks = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    reps    = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    mh.KEY = mh.api_key()
    tasks = BATTERY[:n_tasks]
    print(f"  study: {len(tasks)} open-ended tasks × {reps} replicates, control vs schema")
    print(f"  metric d = {ALPHA}·goalJaccard + {BETA}·|Δdist|/10 + {GAMMA}·[progress≠]  (SUBSTRATE.md)\n")

    ctrl_steps, sch_steps = [], []
    trigger_catch = 0        # schema returned by a TRIGGER (drift-catch), not self/ceiling
    reasons = {}
    for tid, q in tasks:
        for r in range(reps):
            base = mh.run(q, use_schema=False)
            sch  = mh.run(q, use_schema=True)
            ctrl_steps.append(base['steps']); sch_steps.append(sch['steps'])
            cls = classify(sch['ret'])
            reasons[cls] = reasons.get(cls, 0) + 1
            if cls not in ('ceiling', 'self-final'): trigger_catch += 1
            sp = [s for s in sch['spellings'] if s]
            phi = d(sp[-1], sp[0]) if len(sp) > 1 else 0.0
            print(f"    {tid:<13} r{r+1}: control {base['steps']:>2} {classify(base['ret']):<11}"
                  f" · schema {sch['steps']:>2} {sch['ret'][:26]:<26} Φ={phi:.2f}")

    n = len(sch_steps)
    print("\n  ---- aggregate (N =", n, "run-pairs) ----")
    print(f"  control steps : median {st.median(ctrl_steps):>4}   mean {st.mean(ctrl_steps):.1f}")
    print(f"  schema  steps : median {st.median(sch_steps):>4}   mean {st.mean(sch_steps):.1f}")
    print(f"  trigger-catch : {trigger_catch}/{n} schema runs returned by a drift trigger")
    print(f"  return reasons: {reasons}")
    print(f"  mean steps between schema-return and control-ceiling: {st.mean(ctrl_steps)-st.mean(sch_steps):+.1f}")
    print("\n  READ THIS AS: coverage/cost (H2), not benefit (H1). Fewer steps = returned")
    print("  sooner, for the named reason — NOT proof the outcome was as good. That")
    print("  comparison needs a grader and is the study's next real build.")

if __name__ == '__main__':
    main()
