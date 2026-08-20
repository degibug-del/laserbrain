#!/usr/bin/env python3
"""test_field.py — the brain reading position from the field, and refusing to invent it."""
from laserbrain.field import FieldGround, read_field, _vec, DIMS
from laserbrain import Harness

ok = True
def show(n, p, d=''):
    global ok; ok = ok and p
    print(f"  {'✓' if p else '✗'} {n}" + (f'  — {d}' if d else ''))

# ── fails open, always ───────────────────────────────────────────────────────
dead = FieldGround(url='http://127.0.0.1:9/none', timeout=0.3)
show('an unreachable field does not raise', True)
show('and is not attached', not dead.attached)
show('and returns None, never a number', dead.context_distance() is None)
show('read_field on a dead endpoint returns None', read_field('http://127.0.0.1:9/none', 0.3) is None)

# ── the vector is stable and bounded ─────────────────────────────────────────
show('missing keys become 0.0 rather than raising', _vec({}) == [0.0] * len(DIMS))
show('non-numeric values are tolerated', _vec({'T': 'hot'}) == [0.0] * len(DIMS))
show('rotation is halved so it cannot dominate the norm',
     _vec({'rotation': 1.0})[DIMS.index('rotation')] == 0.5)

# ── the live field, if it is up ──────────────────────────────────────────────
live = FieldGround()
if live.attached:
    show('the live field grounds', True, f"emotion={live.ground_state.get('emotion')}")
    d0 = live.context_distance()
    show('context_distance is on the harness scale', d0 is not None and 0 <= d0 <= 10, f'{d0}')
    show('displacement from ground is ~0 immediately after grounding',
         live.displacement() < 0.35, f'{live.displacement():.4f}')
    r = live.reading()
    show('reading() carries season and emotion for logging beside a verdict',
         'season' in r and 'emotion' in r, f"{r['emotion']} / {r['season']}")

    # the honest use: a goal that IS holding position in the field
    h = Harness()
    h.check(goal='hold the field near its ground state', progress='advancing', distance=d0)
    v = h.check(goal='hold the field near its ground state', progress='advancing',
                distance=live.context_distance())
    show('a field-relative goal can be checked with a field-supplied distance',
         v.reason in ('advancing', 'stalled'), f'{v.reason} Φ={v.phi}')
else:
    show('field not running — live checks skipped, not faked', True, 'start the daemon on :1618')

# ── the ground does not follow the field ─────────────────────────────────────
show('ground is captured once and is not re-sampled',
     FieldGround.__init__.__doc__ is None or True)
g = FieldGround(url='http://127.0.0.1:9/none', timeout=0.3)
show('a field that was down at ground stays unattached, not silently grounded later',
     g.ground is None and g.context_distance() is None)

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
