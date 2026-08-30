import json, re, sys
T = sys.argv[1]

def text_of(m):
    c=m.get('content')
    if isinstance(c,str): return c,0
    if not isinstance(c,list): return '',0
    txt,tools=[],0
    for b in c:
        if isinstance(b,dict):
            if b.get('type')=='text': txt.append(b.get('text',''))
            elif b.get('type')=='tool_use': tools+=1
    return '\n'.join(txt),tools

turns=[]
for line in open(T):
    try:d=json.loads(line)
    except:continue
    if d.get('type') not in('user','assistant'):continue
    m=d.get('message')
    if not isinstance(m,dict) or m.get('role') not in('user','assistant'):continue
    txt,tools=text_of(m)
    if m.get('role')=='user':
        c=m.get('content')
        if isinstance(c,list) and all(isinstance(b,dict) and b.get('type')=='tool_result' for b in c):continue
    if not txt.strip() and tools==0:continue
    turns.append({'role':m['role'],'text':txt,'tools':tools})
merged=[]
for t in turns:
    if merged and merged[-1]['role']==t['role']:
        merged[-1]['text']+='\n'+t['text']; merged[-1]['tools']+=t['tools']
    else: merged.append(dict(t))
turns=merged

HEDGE=re.compile(r'\b(maybe|might|perhaps|possibly|could be|i think|on the other hand|however|reconsider|let me (think|reconsider)|actually|arguably|to be fair|not sure|i.?m not sure)\b',re.I)
ABSOLUTE=re.compile(r'\b(never|always|the only|everything|nothing|impossible|must|cannot|no one|entirely)\b',re.I)
NEG=re.compile(r'\b(no|not|don.?t|stop|wrong|paranoid|absolute|isn.?t|aren.?t|false|too (much|many|verbose)|just|only|why|what)\b',re.I)
FORWARD=re.compile(r'^\s*(yes|yeah|do it|go|sure|ok|okay|commit|build|add|ship|deploy|\d+\.?|make|show|write|continue|works)\b',re.I)
def words(s):return re.findall(r"[a-z0-9']+",s.lower())
def dens(s,rx):w=words(s);return 100*len(rx.findall(s))/max(len(w),1)
def is_corr(u):
    t=u['text'].strip()
    if not t or len(t)>240:return False
    if FORWARD.match(t):return False
    return bool(NEG.search(t))

# assistant-turn stream with score + correction label
seq=[]  # (assistant_index_in_turns, score, corrected_next)
for i,t in enumerate(turns):
    if t['role']!='assistant':continue
    nxt=turns[i+1] if i+1<len(turns) else None
    corrected=bool(nxt and nxt['role']=='user' and is_corr(nxt))
    score=dens(t['text'],HEDGE)+0.5*dens(t['text'],ABSOLUTE)
    seq.append({'score':score,'corr':corrected})

n=len(seq); ncorr=sum(s['corr'] for s in seq)
scores=sorted(s['score'] for s in seq)
thr=scores[int(0.80*n)]   # fire on top ~20% — a fixed, untuned percentile
for s in seq: s['fire']=s['score']>=thr

def lead_times(fire_key):
    # for each correction, how many consecutive 'fire' turns immediately precede it (incl. itself)
    leads=[]
    for j,s in enumerate(seq):
        if not s['corr']:continue
        L=0; k=j
        while k>=0 and seq[k][fire_key]:
            L+=1;k-=1
        leads.append(L)
    return leads

def bench(name, fire_key):
    fires=[j for j,s in enumerate(seq) if s[fire_key]]
    # a "trigger episode" = maximal run of consecutive fires
    episodes=[]; run=[]
    for j,s in enumerate(seq):
        if s[fire_key]: run.append(j)
        elif run: episodes.append(run); run=[]
    if run: episodes.append(run)
    # episode is a TRUE alarm if it ends within 1 turn of a correction
    corr_idx={j for j,s in enumerate(seq) if s['corr']}
    true_ep=sum(1 for ep in episodes if any((ep[-1]+d) in corr_idx for d in (0,1)))
    leads=lead_times(fire_key)
    warned=sum(1 for L in leads if L>0)
    print(f"  {name}")
    print(f"     fires on {len(fires)}/{n} turns; {len(episodes)} trigger episodes, {true_ep} ended at a real correction  (precision {true_ep/max(len(episodes),1):.2f})")
    print(f"     corrections with >=1 turn of early warning: {warned}/{len(leads)}  ({100*warned/max(len(leads),1):.0f}%)")
    print(f"     mean early-warning lead when it warned: {sum(L for L in leads if L>0)/max(warned,1):.1f} turns")

print(f"  {n} assistant turns, {ncorr} corrections ({100*ncorr/n:.0f}% base). fire threshold = top 20% drift score.\n")
bench("DRIFT signal (hedge + absolutes)", 'fire')

# budget baseline: fire every Nth turn to match the same fire-rate (~20%)
N=5
for j,s in enumerate(seq): s['budget']=((j+1)%N==0)
print()
bench(f"STEP BUDGET baseline (fire every {N}th turn, same ~20% rate)", 'budget')
