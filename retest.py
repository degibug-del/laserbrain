#!/usr/bin/env python3
"""
retest.py — the FINAL H1 experiment (lasermind/RETEST.md).

The one open empirical question: on CRITERION-ABSENT tasks (the harness's own
domain), does returning to ground on detected drift keep the answer as good as
running longer — AND cost fewer NET tokens? Detection is a theorem (PROOF.md);
this is the benefit half, built to be allowed to lose.

It fixes the two things that left the GRADER pilot unable to settle anything:
  1. DOMAIN — runs only the open-ended BATTERY (no ground truth), never coding
     tasks (codebench already showed the harness is net-NEGATIVE where a criterion
     exists, and theory says it should be).
  2. THE 42% JUDGE-FLIP — replaces the single judge with a PANEL of K judges, each
     double-order; a judge's verdict counts only if order-consistent, the pair's
     verdict is the panel majority, and Fleiss' kappa is reported and GATES the
     decision. A human subsample is emitted blinded for the gold-standard check.

FROZEN INSTRUMENT. The detector below mirrors, value-for-value, the frozen
drift.ts (worker 6b483de7; RETEST.md § FREEZE). Do NOT change it — a changed
instrument restarts the experiment. If drift.ts and this ever disagree, the run
is invalid; reconcile to RETEST § FREEZE first.

I cannot run this — the funded key is Diego's. Run:
  read -rs K && ANTHROPIC_API_KEY="$K" python3 retest.py            # smoke: 3 tasks
  read -rs K && ANTHROPIC_API_KEY="$K" TASKS=8 REPS=2 python3 retest.py
Knobs: TASKS (n from BATTERY), REPS, AGENT (model), JUDGES (comma list),
CAP (step ceiling), OUT (results dir).
"""
import json, math, os, re, sys, time
import mcp_harness as mh
from study_harness import BATTERY

# ---------------------------------------------------------------------------
# THE FROZEN DETECTOR — mirror of drift.ts @ 6b483de7 (RETEST.md § FREEZE).
# Every constant here is load-bearing and frozen. Do not tune.
# ---------------------------------------------------------------------------
STOP = {'the','a','an','to','of','and','or','for','in','on','at','is','it','this',
        'that','with','my','your','our','i','we','be','as','by','from','into','out',
        'up','so','then'}
_STEM = re.compile(r"(ings?|edly|ed|ers?|es|s|tion|ment)$")

def norm(s):
    out = set()
    for w in re.findall(r"[a-z0-9']+", str(s).lower()):
        if w in STOP:
            continue
        r = _STEM.sub('', w) if len(w) > 4 else w
        if r:
            out.add(r)
    return out

def jac(a, b):
    if not a and not b:
        return 0.0
    inter = len(a & b)
    return 1 - inter / len(a | b)

def as_dist(obj):
    try:
        return max(0, min(10, int(float(obj.get('distance', 5)))))
    except Exception:
        return 5

PROGRESS = {'advancing', 'stuck', 'circling'}
DRIFT_REASONS = ('ungrammatical', 'goal-drift', 'stalled')

def is_drift(reason):
    return reason in DRIFT_REASONS or reason.startswith('self-report')

def displacement(goal, progress, distance, ground):
    return (0.5 * jac(norm(goal), norm(ground['goal']))
            + 0.3 * abs(distance - ground['dist']) / 10
            + 0.2 * (0 if progress == ground['progress'] else 1))

