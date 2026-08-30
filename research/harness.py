#!/usr/bin/env python3
"""
Agent harness for the drift-fixer study (STUDY.md).

One real LLM agent, three stopping rules, tasks with objective ground truth.
This is NOT a simulation: the agent's steps are real model output, and the only
thing that differs between conditions is when the run is told to stop and answer.
Simulating the trajectory — defining both the spiral and the detector — is the
rigging trap the preregistration forbids; this avoids it by running an actual
agent and scoring against a fixed correct answer it cannot see.

  control : run until the agent finalises on its own, or a hard ceiling.
  budget  : force a final answer at a fixed step (the standard baseline).
  drift   : force a final answer when the divergence signal crosses threshold.

The signal is the one the pilot found, not the one the spec guessed: hedge +
absolute-language density + self-similarity to recent steps (the looping term).

Usage:  python3 harness.py            # small real pilot
        python3 harness.py --dry      # no API calls; prints the plan
"""
import json, os, re, sys, time, urllib.request, urllib.error

MODEL = 'claude-haiku-4-5-20251001'
MAX_STEPS = 12         # hard ceiling — recursion needs room
BUDGET = 5             # the step-budget baseline fires here
DRIFT_THRESHOLD = 3.0  # fixed a priori; STUDY.md calls for calibration before the powered run

def api_key():
    # Prefer the environment, so a funded key can be supplied from a hidden
    # prompt without landing in any file or transcript:
    #   read -rs K; ANTHROPIC_API_KEY="$K" python3 harness.py
    # Falls back to laserbrain/.env, whose key is currently revoked (401).
    k = os.environ.get('ANTHROPIC_API_KEY')
    if k: return k
    env = os.path.expanduser('~/Library/Mobile Documents/com~apple~CloudDocs/phronesis/laserfield/.env')
    for line in open(env):
        if line.startswith('ANTHROPIC_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"\'')
    raise SystemExit('set ANTHROPIC_API_KEY in the environment (the .env key is 401)')

