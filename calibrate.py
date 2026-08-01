#!/usr/bin/env python3
"""calibrate.py — derive a Calibration from recorded sessions instead of guessing one.

WHY THIS CAN EXIST NOW. Until 2026-07-24 the instrument's numbers were six literals and
there was no way to ask whether they were the right ones — no recorded sessions, and no
object to vary. `Calibration` made them variable and a host hook started
recording real runs, including what each check was GIVEN. Together those make the
question empirical for the first time.

WHAT IT DOES. Replays every recorded check under a grid of calibrations and reports what
recall and precision WOULD have been, against the same ground truth dogfood.py uses: an
error independently caught by a build guard, a failing test, or a human.

WHAT IT REFUSES TO DO. Emit a profile from thin data. A calibration tuned on a handful of
sessions is not a measurement, it is a story about a handful of sessions — and the harness
exists because tuning against your own recent behaviour is exactly how you drift. The
floors below are deliberately awkward:

    at least MIN_SESSIONS distinct sessions
    at least MIN_CATCHES independently-caught errors
    at least MIN_FIRES drift verdicts to compute any precision from

Fail any of them and it prints what is missing and exits without a recommendation. That
is the honest output, not a fallback.

    python3 calibrate.py                       # reads ~/.claude/laserbrain/*.json
    python3 calibrate.py --sessions 'path/*.json'
"""
import sys, json, glob, pathlib, itertools

MIN_SESSIONS, MIN_CATCHES, MIN_FIRES = 5, 20, 10
LOOKBACK = 3                      # same window dogfood.py scores against

GOAL_MIN_GRID = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
SELF_REPORT_GRID = [0.05, 0.10, 0.15, 0.20, 0.25]


def load(patterns):
    out = []
    for pat in patterns:
        for f in glob.glob(str(pathlib.Path(pat).expanduser())):
            try:
                out.append(json.load(open(f)))
            except Exception as e:
                print(f'  skipped {f}: {e}')
    return out


def replay(sess, goal_min, self_report_min):
    """Re-run this session's recorded checks under one calibration.

    Imports laserbrain lazily and by name so a missing/old install is a clear message
    rather than a traceback three frames deep."""
    from laserbrain import Harness, Calibration
    cal = Calibration(goal_min=goal_min, self_report_min=self_report_min)
    h = Harness(calibration=cal)
    fires = set()
    for c in sess.get('checks', []):
        if not c.get('goal'):
            continue                      # pre-2026-07-24 sessions recorded no inputs
        v = h.check(goal=c['goal'], progress=c.get('progress') or 'advancing',
                    distance=c.get('distance'))
        if v.drifting:
            fires.add(c['step'])
    return fires


def score(sessions, goal_min, self_report_min):
    hits = catches = fired = explained = 0
    for s in sessions:
        f = replay(s, goal_min, self_report_min)
        cs = s.get('catches', [])
        catches += len(cs)
        fired += len(f)
        window = set()
        for c in cs:
            w = range(max(0, c['step'] - LOOKBACK), c['step'] + 1)
            window |= set(w)
            if any(x in f for x in w):
                hits += 1
        explained += len(f & window)
    return {'goal_min': goal_min, 'self_report_min': self_report_min,
            'recall': hits / catches if catches else None,
            'precision': explained / fired if fired else None,
            'fires': fired, 'hits': hits, 'catches': catches}


def main(argv):
    pats = ['~/.claude/laserbrain/*.json']
    if '--sessions' in argv:
        pats = [argv[argv.index('--sessions') + 1]]
    sessions = load(pats)
    replayable = [s for s in sessions if any(c.get('goal') for c in s.get('checks', []))]
    catches = sum(len(s.get('catches', [])) for s in replayable)

    print(f'  {len(sessions)} session(s) found, {len(replayable)} replayable, {catches} catch(es)')

    missing = []
    if len(replayable) < MIN_SESSIONS:
        missing.append(f'{MIN_SESSIONS - len(replayable)} more replayable session(s)')
    if catches < MIN_CATCHES:
        missing.append(f'{MIN_CATCHES - catches} more independently-caught error(s)')
    if missing:
        print('\n  NO RECOMMENDATION — not enough data to derive a calibration.')
        print('  Missing: ' + '; '.join(missing) + '.')
        print('\n  This is the honest output. A calibration fitted to a handful of sessions')
        print('  describes those sessions, and tuning the reference against your own recent')
        print('  behaviour is the failure this product is named after. Keep the hook')
        print('  attached, keep working, and run this again when the floors are met.')
        return 1

    rows = [score(replayable, g, sr)
            for g, sr in itertools.product(GOAL_MIN_GRID, SELF_REPORT_GRID)]
    usable = [r for r in rows if r['fires'] >= MIN_FIRES and r['recall'] is not None]
    if not usable:
        print(f'\n  NO RECOMMENDATION — no calibration in the grid fired {MIN_FIRES}+ times.')
        print('  Precision cannot be estimated from fewer, so none is reported.')
        return 1

    usable.sort(key=lambda r: (-(r['recall'] or 0), -(r['precision'] or 0)))
    print(f'\n  {"goal_min":>9} {"self_rep":>9} {"recall":>8} {"precision":>10} {"fires":>6}')
    for r in usable[:10]:
        print(f'  {r["goal_min"]:>9.2f} {r["self_report_min"]:>9.2f} '
              f'{r["recall"]:>8.0%} {r["precision"]:>10.0%} {r["fires"]:>6}')
    best = usable[0]
    print(f'\n  Best on this data: Calibration(goal_min={best["goal_min"]}, '
          f'self_report_min={best["self_report_min"]})')
    print('  Report it WITH the published instrument\'s numbers on the same data, or a')
    print('  reader cannot tell a real improvement from a grid searched until it flattered.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
