#!/usr/bin/env python3
"""
dogfood.py — did the harness fire where something later caught a real error?

The question four studies could not answer ([[MEASURE]]) was "was the answer better",
and it died on judges four times because open-ended work has no criterion. This asks a
different question, and it has one:

    When a build guard, a failing test, or Diego caught a REAL error in a session,
    had laserbrain already fired?

Hits, misses and false alarms are all countable. The ground truth is not a judgement —
it is a guard that failed, a test that went red, or a human who said "that's wrong".
No panel, no kappa.

WHAT THIS IS NOT. It does not show the harness makes the work better. It shows whether
the harness's signal coincides with independently-detected error. That is a weaker and
far more checkable claim, and it is the honest first rung.

    python3 dogfood.py --smoke
    python3 dogfood.py --score sessions/2026-07-24.json
"""
import sys, json, glob, statistics, os

# How many steps before the catch the harness may have fired and still count as a hit.
# Fixed here rather than tuned per-session: a monitor that "predicts" an error it fired
# for twenty steps earlier is not predicting anything.
LOOKBACK = 3

# A session where the harness was barely called cannot produce a detection result. It
# produces a coverage result, and the two look identical from the outside: both show
# zero fires next to real catches. On 2026-07-24 a long, error-dense session recorded
# ONE check across ~48 steps because check_state was never attached, and this scorer
# printed "RECALL 0/10 = 0%" under a line telling the reader to believe it. Silence
# from a detector that is not running says nothing about the detector.
#
# Read from the environment so the gate that ENFORCES coverage and the scorer that
# DEMANDS it are one number. They were two: this was hard-coded 0.5 while lb_gate.py
# gated on a step count landing near 20%, in another file, with nothing joining them.
# Every run therefore satisfied the gate and failed the scorer, and the only symptom was
# "RECALL withheld" forever — which reads as low adoption and was a spec contradiction.
#
# Default stays 0.5 here because this is the MEASUREMENT floor: below it a zero-fire
# result says nothing, and that is a fact about inference, not about tooling comfort.
# Daily work gates lower on purpose. A study raises both together and pays the tax:
#
#     LASERBRAIN_MIN_COVERAGE=0.5 <run the benchmark, then score it>
#
MIN_COVERAGE = min(1.0, max(0.0, float(os.environ.get('LASERBRAIN_MIN_COVERAGE', 0.5) or 0.5)))


def expand(sess: dict) -> list:
    """A session file into its scoreable SEGMENTS.

    reset_task archives the interval it closes (Session.reset), so one file holds a list of
    completed segments plus whatever is live. Each is scored on its own because each IS its
    own unit: one declared goal, one interval, one denominator.

    Averaging them together is what made coverage meaningless before. A session that spent
    2500 ungrounded steps early and then ran disciplined for 40 reports the average of the
    two, which describes neither — and the ungrounded stretch drags every later segment
    below the gate with it.

    Files written before segments existed have no 'segments' key and score exactly as they
    did, so the old corpus stays readable.
    """
    out = []
    for i, seg in enumerate(sess.get('segments') or [], 1):
        d = dict(seg)
        d['id'] = f"{sess.get('id', '?')}#{i}"
        out.append(d)
    # The live tail — the segment in progress, which has not been archived yet.
    if int(sess.get('steps', 0)) > 0:
        # Defaults matter: sess.get(k) yields None for an absent key, and score_session
        # calls len() on three of these. A pre-segments file has no 'inferred' at all, so
        # copying it as None crashed the scorer on the entire old corpus.
        d = {k: (sess.get(k) or ([] if k != 'goal' else None))
             for k in ('goal', 'steps', 'checks', 'inferred', 'catches')}
        d['steps'] = int(sess.get('steps') or 0)
        d['id'] = f"{sess.get('id', '?')}#live" if out else sess.get('id', '?')
        out.append(d)
    return out or [sess]


