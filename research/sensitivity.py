#!/usr/bin/env python3
"""The other half of the detection matrix — what the instrument MISSED.

    python3 sensitivity.py            # report
    python3 sensitivity.py --window 3 # tighter attribution than the default 4

WHY THIS COULD NOT EXIST BEFORE
-------------------------------
`corpus-map.py` prints, in the WHAT IT CANNOT ANSWER section:

    d-prime  not computable, now or ever, from this corpus.

That was true and it was a statement about a missing FIELD, not about the world. Precision
only needs fires, and a fire identifies itself. Sensitivity needs the opposite case — a
moment where something was genuinely wrong and the instrument said nothing — and the only
record of "genuinely wrong" is `catches`, which live in the session file, while readings
live in the drift log. Two files, two independent step counters, no shared key. A catch
could not name the reading that was live when it happened, so a miss was unobservable.

The join landed 2026-08-01: `check_state` returns `run` and `step`, the session records
them on every check, and every catch carries the reading that was live plus `since` — how
many steps back that reading was.

AND THE JOIN WAS NOT ENOUGH, which this file learned by being wrong first
------------------------------------------------------------------------
The paragraph above used to end "That is all sensitivity ever needed." Its first real run,
2026-08-02, returned 0 hits and 8 misses — a 0.0% hit rate — and every one of the eight was
the coverage gate blocking a call in the session that was running this analysis.

The gate fires BECAUSE the instrument has been quiet; a lapse is defined as too many steps
since check_state. So a gate-block catch lands on a quiet reading by construction, can never
coincide with a fire, and produces a 0% hit rate before any data is collected. The join gave
the two sides a shared key. It did not make the catches independent of the instrument, and
sensitivity needs both.

The gate is now excluded at the point of recording, and catches written before that are
dropped whole — see collect(). The count restarts from clean data.

WHAT THIS ACTUALLY MEASURES, AND WHAT IT DOES NOT
-------------------------------------------------
Not "does laserbrain catch mistakes". It measures agreement between the instrument and one
proxy for error: a non-zero exit. Four limits, none of which go away with more data:

  THE PROXY IS NARROW      A failed command is a real, independent error signal — the build
                           disagreeing, with no opinion about the instrument. But most
                           drift is not a failed command. An agent that spends nine steps
                           confidently building the wrong thing produces zero catches. Those
                           are misses this can never see, so the miss rate here is a FLOOR.

  SOME CATCHES ARE ON PURPOSE  ./mutate.sh exists to prove the suite can go red, and every
                           red it produces is a catch. A deliberately failing test is not a
                           moment the instrument should have fired on. --exclude drops
                           commands matching known-intentional patterns; whatever remains
                           is still contaminated in the same direction.

  ATTRIBUTION DECAYS       Coverage on this machine runs near 24%, so three steps in four
                           have no reading at all. A catch `since=1` was live under its
                           reading; `since=12` fell in a stretch nothing watched, and
                           scoring that as a miss blames the detector for a step it was
                           never shown. WINDOW is the cut, and moving it moves the answer —
                           which is why the number is reported per-window, not once.

  QUIET IS NOT CORRECT     The false-alarm denominator is readings with no catch attributed.
                           That treats "nothing failed" as "nothing was wrong", which is
                           the same assumption the proxy already makes, counted twice.

So: a real number where there was none, and it is a measure of agreement with the build,
under a stated window. It is not the instrument's true sensitivity, and this file should
never be quoted as if it were.
"""
import argparse
import glob
import json
import math
import os
import pathlib
import re
import statistics

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
import _root                                                       # noqa: E402

DRIFT = pathlib.Path(os.environ.get('LASERBRAIN_DRIFT_LOG')
                     or _root.config('drift-log.jsonl'))
SESSIONS = _root.sessions_dir()

# Commands whose failure is the POINT. The mutation gate flips an operator and demands the
# suite go red; a red there is the tool working. Counting it as an error the instrument
# should have anticipated would score laserbrain against its own test harness.
INTENTIONAL = re.compile(r'mutate\.sh|--deep\b|expected[- ]fail|should[- ]fail', re.I)

