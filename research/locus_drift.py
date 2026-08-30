#!/usr/bin/env python3
"""locus_drift.py — the harness, run against a locus lab log.

WHY THIS FITS, AND IT IS NOT DECORATION.

Locus already encodes the discipline. Its lab-log schema defines `goal` as:

    "Pass line held fixed for this run — do not revise."

That is a fixed reference, declared once and explicitly not revisable, written down before
laserbrain was ever pointed at it. What locus does not have is the instrument: nothing
measures how far a run has moved from its own pass line while it runs.

And a resonance harvester is the rare case where every term is MEASURED:

    goal      the run's declared pass line — held fixed, per the schema
    distance  detuning |f_drive − f0| in Hz, sampled continuously
    progress  read from the detuning series itself, not self-reported

In software, distance has no honest signal and must be spelled or left None, which makes
Φ a lower bound and disables the stall detector. laserbot gets distance in metres. Locus
gets it in hertz. Both are cases where the instrument runs COMPLETE.

WHAT LOCUS FOUND IN THE INSTRUMENT.

Pointing the harness at a matched rig exposed a real limitation of the published detector,
and it is worth stating rather than working around silently:

    the stall rule cannot distinguish "stopped making progress" from "arrived".

`stalled` fires when distance stops falling. Distance cannot fall below zero. A resonance
harvester that reaches f0 and HOLDS there sits at detuning 0.00 Hz for the rest of the run
and trips the stall detector on every sample. In software this never surfaces: distance 0
means done and you stop checking. In a continuous system, holding at the goal IS the
success condition and it looks identical to a stall.

This adapter therefore reports `held` itself rather than passing that verdict through and
calling a working rig stalled. The instrument is NOT changed — it is frozen, versioned and
parity-tested in three languages, and one domain finding is not grounds for moving it
unilaterally. The finding is recorded here and belongs in CLAIM.md as a known boundary.

WHAT IT DOES NOT CLAIM. This detects displacement from the pass line. It does not judge
whether the run succeeded — that is what the run's own summary and the P0/RP0 pass/fail
runbooks are for. A run can drift and still pass; a run can hold f0 and still fail on
yield. Drift and success are different questions and conflating them would be the same
overclaim this project keeps refusing.

    python3 locus_drift.py ../../phronesis-world/public/locus/runs/*.json
"""
import sys, json, glob, pathlib

# Detuning that counts as "as far from the goal as the scale goes". 5 Hz off a membrane
# f0 is a harvester that has stopped harvesting; the harness scale is 0-10, so this maps
# hertz onto it. Stated here rather than buried so it can be argued with.
FULL_SCALE_HZ = 5.0

# Detuning at or under this is ON the pass line, not merely near it. A matched harvester
# sits here and stays: its detuning series is perfectly flat at ~0. The first version of
# this file read that flatness as "stuck" and reported 4798 of 4800 samples off-goal on a
# rig that was doing exactly what it was built to do. Flat AT the goal is held; flat AWAY
# from it is stuck. The difference is the whole verdict.
HELD_HZ = 0.05


def detuning(sample):
    """|f_drive − f0| in Hz, or None when detuning is not a defined quantity.

    None is not zero, and it is not a large number either. Two ways it is undefined:

      no frequency channel   a P0 solar run has no membrane and no f0. Pretending its
                             detuning is 0 reports a perfectly matched rig that does not
                             exist.

      the drive is OFF       `drive_on: false` sets f_drive to 0.0, and |0 − f0| looks
                             like a full detune. It is not. The rig is not mistuned, it
                             is not running. The first version of this file read that as
                             1200 samples off the pass line on a run whose goal was
                             "piezo energy rises only while drive_on" and whose status
                             was PASS — the drive stopping was the designed second phase
                             of the experiment.

    Both stay unknown, which makes Φ a lower bound. That is the same rule the software
    path uses, and I broke it here two lines after writing it down.
    """
    if sample.get('drive_on') is False:
        return None
    f_drive, f0 = sample.get('f_drive'), sample.get('f0')
    if f_drive is None or f0 is None:
        return None
    try:
        return abs(float(f_drive) - float(f0))
    except (TypeError, ValueError):
        return None


