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
# The SDK is python/ in this repo and laserbrain-sdk/ in the working tree. Naming only the
# latter made this a no-op on a missing directory, so `from laserbrain import attention`
# bound to whatever site-packages held — the PUBLISHED build — and the suite tested the
# wheel while reporting on the working tree.
sys.path.insert(0, str(next((c for c in (HERE.parent / 'python',
                                         HERE.parent / 'laserbrain-sdk')
                             if (c / 'laserbrain' / '__init__.py').exists()),
                            HERE.parent / 'python')))

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
# still describe the corpus" is a question about the real file. tests/test_suites.py gives
# every suite a private LASERBRAIN_HOME so no suite can write to it; honouring that here
# would point --check at an empty temp directory, where it reports "no corpus" and the
# assertion means nothing. (This said "run-tests.sh" until 2026-08-21 — a file that did not
# exist, naming isolation nothing was providing. The runner provides it now, so the sentence
# is true for the first time; stripping the vars here was already correct.)
#
# Reading it is safe in a way writing never was: --check computes and compares, it does not
# append.
_LIVE_ENV = {k: v for k, v in os.environ.items()
             if k not in ('LASERBRAIN_HOME', 'LASERBRAIN_STATE_DIR', 'LASERBRAIN_DRIFT_LOG')}
cal = HERE / 'calibrate_attention.py'
src_json = next((c for c in (HERE.parent / 'json' / 'attention.json',
                             HERE / 'attention.json') if c.exists()),
                HERE.parent / 'json' / 'attention.json')
class _SkipCorpus(Exception):
    pass


def _no_corpus(r):
    """--check cannot judge staleness where no drift log exists.

    Added 2026-08-21, when this suite was first collected by a runner. Without it every
    corpus-dependent check below FAILS on any machine that has the repo and not the
    author's drift log — CI most of all — which would have made a green build impossible
    for a reason that says nothing about the code. A missing corpus is a skip; a stale
    table is a failure. They are different facts and were being reported as one."""
    # THE EXIT CODE, not the wording. This matched the substring 'no corpus' in the
    # calibrator's output, which was correct only by accident of phrasing: any future
    # message containing those words on some other failure path would have converted a real
    # failure into a silent skip — the exact defect this session spent its length removing.
    # calibrate_attention.py returns 77 under --check when the corpus is absent.
    return r.returncode == 77


# Bound BEFORE the branch, and True. Without this it is unbound whenever the calibrator or
# the table is missing, and the round-trip block below raises NameError — which exits
# non-zero, so no false green, but the traceback replaces the assertion summary and the
# remaining checks never run. True is the right default: with no calibrator present there is
# no round-trip to make, and False would shell out to a script that is not there and read
# python's "can't open file" status as a passing assertion.
_skip_corpus = True

if not (cal.exists() and src_json.exists()):
    check('calibrate_attention.py and attention.json present', False)
else:
    p = subprocess.run([sys.executable, str(cal), '--check'], cwd=HERE,
                       env=_LIVE_ENV, capture_output=True, text=True, timeout=900)
    if _no_corpus(p):
        print('  skip  --check against the live corpus   no drift log on this machine')
        _skip_corpus = True
    else:
        _skip_corpus = False
        check('--check passes against the live corpus', p.returncode == 0,
              (p.stdout + p.stderr).strip()[:70])
    saved = src_json.read_text()
    try:
        if _skip_corpus:
            raise _SkipCorpus
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
    except _SkipCorpus:
        pass
    finally:
        # Restores unconditionally, skip or not: the doctored write may already have
        # landed, and this is a real file in the repo.
        src_json.write_text(saved)
    if not _skip_corpus:
        r = subprocess.run([sys.executable, str(cal), '--check'], cwd=HERE,
                           env=_LIVE_ENV, capture_output=True, text=True, timeout=900)
        check('  and the file is restored', r.returncode == 0, r.stdout.strip()[:50])


# ══════════════════════════════════════════════════════════════════════════════════════
# THE PACKAGED COPY MUST NOT DRIFT FROM THE CALIBRATED ONE
#
# attention.json exists twice: json/ holds the calibrated table, and
# python/laserbrain/ holds package data that ships inside the wheel — the table every
# pip-installed agent actually schedules against. (Those were lasermind/ and
# laserbrain-sdk/ before the reorg; the constants below named the old ones until
# 2026-08-21, so _SHIPPED.parent did not exist, this whole block printed "no SDK checkout
# on this machine", and the drift it guards went unreported for five days.)
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
_OUT = next((c for c in (_HERE.parent / 'json' / 'attention.json',
                         _HERE / 'attention.json') if c.exists()),
            _HERE.parent / 'json' / 'attention.json')
