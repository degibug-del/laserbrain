#!/usr/bin/env python3
"""test_observe.py — inferred state, and the properties that make it safe to attach.

The claim inference makes is narrow and has to stay narrow: Φ from inferred state is a
LOWER BOUND on Φ from spelled state. It may miss drift; it must never manufacture it.
Everything below is aimed at that one property, plus the theorem constraint that the
ground goal cannot move.
"""
from laserbrain import Harness, PUBLISHED, _displacement
from laserbrain.observe import Observer

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


G = 'ship the sky billboard'

# ── the ground goal cannot move ──────────────────────────────────────────────
o = Observer(G)
try:
    o.goal = 'something else'
    show('the ground goal is read-only', False, 'assignment succeeded')
except AttributeError:
    show('the ground goal is read-only', True, 'no setter — a reassignable reference is not a fixed one')
try:
    Observer('')
    show('an empty goal is refused', False)
except ValueError:
    show('an empty goal is refused', True)

# ── progress rules ───────────────────────────────────────────────────────────
o = Observer(G)
show('no events reads as advancing', o.progress() == 'advancing')

o = Observer(G)
for _ in range(3):
    o.record('Bash', {'command': 'npm run build'}, ok=True)
show('the same call three times reads as circling', o.progress() == 'circling', o.why())

o = Observer(G)
o.record('Bash', {'command': 'a'}); o.record('Bash', {'command': 'b'}); o.record('Bash', {'command': 'c'})
show('the same TOOL on different inputs is work, not repetition', o.progress() == 'advancing', o.why())

o = Observer(G)
o.record('Bash', {'command': 'x'}, ok=False); o.record('Bash', {'command': 'y'}, ok=False)
show('two consecutive failures read as stuck', o.progress() == 'stuck', o.why())

o = Observer(G)
o.record('Bash', {'command': 'x'}, ok=False); o.record('Bash', {'command': 'y'}, ok=True)
show('a failure followed by a success is not stuck', o.progress() == 'advancing', o.why())

# ── the lower-bound property, stated as arithmetic ───────────────────────────
ground = {'goal': G, 'dist': 5.0, 'progress': 'advancing'}
phi_known = _displacement(G, 'advancing', 0, ground)          # distance moved 5 -> 0
phi_unknown = _displacement(G, 'advancing', None, ground)     # distance not known
show('an unknown distance contributes 0, not a guess', phi_unknown == 0.0, f'Φ={phi_unknown}')
show('and is therefore <= the same state with distance known',
     phi_unknown <= phi_known, f'{phi_unknown} <= {phi_known}')
show('specifically it does not silently become the _asdist fallback of 5',
     phi_unknown != _displacement(G, 'advancing', 5, {'goal': G, 'dist': 0.0, 'progress': 'advancing'}))

# ── it still catches real drift, and marks itself ────────────────────────────
h = Harness()
h.check(**Observer(G).state())
drifted = Observer('refactor the parser and migrate the database')
v = h.check(**drifted.state())
show('a wholly different goal still reads as drift under inference',
     v.reason == 'goal-drift', f'reason={v.reason}')
show('an inferred verdict says so in its advice', '[inferred' in v.advice)

h2 = Harness()
v2 = h2.check(goal=G, progress='advancing', distance=5)
show('a spelled check is NOT tagged inferred', '[inferred' not in v2.advice)

# ── losing the stall detector is acknowledged, not hidden ────────────────────
h3 = Harness()
o3 = Observer(G)
h3.check(**o3.state())
last = None
for _ in range(8):
    last = h3.check(**o3.state())
show('without distances there is no stall verdict (the honest cost)',
     last.reason != 'stalled', f'reason={last.reason}')
show('and the verdict says the distance is unknown', 'distance unknown' in last.advice)

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