def to_distance(hz):
    if hz is None:
        return None
    return max(0, min(10, round(10 * hz / FULL_SCALE_HZ)))


def progress_from(series):
    """advancing | stuck | circling, from the detuning series alone.

    Measured, not self-reported — a rig cannot tell you how it feels. Falling detuning is
    advancing; flat is stuck; a sign-alternating series is circling, which is what a
    controller hunting around f0 actually looks like.
    """
    w = [d for d in series[-4:] if d is not None]
    if len(w) < 3:
        return 'advancing'
    # On the pass line: holding is the goal, not a stall. Checked FIRST, because a matched
    # rig has a perfectly flat series and every flatness test below would misread it.
    if w[-1] <= HELD_HZ:
        return 'advancing'
    deltas = [b - a for a, b in zip(w, w[1:])]
    if all(abs(d) < 1e-9 for d in deltas):
        return 'stuck'                      # flat, and NOT at the goal
    signs = [1 if d > 0 else -1 for d in deltas if abs(d) > 1e-9]
    if len(signs) >= 2 and all(a != b for a, b in zip(signs, signs[1:])):
        return 'circling'                   # hunting around f0
    if w[-1] < w[0]:
        return 'advancing'
    return 'stuck'


def score(run):
    """Replay one lab log through the harness. Returns the trace and a verdict tally."""
    from laserbrain import Harness

    goal = str(run.get('goal') or '').strip()
    if not goal:
        return None, 'no goal declared — the schema requires a pass line'

    hz = [detuning(s) for s in run.get('samples') or []]
    if not hz:
        return None, 'no samples'

    h = Harness()
    trace, measured = [], sum(1 for d in hz if d is not None)
    for i, d in enumerate(hz):
        v = h.check(goal=goal, progress=progress_from(hz[:i + 1]), distance=to_distance(d))
        # On the pass line and holding. The harness says `stalled` here because distance
        # stopped falling, which is true and misleading: it arrived. Reported as `held`
        # rather than laundered into a drift verdict a working rig does not deserve.
        held = d is not None and d <= HELD_HZ
        reason = 'held' if (held and v.reason in ('stalled', 'advancing', 'grounded')) else v.reason
        trace.append({'i': i, 'hz': d, 'reason': reason, 'phi': v.phi, 'held': held})
    return {'goal': goal, 'trace': trace, 'measured': measured, 'total': len(hz)}, None


def main(argv):
    paths = [f for p in argv[1:] for f in glob.glob(p)] or glob.glob(
        str(pathlib.Path(__file__).parent / '../../phronesis-world/public/locus/runs/*.json'))
    if not paths:
        print('  no runs found — pass a path to lab-log json'); return 1

    for p in sorted(paths):
        try:
            run = json.load(open(p))
        except Exception as e:
            print(f'  {pathlib.Path(p).name}: unreadable ({e})'); continue

        res, err = score(run)
        name = pathlib.Path(p).stem
        if err:
            print(f'\n  {name}\n    skipped — {err}'); continue

        drifts = [t for t in res['trace'] if t['reason'] not in ('grounded', 'advancing', 'held')]
        held = sum(1 for t in res['trace'] if t['reason'] == 'held')
        cover = f"{res['measured']}/{res['total']} samples carry f_drive and f0"
        print(f"\n  {name}")
        print(f"    goal    {res['goal'][:66]}")
        print(f"    signal  {cover}")
        if res['measured'] == 0:
            print("    Φ is a LOWER BOUND — no frequency channel, so detuning is unknown")
            print("    and the stall detector cannot run. Not a clean rig, an unmeasured one.")
        if held:
            print(f"    held    {held}/{res['total']} samples ON the pass line (detuning <= {HELD_HZ} Hz)")
        if not drifts:
            print(f"    verdict never left the pass line across {res['total']} samples")
        else:
            print(f"    {len(drifts)} of {res['total']} samples left the pass line:")
            for t in drifts[:4]:
                hz = 'unknown' if t['hz'] is None else f"{t['hz']:.2f} Hz"
                print(f"      sample {t['i']:>3}  {t['reason']:<20} Φ={t['phi']:<5} detuning {hz}")
    print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