class FrozenHarness:
    """One run's drift state + the frozen checkStep. Returns (reason, drifting)."""
    def __init__(self):
        self.ground = None
        self.first_goal = set()
        self.dist_hist = []
        self.trace = []          # reasons, in order

    def _emit(self, reason, drifting):
        self.trace.append(reason)
        return reason, drifting

    def step(self, obj):
        goal = str(obj.get('goal', '')).strip()
        progress = obj.get('progress')
        prev_drift = is_drift(self.trace[-1]) if self.trace else False
        if not goal or progress not in PROGRESS:
            return self._emit('ungrammatical', True)                 # hard
        d = as_dist(obj)
        if self.ground is None:
            self.ground = {'goal': goal, 'progress': progress, 'dist': d}
            self.first_goal = norm(goal)
            self.dist_hist = [d]
            return self._emit('grounded', False)
        phi = displacement(goal, progress, d, self.ground)
        if progress in ('stuck', 'circling') and phi > 0.15:          # soft: needs Φ floor + sustained
            return self._emit(f'self-report:{progress}', prev_drift)
        g = norm(goal)
        anchor = (len(g & self.first_goal) / len(g | self.first_goal)) if (g or self.first_goal) else 0.0
        if anchor < 0.30:                                             # hard
            return self._emit('goal-drift', True)
        self.dist_hist.append(d)
        dh = self.dist_hist
        if len(dh) > 4 and min(dh[-4:]) >= dh[-5]:                     # soft: 4-window + sustained
            return self._emit('stalled', prev_drift)
        return self._emit('advancing', False)

# ---------------------------------------------------------------------------
# THE AGENT — both arms identical except that the harness acts on a confirmed
# drift (drifting=True). Both emit a STATE block each step, so cost accounting
# is symmetric; only the return-to-ground injection differs.
# ---------------------------------------------------------------------------
AGENT = os.environ.get('AGENT', mh.MODEL)
CAP = int(os.environ.get('CAP', '12'))

SYSTEM = (
    "You are reasoning toward a complete answer to an open-ended question. Each turn: "
    "advance your reasoning in a few sentences, then a state block — a line reading STATE, "
    "then one JSON object "
    '{"goal": "<the ORIGINAL question, held fixed>", "progress": "advancing|stuck|circling", '
    '"distance": <0-10, how far from a complete answer, 0 = done>}. '
    "Hold 'goal' identical every turn. Do not restate earlier turns; only add."
)
RETURN = (
    "\n\n[smart recursion harness] You have drifted — {why}. Stop. Restate the original "
    "goal in one line, and take the single step that most directly completes it. Return to "
    "the goal; do not press further down this path."
)
FINALIZE = "State your best complete answer to the original question now."

