#!/usr/bin/env python3
"""The check-in scheduler: it must schedule, and it must refuse to invent.

WHY A SCHEDULER AND NOT A BETTER DETECTOR

Precision on clearly-labelled fires is 14.6%, on 7 useful labels against 41 false. The
per-step question is contested. The per-clock question is not: drift climbs monotonically
with time since the user last spoke, several sigma between the two best-powered bands, and
answering it requires judging no individual step at all — only a timestamp.

So everything here is about a clock, and the sharpest test in this file is the one that
checks no verdict is consulted anywhere.

WHAT IT MUST REFUSE

An underpowered band carries rate: null. The temptation is to borrow the neighbouring
band's number so the API always returns something. That would be the same defect as
reporting a 0.0% hit rate from a contaminated sample: a figure that looks like a
measurement and is a guess. Every function propagates the null instead.
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'laserbrain-sdk'))

from laserbrain import attention as A                          # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


class with_bands:
    """Swap the loaded calibration for a synthetic one; restore on exit."""

    def __init__(self, bands):
        self.bands = bands

    def __enter__(self):
        self.old = A.BANDS
        A.BANDS = self.bands
        return A

    def __exit__(self, *a):
        A.BANDS = self.old


SYNTH = [
    {'label': 'under a minute', 'from_seconds': 0, 'to_seconds': 60,
     'drift': 0, 'n': 100, 'rate': 0.0, 'underpowered': False},
    {'label': '1-5 minutes', 'from_seconds': 60, 'to_seconds': 300,
     'drift': 20, 'n': 100, 'rate': 0.20, 'underpowered': False},
    {'label': '5-30 minutes', 'from_seconds': 300, 'to_seconds': 1800,
     'drift': 40, 'n': 100, 'rate': 0.40, 'underpowered': False},
    {'label': 'over 30 minutes', 'from_seconds': 1800, 'to_seconds': None,
     'drift': 5, 'n': 6, 'rate': None, 'underpowered': True},
]

print('a time lands in the band that contains it')
with with_bands(SYNTH):
    for secs, want in ((0, 'under a minute'), (59, 'under a minute'), (60, '1-5 minutes'),
                       (299, '1-5 minutes'), (300, '5-30 minutes'), (1799, '5-30 minutes'),
                       (1800, 'over 30 minutes'), (99999, 'over 30 minutes')):
        check(f'{secs:>5}s -> {want}', A.risk(secs)['band'] == want, A.risk(secs)['band'])
    check('a negative time is clamped, not crashed', A.risk(-5)['band'] == 'under a minute')

print()
print('an UNDERPOWERED band refuses to quote a rate')
with with_bands(SYNTH):
    r = A.risk(3600)
    check('rate is None', r['rate'] is None, str(r['rate']))
    check('  and known is False', r['known'] is False)
    check("  and it does not borrow the neighbour's 0.40", r['rate'] != 0.40)
    check('  the sample size is still reported', r['n'] == 6, str(r['n']))
    check('  advise() says so rather than guessing',
          'Too few' in A.advise(3600), A.advise(3600)[:70])

print()
print('next_check_in names the edge where the measured rate changes')
with with_bands(SYNTH):
    check('from 0 at 25% tolerance -> the 5-30 edge, 300s',
          A.next_check_in(0, 0.25) == 300.0, str(A.next_check_in(0, 0.25)))
    check('from 0 at 10% -> the 1-5 edge, 60s',
          A.next_check_in(0, 0.10) == 60.0, str(A.next_check_in(0, 0.10)))
    check('from 120s at 25% -> 180s remain to the 300s edge',
          A.next_check_in(120, 0.25) == 180.0, str(A.next_check_in(120, 0.25)))
    check('already past tolerance -> 0, look now',
          A.next_check_in(600, 0.25) == 0.0, str(A.next_check_in(600, 0.25)))
    check('no measured band crosses 90% -> None, not a fabricated time',
          A.next_check_in(0, 0.90) is None, str(A.next_check_in(0, 0.90)))

print()
print('an underpowered band can never BE the answer')
# In the real table the 86% band is the most alarming number and the thinnest. If a
# tolerance between 0.40 and 0.86 returned "look in 30 minutes", the schedule would be
# resting on a handful of readings while sounding certain.
with with_bands(SYNTH):
    check('a tolerance only the null band could satisfy returns None',
          A.next_check_in(0, 0.60) is None, str(A.next_check_in(0, 0.60)))

print()
print('with NO calibration at all it says so, and does not throw')
with with_bands([]):
    check('risk is unknown', A.risk(100)['known'] is False)
    check('next_check_in is None', A.next_check_in(0, 0.25) is None)
    check('advise names the fix', 'calibrate_attention' in A.advise(100), A.advise(100)[:60])

print()
print('the sample size travels with every rate it quotes')
# "40% of readings drift" and "40 of 100" are different claims, and only the second can be
# argued with.
with with_bands(SYNTH):
    msg = A.advise(600)
    check('advise() carries drift and n', '40 of 100' in msg, msg[:80])
    check('  and the percentage', '40%' in msg, msg[:80])

print()
print('NO VERDICT IS CONSULTED — the property that makes this independent')
# Tested by SIGNATURE and IMPORT, not by grepping for words. A first version searched the
# source for 'goal-drift' and failed on advise()'s own sentence — "40 of 100 readings were
# goal-drift" — which is the module NAMING what the rate measures, in prose, for a human.
# Grepping output strings tests the wording; what matters is what the code can read.
import inspect                                                 # noqa: E402

src = pathlib.Path(A.__file__).read_text()
check('it imports nothing from the detector',
      'from .runtime' not in src and 'import runtime' not in src)
for fn in (A.risk, A.next_check_in, A.advise):
    params = list(inspect.signature(fn).parameters)
    ok = all(p in ('seconds', 'elapsed', 'tolerance') for p in params)
    check(f'{fn.__name__}() takes only a clock and a tolerance', ok, str(params))
# And behaviourally: the answer depends on the number passed and nothing else. Two calls
# with the same elapsed time must agree no matter what the agent has been doing.
with with_bands(SYNTH):
    check('the same elapsed time always gives the same answer',
          A.risk(600) == A.risk(600.0) == A.risk(600.4))

print()
print('THE SHIPPED TABLE — sanity, not a re-derivation')
real = A.table()
bands = real.get('bands') or []
if not bands:
    check('a calibration is shipped', False, 'attention.json missing from the package')
else:
    powered = [b for b in bands if b.get('rate') is not None]
    rates = [b['rate'] for b in powered]
    check(f'{len(bands)} bands, {len(powered)} powered', len(powered) >= 2, str(len(powered)))
    check('the measured rate is non-decreasing with time', rates == sorted(rates),
          str(rates))
    check('it carries its own provenance', bool(real.get('provenance', {}).get('corpus_to')))
    check('  and states the single-agent caveat',
          'agent' in str(real.get('provenance', {}).get('caveat', '')))
    check('it is not marked immutable — it is meant to be recomputed',
          real.get('immutable') is False)

print()
print('the calibrator refuses to go stale silently')
cal = HERE / 'calibrate_attention.py'
src_json = HERE / 'attention.json'
if not (cal.exists() and src_json.exists()):
    check('calibrate_attention.py and attention.json present', False)
else:
    p = subprocess.run([sys.executable, str(cal), '--check'], cwd=HERE,
                       capture_output=True, text=True, timeout=900)
    check('--check passes against the live corpus', p.returncode == 0,
          (p.stdout + p.stderr).strip()[:70])
    saved = src_json.read_text()
    try:
        doctored = json.loads(saved)
        # The rate, not the count: --check asks whether the table still DESCRIBES the
        # corpus, and 19% -> 90% is a table that does not.
        doctored['bands'][1]['rate'] = 0.90
        src_json.write_text(json.dumps(doctored, indent=2) + '\n')
        q = subprocess.run([sys.executable, str(cal), '--check'], cwd=HERE,
                           capture_output=True, text=True, timeout=900)
        check('  and fails on a doctored table', q.returncode == 1, f'rc={q.returncode}')
        check('  saying which command fixes it', 'calibrate_attention.py' in q.stdout,
              q.stdout.strip()[:60])
    finally:
        src_json.write_text(saved)
    r = subprocess.run([sys.executable, str(cal), '--check'], cwd=HERE,
                       capture_output=True, text=True, timeout=900)
    check('  and the file is restored', r.returncode == 0, r.stdout.strip()[:50])

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    sys.exit(1)
print('  PASS — it schedules from a clock, and says "unknown" where it was never measured.')