KEY = None
def call(system, messages, max_tokens=350):
    body = json.dumps({'model': MODEL, 'max_tokens': max_tokens, 'system': system, 'messages': messages}).encode()
    req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body, headers={
        'x-api-key': KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read())
            txt = ''.join(b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text')
            u = d.get('usage', {})
            return txt, u.get('input_tokens', 0) + u.get('output_tokens', 0)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(5); continue
            raise
    raise SystemExit('api failed')

# ---- the divergence signal -------------------------------------------------
HEDGE = re.compile(r'\b(maybe|might|perhaps|possibly|i think|however|reconsider|actually|wait|hmm|let me reconsider|on second thought|not sure|double.?check|re-?check)\b', re.I)
ABSOL = re.compile(r'\b(never|always|the only|everything|nothing|impossible|must|cannot|definitely|absolutely)\b', re.I)
def words(s): return re.findall(r"[a-z0-9']+", s.lower())
def dens(s, rx): w = words(s); return 100 * len(rx.findall(s)) / max(len(w), 1)
def similarity(a, b):
    wa, wb = set(words(a)), set(words(b))
    return len(wa & wb) / max(len(wa | wb), 1)
def drift_score(step, prev):
    sim = max((similarity(step, p) for p in prev[-2:]), default=0.0)
    return dens(step, HEDGE) + 0.5 * dens(step, ABSOL) + 4.0 * sim

# ---- tasks with objective ground truth -------------------------------------
def has(*subs):
    return lambda a: any(s in a.lower() for s in subs)
def in_order(a, *names):
    a = a.lower(); pos = [a.find(n) for n in names]
    return all(p >= 0 for p in pos) and pos == sorted(pos)

# Harder battery: multi-constraint logic (real deduction chains) and character
# counting (a genuine model weakness that provokes recount/loop). Every ground
# truth verified by hand before wiring in. The first battery was too easy — a
# capable model finalised in one step, so the three conditions never diverged.
TASKS = [
    # deep: needs several deduction steps; cutting off early should FAIL
    dict(id='logic_pets', control=True,
         q="Ana, Ben, and Cara each have a different pet (cat, dog, fish) and a different shirt colour (red, blue, green). "
           "Clues: (1) Ana does not have the cat. (2) The dog owner wears red. (3) Ben wears blue. (4) Cara does not have the fish. "
           "(5) The fish owner wears green. Who owns the cat, and what colour shirt do they wear? Reason step by step.",
         check=lambda a: 'ben' in a.lower() and 'blue' in a.lower()),
    dict(id='order', control=True,
         q="Five runners finish a race. Amy finished before Ben. Ben finished before Cara. Dan finished before Amy. "
           "Dan finished before Cara. Eve finished last. Give the finishing order, first to last.",
         check=lambda a: in_order(a, 'dan', 'amy', 'ben', 'cara', 'eve')),
    dict(id='multihop', control=True,
         q="Tyke has 4 marbles. Spike has twice as many as Tyke. Jerry has 5 fewer than Spike. Tom has 3 times as many as Jerry. "
           "Butch has 7 more than Tom. How many marbles does Butch have? Work through it one relationship at a time.",
         check=has('16')),
    # loop-prone: counting is where a model miscounts, doubts, recounts — the spiral
    dict(id='count_a', control=False,
         q="Count how many times the letter 'a' appears in this sentence, checking your count carefully: "
           "\"A banana and a bandana lay on a cabana at dawn.\"",
         check=has(' 16', '16 ', '= 16', 'is 16', '16.', 'sixteen')),
    # trap: intuition says scale to 100; the answer is 5. Tempts over-thinking.
    dict(id='widgets', control=False,
         q="If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets? "
           "Answer in minutes, and be careful.",
         check=has('5 min', '5 minute', 'five min', 'five minute', 'is 5', '= 5')),
]

SYSTEM = (
    "You are solving one problem, thinking step by step. Each turn, take exactly ONE short "
    "reasoning step, OR give your final answer. To give the final answer, begin your message "
    "with 'FINAL:' and then the answer. Do not write FINAL until you are done reasoning."
)

def run(task, condition):
    msgs = [{'role': 'user', 'content': task['q']}]
    steps, tokens = [], 0
    for t in range(MAX_STEPS):
        force = (condition == 'budget' and t >= BUDGET) or \
                (condition == 'drift' and steps and drift_score(steps[-1], steps[:-1]) >= DRIFT_THRESHOLD)
        if force:
            msgs.append({'role': 'user', 'content': "Stop reasoning and give your FINAL answer now, on one line beginning FINAL:."})
        txt, tk = call(SYSTEM, msgs); tokens += tk
        msgs.append({'role': 'assistant', 'content': txt})
        if txt.strip().upper().startswith('FINAL') or force or 'FINAL:' in txt.upper():
            ans = txt.split('FINAL:', 1)[-1] if 'FINAL:' in txt.upper() else txt
            return dict(answer=ans, steps=t + 1, tokens=tokens, correct=task['check'](ans), forced=force)
        steps.append(txt)
        msgs.append({'role': 'user', 'content': "Continue with one more step, or give FINAL if done."})
    # ceiling: force
    msgs.append({'role': 'user', 'content': "Give your FINAL answer now, beginning FINAL:."})
    txt, tk = call(SYSTEM, msgs); tokens += tk
    ans = txt.split('FINAL:', 1)[-1] if 'FINAL:' in txt.upper() else txt
    return dict(answer=ans, steps=MAX_STEPS + 1, tokens=tokens, correct=task['check'](ans), forced=True)

def main():
    global KEY
    if '--dry' in sys.argv:
        print(f"  {len(TASKS)} tasks x 3 conditions = {len(TASKS)*3} runs; ceiling {MAX_STEPS}, budget {BUDGET}, drift thr {DRIFT_THRESHOLD}")
        for t in TASKS: print(f"    {t['id']:10} control={t['control']}")
        return
    KEY = api_key()
    conds = ['control', 'budget', 'drift']
    print(f"  {len(TASKS)} tasks x {len(conds)} conditions on {MODEL}\n")
    agg = {c: dict(correct=0, steps=0, tokens=0, n=0) for c in conds}
    for task in TASKS:
        row = f"  {task['id']:10}{'(control)' if task['control'] else '':10}"
        for c in conds:
            r = run(task, c)
            a = agg[c]; a['correct'] += r['correct']; a['steps'] += r['steps']; a['tokens'] += r['tokens']; a['n'] += 1
            row += f"  {c}:{'ok ' if r['correct'] else 'MISS'}/{r['steps']}st"
        print(row)
    print("\n  --- aggregate ---")
    for c in conds:
        a = agg[c]
        print(f"  {c:8} correct {a['correct']}/{a['n']}   mean steps {a['steps']/a['n']:.1f}   tokens {a['tokens']}")

if __name__ == '__main__':
    main()
