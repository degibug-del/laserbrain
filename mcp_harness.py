#!/usr/bin/env python3
"""
Laserbrain MCP agent recursion harness — spelling with JSON.

The agent measures itself against a fixed, findable, unchangeable, RECURSIVE, and
now EXPRESSIVE grammar: it spells its current state into a fixed JSON schema every
step. JSON is the grammar that is universal (every agent speaks it), fixed (the
format does not move), recursive (nested), and rich enough to hold reasoning state
— which forty weather words were not. That closes the gap the word-reduction had.

Confusion is ungrammaticality against the schema, made deterministic — a validator
answers it, not a model's judgment. But validity alone SATURATES (a confused agent
can spell valid JSON that merely says 'confused'), the same trap coherence had. So
the signal is completeness + consistency + stability, not just 'does it parse':

  grammatical : parses, matches the schema (enum + types).           [can it spell at all]
  self-report : progress field is not 'stuck'/'circling'.            [does it say it's spiralling]
  anchored    : the goal it spells still matches its first goal.     [has it lost the thread]
  advancing   : distance-to-goal is not stalled across steps.        [is it actually moving]

Return to ground when the state cannot be spelled cleanly, or the spelling reveals
a spiral. The spelling is both the diagnostic and the return ritual: forcing a
compression into a fixed schema interrupts the recursion by construction.

The SCHEMA is the grammar — fixed here, canonically it would be served by the MCP
(the 'findable' source; the live fetch currently 403s, so a local copy of an
unchangeable standard stands in). Run:
  read -rs K && ANTHROPIC_API_KEY="$K" python3 mcp_harness.py
"""
import json, os, re, sys, time, urllib.request, urllib.error

MODEL = 'claude-haiku-4-5-20251001'
MAX_STEPS = 10
STALL_LIMIT = 3     # steps of non-decreasing distance before we call it stalled
GOAL_ANCHOR_MIN = 0.30  # goal drifted below this overlap with the first goal = lost thread

# ---- the grammar: a fixed JSON schema for a reasoning state ------------------
SCHEMA = {
    'goal':     'string, non-empty — the ONE goal, held stable across steps',
    'doing':    'string — what this step does',
    'progress': "one of: advancing | stuck | circling",
    'distance': 'integer 0-10 — how far from done (0 = done)',
    'next':     'string — the single next action',
    'blocked':  'string or null — what blocks you, or null',
}
PROGRESS = {'advancing', 'stuck', 'circling'}

def api_key():
    k = os.environ.get('ANTHROPIC_API_KEY')
    if k: return k.strip()          # strip: a hidden `read -rs` paste can carry stray whitespace/newline
    raise SystemExit('set ANTHROPIC_API_KEY in the environment')
KEY = None

# Real cost, accumulated from the API's own usage field — the objective measure
# steps only proxy for. A caller snapshots this around a run() to get per-run
# tokens; the schema condition's spell() calls land here too, so its monitoring
# overhead is counted, not hidden. Tokens are ground truth; steps flattered.
USAGE = {'in': 0, 'out': 0, 'calls': 0}

def call(model, system, messages, max_tokens=350, retries=5):
    """One API call, resilient to transient failures. A long grader run makes
       hundreds of sequential calls; without this a single timeout or an
       'overloaded' 529 kills the whole run (as it did at pair 9/12). Retries the
       transient classes with backoff; a real 4xx (401 etc.) still fails fast."""
    body = json.dumps({'model': model, 'max_tokens': max_tokens, 'system': system, 'messages': messages}).encode()
    for attempt in range(retries):
        req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body,
            headers={'x-api-key': KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            u = d.get('usage', {})
            USAGE['in'] += u.get('input_tokens', 0); USAGE['out'] += u.get('output_tokens', 0); USAGE['calls'] += 1
            return ''.join(b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text')
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504, 529) and attempt < retries - 1:
                time.sleep(min(2 ** attempt, 20)); continue
            raise
        except (TimeoutError, urllib.error.URLError):
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 20)); continue
            raise

def llm(system, messages, max_tokens=350):
    return call(MODEL, system, messages, max_tokens)

def words(s): return set(re.findall(r"[a-z0-9']+", str(s).lower()))

