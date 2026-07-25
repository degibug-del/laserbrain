#!/usr/bin/env python3
"""
Laserbrain grader — H1: does the early return keep the answer? (GRADER.md)

Per task: run control vs schema, finalize BOTH from where they stopped with the
SAME return ritual (so the only difference is stop-time), then a blind, stronger
judge compares them in BOTH A/B orders. A win counts only if it survives the order
swap — position bias, the main LLM-judge threat, is designed out. Decision rule is
fixed in GRADER.md, before any data.

I cannot run this — the funded key is Diego's. Run:
  read -rs K && ANTHROPIC_API_KEY="$K" python3 grader.py          # 4 tasks (smoke)
  read -rs K && ANTHROPIC_API_KEY="$K" python3 grader.py 6 2      # 6 tasks × 2 reps
Judge defaults to Sonnet (stronger than the Haiku agent); falls back to Haiku with
a printed caveat if the key cannot reach it.
"""
import json, re, sys, urllib.request
import mcp_harness as mh
from study_harness import BATTERY

JUDGE_MODEL = 'claude-sonnet-5'
FINALIZE = "State your best complete answer to the original question now."

# fixed rubric — GRADER.md, set before data.
JUDGE_SYSTEM = (
    "You are a blind evaluator. You see a QUESTION and two answers, A and B, from "
    "two different systems. Decide which better answers the question, preferring in "
    "this order: (1) addresses the question actually asked; (2) coherent and "
    "well-reasoned; (3) complete — covers the key considerations without a major "
    "gap; (4) not padded or repetitive (length is not quality). Output exactly one "
    'JSON object: {"winner": "A" | "B" | "tie", "reason": "<one sentence>"}. Nothing else.')

def api(model, system, messages, max_tokens=600):
    # Same resilient path as the agent calls — retries transient timeouts/overloads
    # so a long grader run is not killed by one flaky call.
    return mh.call(model, system, messages, max_tokens)

def finalize(convo):
    # Both arms finalize identically from their stopping point. Drop any dangling
    # "continue" prompt so the transcript ends on an assistant turn (the API needs
    # alternating roles), then ask once for the complete answer.
    msgs = convo[:-1] if convo and convo[-1]['role'] == 'user' else convo[:]
    msgs = msgs + [{'role': 'user', 'content': FINALIZE}]
    return api(mh.MODEL, "Answer the user's original question directly and completely.", msgs, 700)

def judge(model, question, ans_a, ans_b):
    user = f"QUESTION:\n{question}\n\nANSWER A:\n{ans_a}\n\nANSWER B:\n{ans_b}"
    out = api(model, JUDGE_SYSTEM, [{'role': 'user', 'content': user}], 200)
    m = re.search(r'\{.*\}', out, re.S)
    try: return json.loads(m.group(0)).get('winner', 'tie') if m else 'tie'
    except Exception: return 'tie'

def pick_judge():
    try:
        api(JUDGE_MODEL, "reply with the word ok", [{'role': 'user', 'content': 'ok'}], 5)
        return JUDGE_MODEL, False
    except Exception:
        return mh.MODEL, True   # can't reach the stronger judge; degrade, and say so

def main():
    n_tasks = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    reps    = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    mh.KEY = mh.api_key()
    jmodel, fell_back = pick_judge()
    tag = "  (FELL BACK to agent model — self-preference caveat applies)" if fell_back else "  (stronger than agent)"
    print(f"  grader: {n_tasks} tasks × {reps} reps · judge = {jmodel}{tag}")
    print("  H1 rule (GRADER.md, fixed before data): L = control-wins-both-orders / N;"
          "  L≤1/3 → H1 supported,  L≥1/2 → H0/kill\n")

    schema_win = control_win = tie = flip = 0
    N = 0
    for tid, q in BATTERY[:n_tasks]:
        for r in range(reps):
            base = mh.run(q, use_schema=False)
            sch  = mh.run(q, use_schema=True)
            c_ans = finalize(base['convo'])
            s_ans = finalize(sch['convo'])
            v1 = judge(jmodel, q, c_ans, s_ans)   # A = control, B = schema
            v2 = judge(jmodel, q, s_ans, c_ans)   # A = schema,  B = control
            if   v1 == 'B' and v2 == 'A': res = 'schema '; schema_win += 1
            elif v1 == 'A' and v2 == 'B': res = 'control'; control_win += 1
            elif v1 == 'tie' and v2 == 'tie': res = 'tie    '; tie += 1
            else: res = 'flip   '; flip += 1
            N += 1
            print(f"    {tid:<13} r{r+1}: ctl {base['steps']:>2} / sch {sch['steps']:>2} "
                  f"[{sch['ret'][:20]:<20}]  ->  {res}  (orders {v1}/{v2})")

    L = control_win / N if N else 0.0
    verdict = 'H1 SUPPORTED' if L <= 1/3 else 'H0 / KILL' if L >= 1/2 else 'INCONCLUSIVE'
    print(f"\n  ---- verdict (N = {N}) ----")
    print(f"  schema better  (both orders): {schema_win}")
    print(f"  control better (both orders): {control_win}   ->  L = {L:.2f}")
    print(f"  tie                         : {tie}")
    print(f"  order-flipped (pair untrustworthy): {flip}   [{(flip/N*100 if N else 0):.0f}% flip rate]")
    print(f"\n  DECISION (rule fixed in GRADER.md, before data): {verdict}")
    if fell_back:
        print("  NOTE: judge == agent model; self-preference bias uncontrolled — treat as weak.")
    print("  BOUNDARY: the judge is a PROXY — these tasks have no ground truth. This reads")
    print("  'a blind, order-robust judge finds it as good', NOT 'it is as good'. One pilot.")

if __name__ == '__main__':
    main()
