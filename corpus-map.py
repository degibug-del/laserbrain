#!/usr/bin/env python3
"""A directory over the drift corpus — what is in it, and what it can answer.

    python3 corpus-map.py

Three things a pile of JSONL will not tell you without being asked:

  WHAT IS IN IT      readings, fires, runs, agents, eras. The corpus spans two logging
                     policies and pooling them is how a 24.8% fire rate got reported as
                     22%, so the eras lead.
  WHO SAID SO        every label carries `by`. A rule-derived label, a self-marked one and
                     an independent one are three different strengths of evidence, and
                     averaging them throws away the only thing that makes a label worth
                     having.
  WHAT IT CANNOT SAY the honest half. Precision is computable; d-prime is not, and never
                     will be from this corpus, because nothing labels the quiet steps.
                     `unclear` is a real answer here, not a gap.
"""
import collections
import json
import os
import pathlib

DRIFT = pathlib.Path(os.environ.get('LASERBRAIN_DRIFT_LOG')
                     or pathlib.Path.home() / '.config/laserbrain/drift-log.jsonl')
OUT = pathlib.Path(os.environ.get('LASERBRAIN_OUTCOMES_LOG')
                   or pathlib.Path.home() / '.config/laserbrain/verdict-outcomes.jsonl')


def load(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


rows, labels = load(DRIFT), load(OUT)


def key(r):
    return (r.get('run'), r.get('step'))


lab = {key(l): l for l in labels}
fires = [r for r in rows if r.get('drifting')]
firekeys = {key(r) for r in fires}
dated = [r for r in rows if r.get('drifting') is not None]
undated = [r for r in rows if r.get('drifting') is None]

bar = '=' * 68
print(f'\n{bar}\n  CORPUS DIRECTORY\n{bar}')
print(f'  readings          {len(rows)}')
print(f'  fires             {len(fires)}')
print(f'  runs              {len({r.get("run") for r in rows})}')
print(f'  agents            {", ".join(sorted({str(r.get("agent")) for r in rows}))}')
ts = sorted(r['ts'] for r in rows if r.get('ts'))
if ts:
    print(f'  span              {ts[0][:10]} to {ts[-1][:10]}')

print(f'\n{bar}\n  ERAS - never pool these\n{bar}')
print(f'  fires-only     {len(undated):>5} readings   every one a fire, no denominator beside it')
print(f'  every-step     {len(dated):>5} readings   {len(fires)} fires '
      f'({len(fires)/max(len(dated),1)*100:.1f}%) - the only era a RATE means anything in')
vs = collections.Counter(r.get('grammar_version') for r in rows if r.get('grammar_version'))
print(f'  version-stamped{sum(vs.values()):>5} readings   {dict(vs) or "none"}')

print(f'\n{bar}\n  LABELS - who said so\n{bar}')
STRENGTH = {'rule:': 'reproducible; wrong the same way every time',
            'claude': 'SELF-MARKED - the agent grading the instrument that judged it',
            'grok': 'self-marked'}
for src, n in collections.Counter(l.get('by') for l in labels).most_common():
    note = next((v for k, v in STRENGTH.items() if str(src).startswith(k)), 'independent')
    print(f'  {str(src):<30}{n:>5}   {note}')

fire_lab = {k: v for k, v in lab.items() if k in firekeys}
oc = collections.Counter(v.get('outcome') for v in fire_lab.values())
print(f'\n  of {len(fires)} fires: {len(fire_lab)} labelled '
      f'({len(fire_lab)/max(len(fires),1)*100:.1f}%), {len(fires)-len(fire_lab)} unlabelled')
for k in ('useful', 'false', 'unclear'):
    if oc[k]:
        print(f'    {k:<10}{oc[k]:>5}')
stray = len(labels) - len(fire_lab)
if stray > 0:
    print(f'  {stray} label(s) sit on readings that never fired - they say nothing about')
    print('  whether an interruption was warranted.')

print(f'\n{bar}\n  WHAT IT CAN ANSWER\n{bar}')
u, f = oc['useful'], oc['false']
if u + f:
    print(f'  precision   {u}/{u+f} = {u/(u+f)*100:.1f}%   (of fires with a CLEAR call)')
    print('              every one of those calls is rule-derived, not judged.')
    if u + f < 30:
        print(f'              {u+f} clear calls is an anecdote. Do not move a threshold on it.')
if oc['unclear']:
    print(f'  declined    {oc["unclear"]} fire(s) the rule could not call -')
    print('              68% of goal-drift fires are followed by another goal-drift, and the')
    print('              drifted goal never becomes the official ground. Those chains are')
    print('              sequential sub-goals with the parent never spelled, so nothing in')
    print('              the data separates working from wandering.')

print(f'\n{bar}\n  WHAT IT CANNOT ANSWER\n{bar}')
print('  d-prime     not computable, now or ever, from this corpus. Sensitivity needs')
print('              labels on the steps that did NOT fire, and review_verdicts offers')
print('              only fires. Half a detection matrix, said as half.')
par = [r for r in rows if isinstance(r.get('laserscore'), str) and '⊂' in r['laserscore']]
exc = sum(1 for r in rows if r.get('reason') == 'excursion')
print(f'  excursions  parent_goal spelled in {len(par)} of {len(rows)} readings '
      f'({len(par)/max(len(rows),1)*100:.1f}%); excursion verdicts: {exc}')
print('              the grammar has a slot for a legitimate sub-task and it goes unused,')
print('              which is why goal-drift dominates and why the rule declines so often.')
print('              A prospective fix, not a threshold one.')
print()