def parse_state(txt):
    i = txt.find('STATE')
    tail = txt[i:] if i >= 0 else txt
    m = re.search(r"\{.*?\}", tail, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None

def run_arm(question, harness):
    """Returns dict(convo, steps, tokens, fired, returns)."""
    before = dict(mh.USAGE)
    convo = [{'role': 'user', 'content': question}]
    det = FrozenHarness()
    steps = 0
    fired = False
    returns = 0
    for _ in range(CAP):
        txt = mh.call(AGENT, SYSTEM, convo, 900)
        steps += 1
        convo.append({'role': 'assistant', 'content': txt})
        obj = parse_state(txt)
        inject = ''
        if obj is not None:
            reason, drifting = det.step(obj)          # the frozen detector runs for BOTH arms
            if harness and drifting and reason != 'grounded':
                fired = True
                returns += 1
                inject = RETURN.format(why=reason)
            # A self-reported 'distance == 0' is the agent declaring completion.
            if as_dist(obj) == 0 and not inject:
                break
        convo.append({'role': 'user', 'content': f"Continue.{inject}"})
    tokens = (mh.USAGE['in'] + mh.USAGE['out']) - (before['in'] + before['out'])
    return dict(convo=convo, steps=steps, tokens=tokens, fired=fired, returns=returns)

def finalize(convo):
    msgs = convo[:-1] if convo and convo[-1]['role'] == 'user' else convo[:]
    msgs = msgs + [{'role': 'user', 'content': FINALIZE}]
    return mh.call(AGENT, "Answer the user's original question directly and completely.", msgs, 800)

# ---------------------------------------------------------------------------
# THE JUDGE PANEL — K judges, each double-order; order-inconsistent => that
# judge scores the pair a tie. Pair verdict = panel majority. Fleiss' kappa
# across judges GATES the decision (RETEST.md).
# ---------------------------------------------------------------------------
DEFAULT_JUDGES = ['claude-opus-4-8', 'claude-sonnet-5', 'claude-haiku-4-5-20251001']
JUDGES = [j.strip() for j in os.environ.get('JUDGES', ','.join(DEFAULT_JUDGES)).split(',') if j.strip()]

JUDGE_SYSTEM = (
    "You are a blind evaluator. You see a QUESTION and two answers, A and B, from two "
    "different systems. Decide which better answers the question, preferring in this order: "
    "(1) addresses the question actually asked; (2) coherent and well-reasoned; (3) complete "
    "— covers the key considerations without a major gap; (4) not padded or repetitive (length "
    'is not quality). Output exactly one JSON object: {"winner": "A"|"B"|"tie", "reason": '
    '"<one sentence>"}. Nothing else.')

def judge_once(model, question, a, b):
    user = f"QUESTION:\n{question}\n\nANSWER A:\n{a}\n\nANSWER B:\n{b}"
    out = mh.call(model, JUDGE_SYSTEM, [{'role': 'user', 'content': user}], 200)
    m = re.search(r'\{.*\}', out, re.S)
    try:
        return json.loads(m.group(0)).get('winner', 'tie') if m else 'tie'
    except Exception:
        return 'tie'

def judge_pair(model, question, control_ans, harness_ans):
    """Double-order. Returns 'control' | 'harness' | 'tie' (tie if it flips)."""
    v1 = judge_once(model, question, control_ans, harness_ans)   # A=control B=harness
    v2 = judge_once(model, question, harness_ans, control_ans)   # A=harness B=control
    if v1 == 'A' and v2 == 'B':
        return 'control'
    if v1 == 'B' and v2 == 'A':
        return 'harness'
    return 'tie'

def fleiss_kappa(rows):
    # rows: list of [n_control, n_harness, n_tie] summing to K per row
    N = len(rows)
    if N == 0:
        return float('nan')
    K = sum(rows[0])
    if K <= 1:
        return float('nan')
    cats = len(rows[0])
    p_j = [sum(r[j] for r in rows) / (N * K) for j in range(cats)]
    P_i = [(sum(c * c for c in r) - K) / (K * (K - 1)) for r in rows]
    P_bar = sum(P_i) / N
    P_e = sum(p * p for p in p_j)
    return (P_bar - P_e) / (1 - P_e) if (1 - P_e) else float('nan')

# ---------------------------------------------------------------------------
def main():
    mh.KEY = mh.api_key()
    n_tasks = int(os.environ.get('TASKS', '3'))
    reps = int(os.environ.get('REPS', '1'))
    outdir = os.environ.get('OUT', 'retest_out')
    os.makedirs(outdir, exist_ok=True)
    tasks = BATTERY[:n_tasks]
    print(f"  retest (H1, RETEST.md): {len(tasks)} criterion-absent tasks × {reps} reps")
    print(f"  agent {AGENT} · cap {CAP} · judge panel {JUDGES}")
    print(f"  detector FROZEN to drift.ts @ 6b483de7 · results -> {outdir}/\n")

    pairs = []      # one per task×rep
    for tid, q in tasks:
        for r in range(reps):
            ctl = run_arm(q, harness=False)
            har = run_arm(q, harness=True)
            c_ans = finalize(ctl['convo'])
            h_ans = finalize(har['convo'])
            verdicts = {j: judge_pair(j, q, c_ans, h_ans) for j in JUDGES}
            counts = [sum(1 for v in verdicts.values() if v == c) for c in ('control', 'harness', 'tie')]
            majority = ('control', 'harness', 'tie')[counts.index(max(counts))] if max(counts) * 2 > len(JUDGES) else 'tie'
            row = dict(task=tid, rep=r, intervened=har['fired'], returns=har['returns'],
                       control_steps=ctl['steps'], harness_steps=har['steps'],
                       control_tokens=ctl['tokens'], harness_tokens=har['tokens'],
                       token_delta=har['tokens'] - ctl['tokens'],
                       verdicts=verdicts, counts=counts, majority=majority,
                       control_answer=c_ans, harness_answer=h_ans, question=q)
            pairs.append(row)
            fmark = f"⚑{har['returns']}" if har['fired'] else "· "
            print(f"    {tid:<13} r{r+1}: ctl {ctl['steps']:>2}/{ctl['tokens']:>6}tok  "
                  f"har {har['steps']:>2}/{har['tokens']:>6}tok {fmark}  "
                  f"Δ{row['token_delta']:>+6}  judge={majority:<7} {counts}")

    # ---- decision (RETEST.md § decision rule) ----
    decisive = [p for p in pairs if p['intervened'] and p['majority'] in ('control', 'harness')]
    cw = sum(1 for p in decisive if p['majority'] == 'control')
    hw = sum(1 for p in decisive if p['majority'] == 'harness')
    L = cw / (cw + hw) if (cw + hw) else float('nan')
    delta = sum(p['token_delta'] for p in pairs) / len(pairs) if pairs else 0
    kappa = fleiss_kappa([p['counts'] for p in pairs])

    if math.isnan(kappa) or kappa < 0.4:
        verdict = 'INCONCLUSIVE (measure untrustworthy: kappa < 0.4)'
    elif not (cw + hw):
        verdict = 'INCONCLUSIVE (no decisive intervened pairs — harness rarely fired)'
    elif L <= 1/3 and delta < 0:
        verdict = 'H1 SUPPORTED (keeps quality AND cheaper on net)'
    elif L >= 1/2 or delta >= 0:
        verdict = 'H0 / KILL (returns hurt quality, or overhead ate the saving)'
    else:
        verdict = 'INCONCLUSIVE (between thresholds — needs more N)'

    print("\n  ---- verdict ----")
    print(f"  intervened pairs: {sum(1 for p in pairs if p['intervened'])}/{len(pairs)}   decisive: {len(decisive)}")
    print(f"  control-wins {cw}  harness-wins {hw}  ->  L = {L if not math.isnan(L) else 'n/a'}")
    print(f"  mean net token delta (harness - control): {delta:+.0f}   (negative = harness cheaper)")
    print(f"  Fleiss kappa across {len(JUDGES)} judges: {kappa:.2f}"
          f"   {'(trustworthy)' if not math.isnan(kappa) and kappa>=0.4 else '(too noisy to conclude)'}")
    print(f"\n  DECISION (rule fixed in RETEST.md, before data): {verdict}")

    # ---- persist: full results + a BLINDED file for the human subsample ----
    with open(f"{outdir}/results.json", 'w') as f:
        json.dump(dict(config=dict(tasks=n_tasks, reps=reps, agent=AGENT, judges=JUDGES,
                                   detector='drift.ts@6b483de7'),
                       L=L, mean_token_delta=delta, kappa=kappa, verdict=verdict,
                       pairs=pairs), f, indent=2)
    # Blind human rating: randomize which of A/B is the harness, hide the label.
    import random
    blind = []
    for i, p in enumerate(pairs):
        swap = random.random() < 0.5
        A, B = (p['harness_answer'], p['control_answer']) if swap else (p['control_answer'], p['harness_answer'])
        blind.append(dict(pair_id=i, question=p['question'], answer_A=A, answer_B=B,
                          _key=('A=harness' if swap else 'A=control')))
    with open(f"{outdir}/human_blind.json", 'w') as f:
        json.dump(blind, f, indent=2)
    print(f"\n  wrote {outdir}/results.json and {outdir}/human_blind.json")
    print("  (human_blind.json: rate A vs B per RETEST rubric; _key reveals the arm AFTER rating.)")
    print("\n  BOUNDARY: the panel is a PROXY — these tasks have no ground truth. A win reads")
    print("  'a trustworthy blind panel finds it as good at fewer net tokens', NOT 'it is as good'.")
    print("  Publish this beside the codebench NEGATIVE — the boundary is what makes it honest.")

if __name__ == '__main__':
    main()
