#!/usr/bin/env python3
"""Bugfinder across agents — and the rule that it must never repeat per-agent Bugfinder.

The first version of fleet_catches ran three of the six catch signatures over the pooled
event log and reported the results. A test showed two of the three were duplicates: the
per-agent `unfalsified` and `unrun` had already fired on the same evidence, so the
supervisor was announcing what everyone already knew. A finding that is already in
findings() is noise, and noise in a monitor is how monitors get switched off.

So a fleet catch has to earn its place by CHANGING the per-agent answer — in either
direction. More evidence can exonerate as readily as it accuses, and an instrument that
can only add accusations is not measuring, it is prosecuting.
"""
import sys

from laserbrain import Supercode
from laserbrain.catches import Event, catches

FAIL = []


def check(name, got, want):
    if got != want:
        FAIL.append(f'{name}: got {got!r}, want {want!r}')
    print(f"  {'ok  ' if got == want else 'FAIL'} {name:52} {got}")


def sigs(sc):
    return sorted(f['signature'] for f in sc.fleet_catches())


def base(agents=(('a', 'write the parser'), ('b', 'tune the cache'))):
    sc = Supercode()
    for n, g in agents:
        sc.observe(n, goal=g, progress='advancing', distance=4)
    return sc


# ── blind_fleet: genuinely unreachable from inside one agent ─────────────────────
print('one tool, identical answer, different work')
sc = base()
for n in ('a', 'b'):
    sc.saw(n, Event(kind='tool', name='search_index', result=[]))
# instrument_blind cannot fire per-agent here: each agent called it once, so there is no
# repetition to see. The fleet knows the inputs differed, which is the stronger claim.
check('no per-agent catch', [c.signature for a in ('a', 'b') for c in catches(sc.agents[a].events)], [])
check('fleet sees it', 'blind_fleet' in sigs(sc), True)

# One agent alone can never produce it.
sc = base()
for _ in range(3):
    sc.saw('a', Event(kind='tool', name='search_index', result=[]))
check('one agent cannot trigger blind_fleet', 'blind_fleet' in sigs(sc), False)

# ── unrun_cleared: the fleet exonerating a per-agent catch ───────────────────────
print('\na claim its own agent never ran, that another agent did')
sc = base()
sc.saw('a', Event(kind='claim', name='parser_speed', text='3x faster now'))
sc.saw('b', Event(kind='tool', name='parser_speed', result='ok', ok=True))
check('per-agent flags the claimant', 'unrun' in {c.signature for c in catches(sc.agents['a'].events)}, True)
check('the fleet clears it', 'unrun_cleared' in sigs(sc), True)

# Nobody ran it: per-agent unrun already says so, and the fleet adds nothing.
sc = base()
sc.saw('a', Event(kind='claim', name='parser_speed', text='3x faster now'))
check('nobody ran it — no fleet finding to add', sigs(sc), [])
check('because per-agent already has it', 'unrun' in {c.signature for c in catches(sc.agents['a'].events)}, True)

# ── thin_evidence: only when nobody could conclude alone ─────────────────────────
print('\na check green everywhere, thin for each agent')
sc = base((('a', 'x'), ('b', 'y'), ('c', 'z')))
for n in ('a', 'b', 'c'):
    sc.saw(n, Event(kind='check', name='lint', ok=True))
per = {s for n in ('a', 'b', 'c') for s in {c.signature for c in catches(sc.agents[n].events)}}
if 'unfalsified' not in per:
    check('fleet notices what no agent could', 'thin_evidence' in sigs(sc), True)
else:
    # Per-agent already fired, so the fleet must stay quiet rather than repeat it.
    check('suppressed when per-agent already fired', 'thin_evidence' in sigs(sc), False)

# A red anywhere is a check that can fail, which is the whole point of having one.
sc = base((('a', 'x'), ('b', 'y'), ('c', 'z')))
for n in ('a', 'b'):
    sc.saw(n, Event(kind='check', name='lint', ok=True))
sc.saw('c', Event(kind='check', name='lint', ok=False))
check('one red clears it', 'thin_evidence' in sigs(sc), False)

# ── the standing rule ────────────────────────────────────────────────────────────
print('\nit never repeats findings()')
sc = base()
sc.saw('a', Event(kind='claim', name='parser_speed', text='fast'))
for n in ('a', 'b'):
    sc.saw(n, Event(kind='tool', name='search_index', result=[]))
per_sigs = {c.signature for n in ('a', 'b') for c in catches(sc.agents[n].events)}
fleet_subjects = {f['signature'] for f in sc.fleet_catches()}
# The fleet may CLEAR a per-agent signature, but must never re-assert one.
check('no fleet catch re-asserts a per-agent signature',
      bool(fleet_subjects & per_sigs), False)
check('empty fleet on empty evidence', Supercode().fleet_catches(), [])

print()
if FAIL:
    print(f'{len(FAIL)} FAILED')
    for f in FAIL:
        print('   ', f)
    sys.exit(1)
print('all pass')