# How many steps a reading is allowed to "cover". Chosen to match stall_window=4 in the
# calibration — the instrument already treats four steps as the horizon over which a
# reading says something, so borrowing a different number here would measure the join
# against a window the grammar does not use.
WINDOW = 4


def load_rows(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def load_sessions(d):
    out = []
    for f in glob.glob(str(pathlib.Path(d) / '*.json')):
        try:
            out.append(json.load(open(f)))
        except Exception:
            continue          # a half-written session is not a finding, just skip it
    return out


def segments_of(s):
    """Every task the session held — the live one plus any archived by reset.

    A reset archives checks and catches into `segments` and clears the live slots, so a
    session read only at the top level loses every task but the last. That is how a
    ~100-step session came back as 3 steps once before.
    """
    yield s
    for seg in (s.get('segments') or []):
        yield seg


def collect(sessions, window, exclude_intentional):
    """Join catches to the readings that were live, and count the four cells."""
    hits, misses, unjoinable, far, dropped, precontam = [], [], 0, 0, 0, 0
    fired_keys, seen_keys = set(), set()

    # Every reading the sessions recorded, keyed the way the drift log keys them.
    reading = {}
    for s in sessions:
        for seg in segments_of(s):
            for c in (seg.get('checks') or []):
                if c.get('run') and c.get('run_step') is not None:
                    k = (c['run'], c['run_step'])
                    reading[k] = c
                    seen_keys.add(k)
                    if c.get('drifting'):
                        fired_keys.add(k)

    for s in sessions:
        for seg in segments_of(s):
            for cat in (seg.get('catches') or []):
                what = str(cat.get('what') or '')
                # THE CONTAMINATED ERA. Until 2026-08-02 a coverage-gate block counted as a
                # catch. The gate fires BECAUSE the instrument was quiet, so those catches
                # land on quiet readings by construction and can only ever score as misses:
                # this file's first real run reported 0 hits / 8 misses, and all eight were
                # the gate blocking the very session that was analysing it. 0.0% was an
                # identity, not a result.
                #
                # They cannot be cleaned retroactively — a catch stores "failed call: Bash"
                # and not the text that would identify it — so they are dropped whole rather
                # than estimated around. `clean` is stamped by the code that knows to exclude
                # the gate; its absence means "written before that was true". Dating them
                # would not work either: the fix landed mid-session, so the contaminated
                # catches share a date with the clean ones.
                if not cat.get('clean'):
                    precontam += 1
                    continue
                if exclude_intentional and INTENTIONAL.search(what):
                    dropped += 1
                    continue
                run, rstep, since = cat.get('run'), cat.get('run_step'), cat.get('since')
                if not run or rstep is None:
                    unjoinable += 1          # predates the join, or fired before any check
                    continue
                if since is None or since > window:
                    far += 1                 # fell in a stretch nothing watched
                    continue
                r = reading.get((run, rstep))
                if r is None:
                    unjoinable += 1
                    continue
                (hits if r.get('drifting') else misses).append(
                    {'what': what[:80], 'since': since, 'reason': r.get('reason'),
                     'phi': r.get('phi'), 'run': run, 'step': rstep})

    caught_keys = {(h['run'], h['step']) for h in hits}
    return {'hits': hits, 'misses': misses, 'unjoinable': unjoinable, 'far': far,
            'dropped': dropped, 'precontam': precontam, 'fired': fired_keys, 'seen': seen_keys,
            'caught': caught_keys}


def dprime(hit, n_signal, fa, n_noise):
    """d' with the standard 0.5/N edge correction, and an honest refusal when n is tiny.

    A rate of 0 or 1 sends z to infinity, so Macmillan & Kaplan's correction nudges it by
    half an observation. That correction is defensible at n=50 and meaningless at n=3: it
    would manufacture a finite, confident-looking number out of a sample that cannot
    support one. Below MIN_N this returns None rather than a figure someone might quote.
    """
    MIN_N = 20
    if n_signal < MIN_N or n_noise < MIN_N:
        return None, f'n too small (signal {n_signal}, noise {n_noise}; need {MIN_N} each)'
    h = min(max(hit / n_signal, 0.5 / n_signal), 1 - 0.5 / n_signal)
    f = min(max(fa / n_noise, 0.5 / n_noise), 1 - 0.5 / n_noise)
    z = statistics.NormalDist().inv_cdf
    return z(h) - z(f), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--window', type=int, default=WINDOW,
                    help=f'max steps between a reading and a catch it covers (default {WINDOW})')
    ap.add_argument('--keep-intentional', action='store_true',
                    help='count deliberately-failing commands (mutation gate) as errors')
    a = ap.parse_args()

    sessions = load_sessions(SESSIONS)
    d = collect(sessions, a.window, not a.keep_intentional)
    bar = '=' * 68
    print(f'\n{bar}\n  SENSITIVITY — what the instrument missed\n{bar}')
    print(f'  sessions read      {len(sessions)}')
    print(f'  readings joinable  {len(d["seen"])}   (carry run + run_step)')
    print(f'  window             {a.window} step(s)')
    if d['dropped']:
        print(f'  excluded           {d["dropped"]} deliberately-failing command(s)')

    n_hit, n_miss = len(d['hits']), len(d['misses'])
    total = n_hit + n_miss
    if not total:
        print(f'\n  NO JOINABLE CATCHES.')
        print(f'    unjoinable  {d["unjoinable"]:>4}  no run/run_step — recorded before the join')
        print(f'    out of window {d["far"]:>2}  a reading was too far back to have covered it')
        print(f'    excluded    {d["precontam"]:>4}  written while a gate block still counted '
              f'as a catch')
        if d['precontam']:
            # Printed HERE as well as in the main report, because this branch runs while the
            # clean corpus is still empty — which is exactly when a silently dropped count
            # would be misread as "there was never any data".
            print('\n  Those excluded catches are why this says nothing yet. Until 2026-08-02')
            print('  a coverage-gate block counted as a catch, and the gate fires precisely')
            print('  when the instrument is quiet — so they could only ever score as misses.')
            print('  The first run of this file reported 0 hits / 8 misses on exactly that,')
            print('  which was an identity and not a measurement. They cannot be cleaned')
            print('  after the fact, so sensitivity restarts from clean data.')
        else:
            print('\n  The join fields landed 2026-08-01, so every older catch predates')
            print('  them. Nothing is wrong and nothing is proven.')
        print('\n  The number becomes available as new sessions run. Reporting it as 0%')
        print('  would be a fabrication, so it is not reported.\n')
        return 0

    # SIGNAL trials: a catch happened. NOISE trials: readings with no catch attributed.
    n_noise = len(d['seen']) - len(d['caught']) - n_miss
    fa = len({k for k in d['fired'] if k not in d['caught']})

    print(f'\n{bar}\n  AGREEMENT WITH THE BUILD\n{bar}')
    print(f'  hits    {n_hit:>4}   a catch landed while the instrument was already firing')
    print(f'  misses  {n_miss:>4}   a catch landed on a reading that said nothing')
    print(f'  hit rate  {n_hit / total * 100:.1f}%  of {total} attributable catch(es)')
    print(f'  unjoinable {d["unjoinable"]:>3}   out of window {d["far"]:>3}   (neither counted)')
    if d['precontam']:
        print(f'\n  EXCLUDED {d["precontam"]:>3}   catches written before 2026-08-02, when a '
              f'coverage-gate\n              block still counted as a catch. Not cleanable '
              f'after the fact —\n              see collect(). Sensitivity restarts from '
              f'clean data.')

    dp, why = dprime(n_hit, total, fa, max(n_noise, 0))
    print(f'\n{bar}\n  d-prime\n{bar}')
    if dp is None:
        print(f'  withheld — {why}')
        print('  The formula would return a number. It would not mean anything, and a')
        print('  printed figure gets quoted regardless of the caveat beside it.')
    else:
        print(f"  d' = {dp:.2f}   (hit {n_hit}/{total}, false alarm {fa}/{n_noise})")
        print("  Agreement with a non-zero exit, inside a "
              f"{a.window}-step window. Not the instrument's true sensitivity —")
        print('  see the four limits at the top of this file before quoting it.')

    if d['misses']:
        print(f'\n{bar}\n  THE MISSES — read these, they are the finding\n{bar}')
        for m in sorted(d['misses'], key=lambda m: m['since'])[:12]:
            print(f"  since {m['since']}  Φ={m['phi']}  {m['reason']:<16} {m['what']}")
    print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
