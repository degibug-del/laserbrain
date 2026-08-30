#!/usr/bin/env python3
"""branch_test.py — do goal-drift fires cluster on goal RESTATEMENTS?

THE PREDICTION (NUANCED-VARIEGATED.md, 2026-07-25). If Phi's goal term fails because it
applies a nuanced measure to a variegated process, then its false fires should sit on
BRANCH POINTS -- steps where the agent restated its goal to name a sub-task -- rather than
being scattered through a run. And Phi should be well behaved wherever the goal is restated
in stable language, however badly the work is going.

If the fires are spread evenly across restatements and non-restatements, the framing is a
pair of nice words and should be dropped.

This could not be run before 2026-07-25: the session files recorded ZERO fires, because
Session.feed decided `drifting` by substring-matching a response whose quotes were escaped.
Fixed that morning; this is the first run against data that actually contains fires.
"""
import glob, json, os, re, sys
from collections import Counter

STOP = set('a an the of to for and or in on at is are be was were it its this that with '
           'from by as into so then than we you i our your my me not no do does did'.split())

def norm(s):
    ws = [w for w in re.findall(r"[a-z0-9']+", (s or '').lower()) if w not in STOP]
    return set(w[:4] if len(w) > 4 else w for w in ws)

def overlap(a, b):
    return len(a & b) / len(a | b) if (a or b) else 1.0

rows = []
for f in glob.glob(os.path.expanduser('~/.claude/laserbrain/*.json')):
    try: d = json.load(open(f))
    except Exception: continue
    for seg in (d.get('segments') or []) + [d]:
        ch = seg.get('checks') or []
        if not ch: continue
        ground, prev = norm(ch[0].get('goal')), None
        for c in ch:
            g = norm(c.get('goal'))
            rows.append({'reason': c.get('reason'),
                         'restated': prev is not None and overlap(g, prev) < 0.999,
                         'anchor': overlap(g, ground),
                         'first': prev is None})
            prev = g

body = [r for r in rows if not r['first'] and r['reason']]
print(f"  scoreable checks (reason recorded, not ground): {len(body)}")
print(f"  reasons: {dict(Counter(r['reason'] for r in body))}\n")

FIRE = {'goal-drift'}
R  = [r for r in body if r['restated']]
NR = [r for r in body if not r['restated']]
fR  = sum(1 for r in R  if r['reason'] in FIRE)
fNR = sum(1 for r in NR if r['reason'] in FIRE)

print(f"  goal RESTATED   {len(R):>4} checks   goal-drift {fR:>3}   " + (f"rate {fR/len(R):.0%}" if R else ""))
print(f"  goal UNCHANGED  {len(NR):>4} checks   goal-drift {fNR:>3}   " + (f"rate {fNR/len(NR):.0%}" if NR else ""))
print()
if R and NR:
    if fNR == 0 and fR:
        print(f"  EVERY goal-drift fire sits on a restatement — 0 across {len(NR)} unchanged-goal checks.")
        print("  That is the prediction, exactly.")
    elif fNR:
        print(f"  fires are {(fR/len(R))/(fNR/len(NR)):.1f}x more likely on a restatement")
    else:
        print("  no fires at all — nothing to conclude.")

# The counterweight: regrounds are restatements the harness ACCEPTED.
rg = sum(1 for r in body if r['reason'] == 'reground')
print(f"\n  restatements the harness ACCEPTED (reground): {rg}")
print(f"  restatements it REFUSED (goal-drift):        {fR}")
if rg + fR:
    print(f"  → {fR/(rg+fR):.0%} of goal restatements were called drift")