_SHIPPED = next((c for c in (_HERE.parent / 'python' / 'laserbrain' / 'attention.json',
                             _HERE.parent / 'laserbrain-sdk' / 'laserbrain' / 'attention.json')
                 if c.parent.exists()),
                _HERE.parent / 'python' / 'laserbrain' / 'attention.json')

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
    # ON DISK TOO, BEFORE ANY WRITE. `_bak`/`_bak_out` alone are process memory: kill the
    # suite between the doctoring write and the finally and the repo is left holding test
    # fixture values in two real files, with no record of what they were. Worse, two
    # concurrent runs corrupt each other — B reads A's doctored file as its own backup and
    # writes that back. The sidecars survive the first; refusing to start when one already
    # exists closes the second.
    _sides = [(_SHIPPED, _SHIPPED.with_suffix('.json.testbak')),
              (_OUT, _OUT.with_suffix('.json.testbak'))]
    _stale = [b for _, b in _sides if b.exists()]
    if _stale:
        check('no stale test backup is present', False,
              f'{_stale[0]} exists — another run is in flight, or one died mid-write. '
              f'Restore it by hand before rerunning.')
        raise SystemExit(1)
    for _live, _side in _sides:
        _side.write_text(_live.read_text())
    try:
        check('the two copies are identical to begin with', _OUT.read_text() == _bak)

        # Everything past this point drives the REAL calibrator, which needs the drift
        # log. No corpus is a skip, not a failure — see _no_corpus above. The identity
        # check before it is a plain file comparison and runs anywhere, which is the one
        # that matters here: it is the drift guard itself.
        if _skip_corpus:
            raise _SkipCorpus

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

        # THE GUARD FIRST, because it is the thing that would silently stop the repair.
        # calibrate_attention.py refuses to write an agent_clock with drift 0 in every band
        # over a live one — the blind-arm signature. On a machine recording verdicts this
        # passes straight through; on a blind one it refuses, and either way the refusal
        # must be observable rather than mistaken for a failed repair.
        _g = _sp.run([_sys.executable, str(_CAL), '--ship'], env=_LIVE_ENV,
                     capture_output=True, text=True, cwd=_HERE)
        _guarded = 'REFUSING' in _g.stdout
        if _guarded:
            check('  the blind-arm guard refuses to write a dead agent_clock',
                  _g.returncode == 1 and 'drift 0 in every band' in _g.stdout,
                  f'exit {_g.returncode}')
        else:
            # LOUDLY, not by vanishing. Wrapped in `if _guarded:` alone this assertion
            # simply did not exist on a machine whose store is readable, which is the
            # pattern this whole file is written against: a check that is absent reads
            # exactly like a check that passed.
            print('  skip  the blind-arm guard   this store is readable, nothing to refuse')

        # And a --ship run repairs the divergence, rather than leaving a human to copy the
        # file. The packaged copy became opt-in behind --ship ("a site build must not mutate
        # published package data as a side effect"); this assertion said "a plain run" and so
        # had been asserting behaviour the calibrator deliberately gave up. --force is passed
        # only where the guard already fired: this block is testing the WRITE mechanism, and
        # it restores both files from backup in the finally below.
        if _guarded:
            _sp.run([_sys.executable, str(_CAL), '--ship', '--force'], env=_LIVE_ENV,
                    capture_output=True, text=True, cwd=_HERE)
        check('a --ship run rewrites BOTH copies', _SHIPPED.read_text() == _OUT.read_text())
        _rc2 = _sp.run([_sys.executable, str(_CAL), '--check'],
                       env=_LIVE_ENV, capture_output=True, text=True, cwd=_HERE)
        check('  and the check passes again', _rc2.returncode == 0, f'exit {_rc2.returncode}')
    except _SkipCorpus:
        print('  skip  the calibrator round-trip   no drift log on this machine')
    finally:
        _SHIPPED.write_text(_bak)
        _OUT.write_text(_bak_out)
        for _live, _side in _sides:
            if _side.exists():
                _side.unlink()

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    sys.exit(1)
print('  PASS — it schedules from a clock, and says "unknown" where it was never measured.')
