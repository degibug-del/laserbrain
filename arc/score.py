#!/usr/bin/env python3
"""Score every agent trace: how many steps earlier did the union see the waste?

    python3 score.py

THE METRIC, and it took a whole evening to find the right one.

Three wrong ones were tried first. "Was the verdict true afterwards" — did the agent reach
any new state after a fire — gave 0 of 1,070 on a random walker and 0 of 4 on a reasoning
one, because a real agent almost always eventually finds something new. That criterion
grades a referee on whether the team scored later.

The right question is the one ARC-AGI-3 itself scores: ACTION WASTE. Specifically —

    when a run enters a stretch of going nowhere, who notices first,
    the agent or the instrument, and by how many steps?

Steps of lead is not a proxy for action efficiency. It is action efficiency.

WHY THE UNION AND NOT EITHER ALONE. On the first measured trace the agent's own reports
flagged trouble at steps 8, 12 and 21; the instrument flagged 11 and 18. Neither set
contains the other. The agent is smarter — it sees what no rule anticipates. The instrument
is more precise — it applies one rule identically and does not flatter itself, which is how
it caught 11 and 18 while the agent was still writing `advancing`. Precision catches what
intelligence rationalises away; intelligence catches what precision has no rule for.

WHAT MAKES THESE TRACES WORTH SCORING. They come from agents that were told to play a game
and report honestly, and were told NOTHING about laserbrain, about this metric, or that
their self-report was being compared to anything. An agent that knows its `advancing` is
the thing being counted cannot produce a naive one. That is why these runs are not played
by the author.
"""
import json
import os
import pathlib
import statistics
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
os.environ.setdefault('LASERBRAIN_HOME', tempfile.mkdtemp(prefix='lb-score-'))
sys.path.insert(0, str(HERE.parent.parent / 'laserbrain-sdk'))

from laserbrain import fires_first                                 # noqa: E402

rows = []
for f in sorted((HERE / 'runs').glob('session-agent-*.json')):
    d = json.loads(f.read_text())
    tr = d.get('trace') or []
    if len(tr) < 5:
        print(f'  skip {f.stem}: only {len(tr)} step(s)')
        continue
    ep = fires_first(tr)
    inst = [e for e in ep if e['first'] == 'instrument']
    own = [e for e in ep if e['first'] == 'agent']
    both = [e for e in ep if e['first'] == 'both']
    # NEVER NOTICING IS THE LARGEST LEAD, NOT THE SMALLEST.
    #
    # `lead` is None when no agent call follows an instrument call — and the first real run
    # to come back was exactly that case: 39 steps, `advancing` logged on every single one,
    # the agent never once saying stuck or circling while laserbrain read `stalled` twelve
    # times. Summing only the non-None leads scores that as 0, which reads as "the
    # instrument added nothing" when what happened is the opposite: it was the only thing
    # in the run that noticed.
    #
    # So an unanswered fire is credited to the end of the run. That is what it cost: the
    # agent went the whole way without ever calling it.
    # THE UNION OF STEPS, not the sum of intervals. Summing gave ls20 a lead of 124% of
    # its own run: three unanswered fires at steps 5, 10 and 15 each credited to the end
    # count the same later steps three times. A share of a run cannot exceed the run, and a
    # metric that reports 124% is telling you it is adding the wrong things.
    #
    # What is actually being measured is: on how many steps was the instrument flagging a
    # stall that the agent had not called? Mark those steps, then count them once.
    covered = set()
    for e in inst:
        end = e['step'] + e['lead'] if e['lead'] is not None else len(tr)
        covered.update(range(e['step'], end))
    lead = len(covered)
    unanswered = sum(1 for e in inst if e['lead'] is None)
    rows.append({'game': d.get('game'), 'steps': len(tr), 'levels': d.get('levels', 0),
                 'episodes': len(ep), 'instrument_first': len(inst), 'agent_first': len(own),
                 'both': len(both), 'lead': lead, 'unanswered': unanswered,
                 'pct': 100 * lead / len(tr) if tr else 0})

if not rows:
    print('\n  no agent traces yet — the wave is still playing\n')
    raise SystemExit(0)

print(f'\n  {len(rows)} run(s), {sum(r["steps"] for r in rows)} steps, '
      f'{sum(r["levels"] for r in rows)} level(s) completed\n')
print(f'  {"game":18} {"steps":>5} {"episodes":>9} {"inst 1st":>9} {"agent 1st":>10} {"lead":>5} {"%":>6}')
for r in rows:
    print(f'  {str(r["game"])[:18]:18} {r["steps"]:5} {r["episodes"]:9} {r["instrument_first"]:9} '
          f'{r["agent_first"]:10} {r["lead"]:5} {r["pct"]:5.0f}%')

leads = [r['lead'] for r in rows]
pcts = [r['pct'] for r in rows]
tot_ep = sum(r['episodes'] for r in rows)
tot_own = sum(r['agent_first'] for r in rows)
tot_inst = sum(r['instrument_first'] for r in rows)

print()
print(f'  episodes: {tot_ep} union   {tot_own} agent-first   {tot_inst} instrument-first')
un = sum(r['unanswered'] for r in rows)
if un:
    print(f'  of those, {un} the agent NEVER called at all — credited to end of run')
print(f'  steps of lead: total {sum(leads)}   mean {statistics.mean(leads):.1f} per run')
if len(leads) > 1:
    sd = statistics.stdev(leads)
    se = sd / len(leads) ** 0.5
    print(f'                 sd {sd:.1f}   95% CI {statistics.mean(leads) - 1.96 * se:.1f}'
          f' to {statistics.mean(leads) + 1.96 * se:.1f}')
print(f'  as a share of the run: mean {statistics.mean(pcts):.1f}%')
print()
if tot_inst == 0:
    print('  THE INSTRUMENT NEVER CALLED ONE FIRST. On these runs it added nothing the')
    print('  agents had not already said, and the honest report is that number, not a story.')
else:
    print(f'  The instrument caught {tot_inst} episode(s) the agents had not yet called,')
    print(f'  worth {sum(leads)} step(s) of earlier warning across {sum(r["steps"] for r in rows)} steps.')
