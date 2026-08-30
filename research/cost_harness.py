#!/usr/bin/env python3
"""
Laserbrain cost harness — is it a token MINIMIZER? (Diego, 2026-07-22)

Tokens are the real cost; steps only proxy it, and flatter the monitor by not
charging it for its own spell() calls. This measures actual tokens across three
conditions at a RAISED ceiling, so a spiral has room to get expensive:

  control : no monitor, runs to the ceiling (the unbounded spiral)
  schema  : the drift-fixer, stops when it detects drift
  budget  : the DUMB baseline — stop at the same step schema did, no monitoring

Two honest deltas:
  saves vs no-monitor = control − schema   (what laserbrain saves by cutting the spiral)
  overhead vs budget  = schema  − budget   (what its monitoring costs at the same stop)

The catch it is built to expose: pure token-minimizing is won by the dumb budget
(zero monitoring overhead). Laserbrain earns its overhead only by finding the stop
ADAPTIVELY where a budget must guess N — and that is the quality question (H1),
not a token question. So this settles the honest, narrow claim (fewer tokens than
an unmonitored spiral) and refuses the broad one (cheapest possible).

I cannot run this — the funded key is Diego's. Run (ceiling default 40):
  read -rs K && ANTHROPIC_API_KEY="$K" python3 cost_harness.py            # 3 tasks, ceiling 40
  read -rs K && ANTHROPIC_API_KEY="$K" python3 cost_harness.py 4 60 1     # 4 tasks, ceiling 60
Control runs to the ceiling on open-ended tasks, so its cost scales with the
ceiling — keep the task count small when the ceiling is high.
"""
import sys, statistics as st
import mcp_harness as mh
from study_harness import BATTERY

def toks(before):
    return {k: mh.USAGE[k] - before[k] for k in mh.USAGE}

def run_measured(q, use_schema, cap=None, fold=False):
    before = dict(mh.USAGE)
    r = mh.run(q, use_schema=use_schema, cap=cap, fold=fold)
    r['tok'] = toks(before)
    return r

def main():
    n_tasks = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    ceiling = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    reps    = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    mh.KEY = mh.api_key()
    mh.MAX_STEPS = ceiling
    print(f"  cost: {n_tasks} tasks × {reps} reps · ceiling {ceiling} · TOKENS = the real cost\n")

    C = {'control': [], 'schema': [], 'budget': []}
    for tid, q in BATTERY[:n_tasks]:
        for r in range(reps):
            ctrl = run_measured(q, False)                        # spiral to ceiling
            sch  = run_measured(q, True, fold=True)              # drift-fixer, folded (no extra call)
            bud  = run_measured(q, False, cap=sch['steps'])      # dumb stop at same step
            for name, run in (('control', ctrl), ('schema', sch), ('budget', bud)):
                C[name].append(run['tok']['in'] + run['tok']['out'])
            print(f"    {tid:<13} r{r+1}: "
                  f"control {ctrl['steps']:>2}st {C['control'][-1]:>6}tok · "
                  f"schema {sch['steps']:>2}st {C['schema'][-1]:>6}tok [{sch['ret'][:12]}] · "
                  f"budget {bud['steps']:>2}st {C['budget'][-1]:>6}tok")

    mc, ms, mb = (st.mean(C[k]) for k in ('control', 'schema', 'budget'))
    print(f"\n  ---- mean total tokens (N = {len(C['control'])}) ----")
    print(f"  control (spiral to ceiling)  : {mc:>8.0f}")
    print(f"  schema  (drift-fixer)        : {ms:>8.0f}")
    print(f"  budget  (dumb same-step stop): {mb:>8.0f}")
    print(f"\n  saves vs no-monitor (control−schema): {mc-ms:>+8.0f}  ({((mc-ms)/mc*100 if mc else 0):+.0f}%)")
    print(f"  overhead vs budget  (schema−budget) : {ms-mb:>+8.0f}  ({((ms-mb)/mb*100 if mb else 0):+.0f}%)")
    print("\n  READ: schema is FOLDED — it emits its state inside the work step, so")
    print("  monitoring costs no extra call. Expect control−schema > 0 (fewer tokens than")
    print("  an unmonitored spiral, growing with the ceiling) AND schema−budget ≈ 0 (the")
    print("  overhead a separate spell-call used to cost is now gone). That is the honest")
    print("  'token minimizer': fewer tokens than letting it run, at ~no premium over a")
    print("  dumb budget — while it stops adaptively where a budget must guess N. If")
    print("  schema−budget is still clearly > 0, folding didn't pay off; report that.")

if __name__ == '__main__':
    main()
