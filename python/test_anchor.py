#!/usr/bin/env python3
"""How much of Φ rests on the agent's own account of itself.

laserbrain's claim is that it measures against a fixed external reference, which an agent
watching only itself provably cannot do. That is true of the goal term — the ground is
frozen at first call and cannot be revised mid-run. It is NOT true of the other two:
`distance` and `progress` are whatever the agent types. On the published calibration that
is 0.5 anchored and 0.5 introspection, and until 2026-07-27 nothing said so anywhere.

The test that matters is the first one below: an agent doing the work and an agent
inventing its numbers produce the SAME Φ. Φ cannot tell them apart and never could.
`anchored` is what does.
"""
import sys

from laserbrain import Harness

FAIL = []


def check(name, got, want):
    if got != want:
        FAIL.append(f'{name}: got {got!r}, want {want!r}')
    print(f"  {'ok  ' if got == want else 'FAIL'} {name:46} {got}")


def run(n=5, evidence=None):
    h = Harness()
    v = None
    for d in range(n, 0, -1):
        for kind, name, ok in (evidence or []):
            h.saw(kind, name, ok=ok)
        v = h.check(goal='ship the page', progress='advancing', distance=d)
    return h, v


# ── the point ────────────────────────────────────────────────────────────────────
print('an honest run and a fabricated one, side by side')
h_none, v_none = run()
h_work, v_work = run(evidence=[('tool', 'pytest', True), ('edit', 'page.tsx', None)])

# THE finding: identical Φ. The instrument cannot separate them on Φ alone, because both
# agents typed the same numbers and only one of them did anything.
check('same Φ whether or not work happened', v_none.phi == v_work.phi, True)
check('fabricated run is half-anchored', v_none.anchored, 0.5)
check('corroborated run is fully anchored', v_work.anchored, 1.0)
check('run corroboration, fabricated', h_none.corroboration(), 0.0)
check('run corroboration, real', h_work.corroboration(), 1.0)

# ── what counts as corroboration ─────────────────────────────────────────────────
print('\nwhat backs a self-report')
# Work that RAN AND FAILED does not corroborate a claim of advancing: something happened,
# but not the thing being claimed. That is `unrun`/`unfalsified` reasoning from catches.py
# turned on the harness's own inputs.
check('failing work does not corroborate', run(3, [('check', 'tests', False)])[1].anchored, 0.5)
check('mixed, with a success, does',
      run(3, [('check', 'tests', False), ('tool', 'build', True)])[1].anchored, 1.0)

# Evidence is per-interval, not per-run — cleared at each check, so one burst of work
# cannot vouch for every later step.
h = Harness()
h.saw('tool', 'pytest', ok=True)
first = h.check(goal='ship the page', progress='advancing', distance=5)
second = h.check(goal='ship the page', progress='advancing', distance=4)
check('evidence does not carry over', (first.anchored, second.anchored), (1.0, 0.5))

# ── it must not disturb anything ─────────────────────────────────────────────────
print('\nΦ and the verdicts are untouched')
# `anchored` is REPORTED, never folded into Φ. Reweighting would move the published
# instrument and invalidate every calibration and drift vector, and there is no data yet
# behind any particular new weight.
check('Φ unchanged by evidence', run(evidence=[('tool', 'x', True)])[1].phi, run()[1].phi)
check('verdict unchanged by evidence', run(evidence=[('tool', 'x', True)])[1].reason, run()[1].reason)
check('why is still a string', isinstance(run()[1].why, str), True)
check('laserscore still rendered', run()[1].laserscore is not None, True)
# Positional construction: `anchored` had to go LAST in the dataclass, or `why` lands in
# it on all six Verdict(...) call sites — which is exactly what the first attempt did.
check('field order holds', isinstance(run()[1].why, str), True)

print()
if FAIL:
    print(f'{len(FAIL)} FAILED')
    for f in FAIL:
        print('   ', f)
    sys.exit(1)
print('all pass')
