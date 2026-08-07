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
import os
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
print("THE AGENT'S OWN CLOCK — measured, and reported with its censoring")
# The contrast is the finding. The external clock (time since a person spoke) is strong;
# the internal one (steps since the agent's own check) is flat AND censored by the gate
# that produced it, because the gate forces a check at 4 steps. A flat line through a
# censored sample is a fact about the censoring, not about the interval.
ag = A.AGENT
if not ag.get('bands'):
    check('an agent_clock block is present', False, 'missing from attention.json')
else:
    cut = ag.get('censored_beyond_steps')
    check('it names where the sample stops being about agents', isinstance(cut, int), str(cut))
    check('  and says why in words', 'gate' in str(ag.get('censoring', '')).lower())
    check('  and reports the share it lost', isinstance(ag.get('censored_share'), float),
          str(ag.get('censored_share')))
    inside = A.agent_risk(max(1, cut - 2))
    beyond = A.agent_risk(cut + 4)
    check('inside the permitted range it answers', inside['known'] is True,
          f"{inside['band']} {inside['rate']}")
    check('  and is not marked censored', inside['censored'] is False)
    check('past the gate it refuses', beyond['known'] is False, str(beyond))
    check('  and says it is censored, not merely thin', beyond['censored'] is True)
    check('  quoting no rate there', beyond['rate'] is None, str(beyond['rate']))
    # The absent function is deliberate: there is no agent_next_check_in, because a
    # schedule built on a censored sample would dress a policy as a measurement.
    check('there is no agent schedule to mistake for a measurement',
          not hasattr(A, 'agent_next_check_in'))

print()
print('the calibrator refuses to go stale silently')
# THE LIVE CORPUS, on purpose — the same exemption test_corpus_clean takes and for the same
# reason. attention.json is calibrated FROM the accumulated drift log, so "does the table
# still describe the corpus" is a question about the real file. run-tests.sh exports
# LASERBRAIN_HOME so no suite can write to it; honouring that here would point --check at an
# empty temp directory, where it reports "no corpus" and the assertion means nothing.
#
# Reading it is safe in a way writing never was: --check computes and compares, it does not
# append.
_LIVE_ENV = {k: v for k, v in os.environ.items()
             if k not in ('LASERBRAIN_HOME', 'LASERBRAIN_STATE_DIR', 'LASERBRAIN_DRIFT_LOG')}
cal = HERE / 'calibrate_attention.py'
src_json = HERE / 'attention.json'
if not (cal.exists() and src_json.exists()):
    check('calibrate_attention.py and attention.json present', False)
else:
    p = subprocess.run([sys.executable, str(cal), '--check'], cwd=HERE,
                       env=_LIVE_ENV, capture_output=True, text=True, timeout=900)
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
                           env=_LIVE_ENV, capture_output=True, text=True, timeout=900)
        check('  and fails on a doctored table', q.returncode == 1, f'rc={q.returncode}')
        check('  saying which command fixes it', 'calibrate_attention.py' in q.stdout,
              q.stdout.strip()[:60])
    finally:
        src_json.write_text(saved)
    r = subprocess.run([sys.executable, str(cal), '--check'], cwd=HERE,
                       env=_LIVE_ENV, capture_output=True, text=True, timeout=900)
    check('  and the file is restored', r.returncode == 0, r.stdout.strip()[:50])


# ══════════════════════════════════════════════════════════════════════════════════════
# THE PACKAGED COPY MUST NOT DRIFT FROM THE CALIBRATED ONE
#
# attention.json exists twice: lasermind/ holds the calibrated table, and
# laserbrain-sdk/laserbrain/ holds package data that ships inside the wheel — the table
# every pip-installed agent actually schedules against.
#
# calibrate_attention.py wrote only the first. On 2026-08-04 a recalibration moved the
# rates, the two had been byte-identical minutes earlier, and the split was noticed by
# hand. Nothing would have reported it: a stale data file raises no error, it answers an
# old question confidently. The next release would have shipped a table its own corpus had
# already outgrown.
#
# Byte-identical, not "within tolerance" — these are not two measurements that ought to
# agree, they are one artifact stored twice.
# ══════════════════════════════════════════════════════════════════════════════════════
import json as _json                                             # noqa: E402
import pathlib as _pl                                            # noqa: E402
import shutil as _sh                                             # noqa: E402
import subprocess as _sp                                         # noqa: E402
import sys as _sys                                               # noqa: E402

_HERE = _pl.Path(__file__).resolve().parent
_CAL = _HERE / 'calibrate_attention.py'
_OUT = _HERE / 'attention.json'
_SHIPPED = _HERE.parent / 'laserbrain-sdk' / 'laserbrain' / 'attention.json'

print()
print('the packaged copy is held to the calibrated one')

if not _SHIPPED.parent.exists():
    print('  skip  no SDK checkout on this machine')
else:
    # BOTH files are backed up, not just the shipped one. This block invokes the REAL
    # calibrator, which writes attention.json as well — so a first version of this test
    # rewrote the calibrated table as a side effect and the suite failed on its second run
    # with three assertions from the section ABOVE it. A test that mutates the artifact it
    # is testing is not a test, it is a migration with assertions attached.
    _bak = _SHIPPED.read_text()
    _bak_out = _OUT.read_text()
    try:
        check('the two copies are identical to begin with', _OUT.read_text() == _bak)

        # Doctor the SHIPPED copy only — the precise failure that occurred.
        _d = _json.loads(_bak)
        _d['bands'][1]['rate'] = 0.999
        _SHIPPED.write_text(_json.dumps(_d, indent=2) + '\n')
        _rc = _sp.run([_sys.executable, str(_CAL), '--check'],
                      env=_LIVE_ENV, capture_output=True, text=True, cwd=_HERE)
        check('a diverged package copy FAILS the check', _rc.returncode != 0,
             f'exit {_rc.returncode}')
        check('  and the message names the divergence', 'DIVERGED' in _rc.stdout,
             _rc.stdout.strip().splitlines()[-1][:60] if _rc.stdout.strip() else '(no output)')

        # And a plain run repairs it, rather than leaving a human to copy the file.
        _sp.run([_sys.executable, str(_CAL)], env=_LIVE_ENV, capture_output=True,
                text=True, cwd=_HERE)
        check('a plain run rewrites BOTH copies', _SHIPPED.read_text() == _OUT.read_text())
        _rc2 = _sp.run([_sys.executable, str(_CAL), '--check'],
                       env=_LIVE_ENV, capture_output=True, text=True, cwd=_HERE)
        check('  and the check passes again', _rc2.returncode == 0, f'exit {_rc2.returncode}')
    finally:
        _SHIPPED.write_text(_bak)
        _OUT.write_text(_bak_out)

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    sys.exit(1)
print('  PASS — it schedules from a clock, and says "unknown" where it was never measured.')
