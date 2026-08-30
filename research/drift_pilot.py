import json, re, sys
T = sys.argv[1]

def text_of(msg):
    c = msg.get('content')
    if isinstance(c, str): return c, 0
    if not isinstance(c, list): return '', 0
    txt, tools = [], 0
    for b in c:
        if not isinstance(b, dict): continue
        if b.get('type') == 'text': txt.append(b.get('text',''))
        elif b.get('type') == 'tool_use': tools += 1
    return '\n'.join(txt), tools

# ordered real user/assistant turns
turns = []
with open(T) as f:
    for line in f:
        try: d = json.loads(line)
        except: continue
        if d.get('type') not in ('user','assistant'): continue
        m = d.get('message')
        if not isinstance(m, dict): continue
        role = m.get('role')
        if role not in ('user','assistant'): continue
        txt, tools = text_of(m)
        # skip tool-result-only user turns (no human text) and empty
        if role == 'user':
            c = m.get('content')
            if isinstance(c, list) and all(isinstance(b,dict) and b.get('type')=='tool_result' for b in c): continue
        if not txt.strip() and tools == 0: continue
        turns.append({'role': role, 'text': txt, 'tools': tools})

# collapse consecutive same-role (assistant turns split across tool rounds) into one
merged = []
for t in turns:
    if merged and merged[-1]['role']==t['role']:
        merged[-1]['text'] += '\n'+t['text']; merged[-1]['tools'] += t['tools']
    else:
        merged.append(dict(t))
turns = merged

HEDGE = re.compile(r'\b(maybe|might|perhaps|possibly|could be|i think|on the other hand|however|reconsider|let me (think|reconsider)|actually|arguably|to be fair|not sure|i.?m not sure)\b', re.I)
ABSOLUTE = re.compile(r'\b(never|always|the only|everything|nothing|impossible|must|cannot|no one|entirely)\b', re.I)
# a user turn that pushes back / corrects (not a forward directive)
NEG = re.compile(r'\b(no|not|don.?t|stop|wrong|paranoid|absolute|isn.?t|aren.?t|false|too (much|many|verbose)|just|only|why|what)\b', re.I)
FORWARD = re.compile(r'^\s*(yes|yeah|do it|go|sure|ok|okay|commit|build|add|ship|deploy|\d+\.?|make|show|write|continue|works)\b', re.I)

def words(s): return re.findall(r"[a-z0-9']+", s.lower())

def is_correction(u):
    t = u['text'].strip()
    if not t or len(t) > 240: return False           # corrections are short
    if FORWARD.match(t): return False                 # forward directive, not a correction
    return bool(NEG.search(t))

def hedge_density(s):
    w = words(s); 
    return 100*len(HEDGE.findall(s))/max(len(w),1)
def absolute_density(s):
    w = words(s)
    return 100*len(ABSOLUTE.findall(s))/max(len(w),1)

# per assistant turn: features + label (next user turn is a correction)
rows = []
for i,t in enumerate(turns):
    if t['role'] != 'assistant': continue
    nxt = turns[i+1] if i+1 < len(turns) else None
    corrected = bool(nxt and nxt['role']=='user' and is_correction(nxt))
    w = words(t['text'])
    ends_q = t['text'].rstrip().endswith('?')
    rows.append({
        'i': i, 'chars': len(t['text']), 'nwords': len(w), 'tools': t['tools'],
        'hedge': hedge_density(t['text']), 'abs': absolute_density(t['text']),
        'ends_q': ends_q, 'corrected': corrected,
    })

n = len(rows); ncorr = sum(r['corrected'] for r in rows)
print(f"  assistant turns: {n}   followed by a correction: {ncorr}  ({100*ncorr/n:.0f}%)")
print()

def mean(xs): return sum(xs)/len(xs) if xs else 0
for feat in ['hedge','abs','chars','nwords','tools']:
    c = [r[feat] for r in rows if r['corrected']]
    nc= [r[feat] for r in rows if not r['corrected']]
    print(f"  {feat:7} corrected={mean(c):8.2f}   not={mean(nc):8.2f}   ratio={mean(c)/max(mean(nc),1e-9):.2f}")
eq = sum(1 for r in rows if r['corrected'] and r['ends_q'])
enq= sum(1 for r in rows if r['ends_q'])
print(f"  ends_q  P(correction | ends '?')={eq/max(enq,1):.2f}   base rate={ncorr/n:.2f}   (n ends_q={enq})")

# The real test: does a drift signal beat turn-position (the step-budget analog)?
# Build a simple score = hedge + 0.5*abs + 3*ends_q ; rank turns; do corrections
# concentrate in the top vs a position-based baseline (later turns)?
for r in rows: r['score'] = r['hedge'] + 0.5*r['abs'] + 3*(1 if r['ends_q'] else 0)
def precision_at_top(key, frac=0.2):
    k = max(1,int(n*frac))
    top = sorted(rows, key=lambda r: -r[key])[:k]
    return sum(t['corrected'] for t in top)/k
print()
print(f"  precision@top20% by DRIFT score : {precision_at_top('score'):.2f}")
print(f"  precision@top20% by turn LENGTH : {precision_at_top('chars'):.2f}   (a budget flags long turns)")
print(f"  precision@top20% by turn INDEX  : {precision_at_top('i'):.2f}   (a budget flags late turns)")
print(f"  base rate                       : {ncorr/n:.2f}")