def spell(convo):
    """Ask the agent to spell its state as JSON against the fixed schema."""
    sys_p = ("Report your CURRENT working state as a JSON object, nothing else — no prose, no code fence. "
             "Exactly these keys:\n" + json.dumps(SCHEMA, indent=2) +
             "\nHold 'goal' identical to the goal you first stated. Output only the JSON.")
    out = llm(sys_p, convo + [{'role':'user','content':"Spell your state as JSON now:"}], 200)
    m = re.search(r'\{.*\}', out, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None

# Folded monitoring: the agent emits its state block INSIDE its normal step, so
# checking it costs no extra call. This is what makes laserbrain a real token
# minimizer — with a separate spell() call, half the steps at 2× per-step cost is
# a wash; folded, half the steps is half the tokens. Same signals, ~zero overhead.
STATE_INSTR = ("\n\nBEGIN every message with a state block: a line reading STATE, then one JSON object "
               "with keys goal, doing, progress (advancing|stuck|circling), distance (integer 0-10), "
               "next, blocked — THEN take your step below it. Hold 'goal' identical to the goal you first "
               "stated. The block goes FIRST so a long step can never truncate it away.")

def parse_state(txt):
    """Pull the inline state block out of a folded step — no extra LLM call. The
       block is emitted FIRST, so a truncated step never loses it. Non-greedy so
       it grabs the state object, not everything up to a later brace."""
    i = txt.find('STATE')
    tail = txt[i:] if i >= 0 else txt
    m = re.search(r'\{.*?\}', tail, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None

def grammatical(obj):
    """Can the state be spelled at all: a real goal and a valid self-report.
       Deliberately lenient on the rest — a dropped optional key or a string
       distance is a spelling quirk, not confusion, and the strict version
       masked the real signals (self-report, drift, stall) behind a technicality."""
    if not isinstance(obj, dict): return False
    if not str(obj.get('goal', '')).strip(): return False
    if obj.get('progress') not in PROGRESS: return False
    return True

def as_dist(obj):
    try: return max(0, min(10, int(float(obj.get('distance', 5)))))
    except Exception: return 5

# ---- the displacement metric on grammatical states (SUBSTRATE.md) -----------
# A pseudometric: Φ(n) = displacement(sₙ, ground). PROOF.md makes this the arbiter
# of drift. Weights fixed before data, a modelling choice (not tuned to a run).
ALPHA, BETA, GAMMA = 0.5, 0.3, 0.2

def jaccard_dist(a, b):
    if not a and not b: return 0.0
    return 1 - len(a & b) / len(a | b)

def displacement(s, ground):
    return (ALPHA * jaccard_dist(words(s.get('goal', '')), words(ground.get('goal', '')))
          + BETA  * abs(as_dist(s) - as_dist(ground)) / 10
          + GAMMA * (0 if s.get('progress') == ground.get('progress') else 1))

def run(task, use_schema, cap=None, fold=False):
    # cap = a hard step budget (the dumb baseline: stop at N, no monitoring). None
    # means run to MAX_STEPS. use_schema adds the drift-fixer on top. fold=True
    # folds the state-spelling into the work step (no extra call) — the token-
    # minimizer design; costs nothing to monitor.
    convo = [{'role':'user','content':task}]
    steps = 0; spellings = []; first_goal = None; ground = None; dist_hist = []
    SYSTEM = ("You are working on a task, thinking step by step. Each turn take ONE step, "
              "or begin your message with FINAL: to conclude.")
    SYS = SYSTEM + STATE_INSTR if (use_schema and fold) else SYSTEM
    for t in range(cap if cap is not None else MAX_STEPS):
        txt = llm(SYS, convo, 450 if (use_schema and fold) else 350); steps += 1
        convo.append({'role':'assistant','content':txt})
        if txt.strip().upper().startswith('FINAL'):
            return dict(steps=steps, ret='self', spellings=spellings, convo=convo)
        if use_schema:
            obj = parse_state(txt) if fold else spell(convo); spellings.append(obj)
            if not grammatical(obj):
                return dict(steps=steps, ret='ungrammatical (cannot spell state)', spellings=spellings, convo=convo)
            if first_goal is None:
                first_goal = words(obj['goal']); ground = obj
            phi = displacement(obj, ground)
            # self-report of a spiral — but only once displaced from ground.
            # PROOF.md makes Φ the arbiter: at Φ=0 there is nothing to detect, and
            # 'circling' is a claim about a loop, which cannot exist at zero
            # displacement (step 1, or a state identical to ground). This gates the
            # premature-mood returns the N=18 run exposed — step-1 self-reports at
            # Φ=0 on hard questions — by applying the proof's criterion, not tuning
            # a threshold to the data. STUDY.md amendment 2026-07-22.
            if obj['progress'] in ('stuck', 'circling') and phi > 0:
                return dict(steps=steps, ret=f"self-report: {obj['progress']}", spellings=spellings, convo=convo)
            # lost the thread: goal drifted from the anchor
            anchor = len(first_goal & words(obj['goal'])) / max(len(first_goal | words(obj['goal'])), 1)
            if t > 0 and anchor < GOAL_ANCHOR_MIN:
                return dict(steps=steps, ret=f"goal drift (anchor={anchor:.2f})", spellings=spellings, convo=convo)
            # stalled: distance not decreasing
            dist_hist.append(as_dist(obj))
            if len(dist_hist) > STALL_LIMIT and min(dist_hist[-STALL_LIMIT:]) >= dist_hist[-STALL_LIMIT-1]:
                return dict(steps=steps, ret=f"stalled (distance {dist_hist[-STALL_LIMIT-1:]})", spellings=spellings, convo=convo)
        convo.append({'role':'user','content':"Continue with one step, or FINAL: to conclude."})
    return dict(steps=steps, ret='ceiling', spellings=spellings, convo=convo)

TASKS = [
    ("open_synthesis", "Design the ideal governance structure for a lunar research colony. Keep refining until it is truly complete."),
    ("open_deliberate","Is it ever ethical to lie? Reason it fully through, considering every angle, until you are certain."),
]

def main():
    global KEY
    print("  grammar: fixed JSON schema —", ', '.join(SCHEMA.keys()))
    if '--dry' in sys.argv:
        print("  (dry) tasks:", [t[0] for t in TASKS]); return
    KEY = api_key()
    for tid, q in TASKS:
        base = run(q, use_schema=False)
        sch  = run(q, use_schema=True)
        print(f"\n  {tid}")
        print(f"     control : {base['steps']} steps, returned by {base['ret']}")
        print(f"     schema  : {sch['steps']} steps, returned by {sch['ret']}")
        for i, s in enumerate(sch['spellings']):
            if s: print(f"       step {i+1}: goal='{str(s.get('goal'))[:38]}' progress={s.get('progress')} dist={s.get('distance')}")
            else: print(f"       step {i+1}: <unspellable>")

if __name__ == '__main__':
    main()