def score_session(sess: dict) -> dict:
    """sess: {'checks': [{'step', 'drifting', 'reason'}], 'catches': [{'step', 'what', 'by'}]}

       A CATCH is an error independently found — by a guard, a test, or a human. A
       FIRE is a drifting verdict from the harness."""
    fires = {c['step'] for c in sess.get('checks', []) if c.get('drifting')}
    catches = sess.get('catches', [])
    hits, misses = [], []
    for c in catches:
        window = range(max(0, c['step'] - LOOKBACK), c['step'] + 1)
        (hits if any(s in fires for s in window) else misses).append(c)
    # a fire with no catch inside the lookahead is unexplained — not necessarily wrong,
    # but it is the number that keeps this honest
    explained = {s for c in catches for s in range(max(0, c['step'] - LOOKBACK), c['step'] + 1)}
    false_alarms = sorted(fires - explained)
    steps = sess.get('steps', len(sess.get('checks', [])))
    n_checks = len(sess.get('checks', []))
    # Inferred checks are counted, and counted SEPARATELY. The hook can infer a state on
    # every single tool call, so folding them in would make coverage trivially 100% and
    # turn the gate below into decoration. Inferred state also carries no distance, so
    # its Φ is a lower bound and it cannot produce the 'stalled' verdict at all — it is
    # a weaker measurement, not the same one taken automatically.
    n_inferred = len(sess.get('inferred', []))
    return {'session': sess.get('id', '?'), 'steps': steps, 'checks': n_checks,
            'inferred': n_inferred,
            'inferred_coverage': (n_inferred / steps) if steps else 0.0,
            'coverage': (n_checks / steps) if steps else 0.0,
            'fires': len(fires), 'catches': len(catches), 'hits': len(hits),
            'misses': [m['what'] for m in misses], 'false_alarms': len(false_alarms)}


def report(rows: list) -> None:
    # PRECISION and RECALL do not need the same evidence, and conflating them withheld the
    # only number this corpus could actually produce.
    #
    #   RECALL asks "a real error happened — had the harness fired?" That is unanswerable
    #   at low coverage. If 80% of steps were never checked, silence means nothing, and a
    #   number would measure adoption while reading as detection. Gate it. This was right.
    #
    #   PRECISION asks "the harness fired — was there a real error?" Every fire is its own
    #   evidence. Unchecked steps do not enter the ratio at all, so coverage cannot bias
    #   it — only shrink the sample. What DOES bias it is an incomplete catch log: a fire
    #   with no logged error beside it is scored a false alarm, and some of those were real
    #   errors nothing independently caught. That runs one way, so the figure is an honest
    #   LOWER BOUND on precision, not an invalid one.
    #
    # Until 2026-07-25 report() dropped every thin session before computing either, so a
    # 29-segment corpus with 35 fires reported precision from a single surviving segment:
    # "0/1 = 0%". A sample of one, printed as a rate.
    precision_rows = [r for r in rows if r['fires']]
    thin = [r for r in rows if r['coverage'] < MIN_COVERAGE]
    if thin:
        print(f"\n  UNSCORABLE for detection — {len(thin)} of {len(rows)} session(s) below "
              f"{MIN_COVERAGE:.0%} coverage:")
        for r in thin:
            extra = (f", {r['inferred']} inferred = {r['inferred_coverage']:.0%}"
                     if r.get('inferred') else '')
            print(f"    · {r['session']}: {r['checks']} spelled check(s) over {r['steps']} steps "
                  f"= {r['coverage']:.0%}{extra}")
        if any(r.get('inferred') for r in thin):
            print("  Inferred coverage does NOT open the gate: no distance means a lower-bound")
            print("  Φ and no stall detector, so it is a weaker measurement, not the same one.")
        print("  The harness was not attached for these. Their catches are real; their")
        print("  ZERO FIRES ARE NOT EVIDENCE. Recall is withheld rather than reported low —")
        print("  a number here would measure adoption and be read as detection.")
        rows = [r for r in rows if r['coverage'] >= MIN_COVERAGE]

    # ── precision, over every session where the harness actually fired ──────────
    PF = sum(r['fires'] for r in precision_rows)
    PFA = sum(r['false_alarms'] for r in precision_rows)
    if PF:
        print(f"\n  PRECISION  {PF-PFA}/{PF} = {(PF-PFA)/PF:.0%}   (the harness fired; was "
              f"there a real error?)")
        print(f"             over {len(precision_rows)} session(s) that fired, at any coverage.")
        print("             A LOWER BOUND: a fire with no logged error beside it counts")
        print("             against us, and some of those were real errors no guard caught.")
    else:
        print("\n  PRECISION  undefined — the harness never fired in these sessions.")
        print("             Not a good score. No score. Report it this way or an absent")
        print("             false-alarm rate reads as a low one.")

    # ── recall, only where the harness was actually attached ───────────────────
    if not rows:
        print("\n  RECALL     withheld — no session reached the coverage floor.")
        print("             Attach the harness and re-run the work.")
        return
    H = sum(r['hits'] for r in rows)
    C = sum(r['catches'] for r in rows)
    F = sum(r['fires'] for r in rows)
    print(f"\n  scorable for recall: {len(rows)} session(s) · fires {F} · independent catches {C}")
    if C:
        print(f"  RECALL     {H}/{C} = {H/C:.0%}   (a real error was caught; had the harness fired?)")
    else:
        print("  RECALL     undefined — no independent catches in the scorable sessions.")
    misses = [m for r in rows for m in r['misses']]
    if misses:
        print(f"\n  MISSED — real errors the harness was silent for ({len(misses)}):")
        for m in misses: print(f"    · {m}")
    print("\n  Read honestly: recall is the number that matters, and a low one is a real")
    print("  result about the harness, not about the workload. Report both, always.")


def smoke() -> None:
    print("dogfood.py --smoke · validates the scorer, not the harness")
    # An ATTACHED session: the harness is called every step, which is what it is for.
    # The old fixture declared 10 steps and 2 checks — it was quietly modelling an
    # unattached run while asserting things about detection.
    s = {'id': 'smoke', 'steps': 16,
         'checks': [{'step': i, 'drifting': i in (2, 7),
                     'reason': {2: 'goal-drift', 7: 'stalled'}.get(i, 'grounded')}
                    for i in range(1, 17)],
         'catches': [{'step': 3, 'what': 'guard caught a bad edit', 'by': 'build'},
                     {'step': 15, 'what': 'human caught a wrong claim', 'by': 'diego'}]}
    r = score_session(s)
    assert r['hits'] == 1 and len(r['misses']) == 1, r
    assert r['false_alarms'] == 1, r          # the step-7 fire explains nothing
    assert r['coverage'] >= MIN_COVERAGE, r   # 2 checks over 10 steps... see below
    report([r])
    print("\n  ✓ a fire inside the lookback counts as a hit; a catch with no fire is a MISS;")
    print("    a fire explaining no catch is a false alarm. All three are counted.")

    # and the case that motivated the coverage gate: the harness was never attached
    unattached = {'id': 'smoke-unattached', 'steps': 40,
                  'checks': [{'step': 1, 'drifting': False, 'reason': 'grounded'}],
                  'catches': [{'step': 12, 'what': 'a guard caught a real bug', 'by': 'build'},
                              {'step': 30, 'what': 'a human caught a wrong claim', 'by': 'diego'}]}
    u = score_session(unattached)
    assert u['coverage'] < MIN_COVERAGE, u
    print("\n  -- unattached session --")
    report([u])
    print("\n  ✓ recall is WITHHELD, not reported as 0%. Before this gate the same input")
    print("    printed 'RECALL 0/2 = 0%' beside advice to trust it.")


def main() -> int:
    if '--score' in sys.argv:
        paths = sys.argv[sys.argv.index('--score') + 1:]
        files = [f for p in paths for f in glob.glob(p)]
        if not files:
            print('  no session files matched'); return 1
        rows = [score_session(seg) for f in files for seg in expand(json.load(open(f)))]
        for r in rows:
            print(f"  {r['session']:<24} fires {r['fires']:<3} catches {r['catches']:<3} "
                  f"hits {r['hits']:<3} false-alarms {r['false_alarms']}")
        report(rows)
        return 0
    smoke(); return 0


if __name__ == '__main__':
    raise SystemExit(main())
