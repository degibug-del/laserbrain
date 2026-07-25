#!/usr/bin/env python3
"""
measure.py — the preregistered instrument test ([[MEASURE]]).

Four studies died because open-ended answers cannot be graded reliably (H1's panel
agreed at κ=0.10). This does not test laserbrain. It tests whether a HIDDEN RUBRIC —
concrete binary requirements, frozen before any run and never shown to the agent —
gives judges the fixed reference that holistic "which is better?" lacks.

Two instruments, same answers, both binary, both scored with retest.py's Fleiss κ:
  holistic : "is this a high-quality answer?"  yes/no    ← the instrument that failed
  rubric   : "does it specify a mechanism for X?" yes/no ← per frozen item

Decision rule (frozen, MEASURE.md): rubric works iff κ ≥ 0.60 AND exceeds holistic
by ≥ 0.30; fails iff κ < 0.40; otherwise inconclusive.

  python3 measure.py --smoke
  read -rs K && ANTHROPIC_API_KEY="$K" python3 measure.py --live --n 20 --out retest_out/measure.json
"""
import sys, re, json, random

from retest import fleiss_kappa            # the SAME κ that produced H1's 0.10

# ── THE FROZEN RUBRICS — written before any run, never shown to the agent ──────
RUBRICS = {
    'colony': {
        'task': 'Design the governance structure for a lunar research colony of 200 people. '
                'Be concrete and complete.',
        'items': [
            'a named mechanism for removing or recalling the person or body in charge',
            'a rule for breaking deadlocks or ties in decisions',
            'a defined succession path when a leader dies, leaves, or is incapacitated',
            'a procedure for allocating a scarce physical resource (air, water, power, or space)',
            'a way disputes between individual residents are adjudicated',
            'a stated term length, election interval, or rotation schedule',
            'a limit or check on emergency powers, including when they expire',
            'a rule for admitting new residents or granting membership',
            'a distinction between scientific authority and civil or political authority',
            'a defined process for amending the governance structure itself',
        ],
    },
    'archive': {
        'task': 'Design a system for preserving a civilization’s digital records for 1,000 years. '
                'Be concrete and complete.',
        'items': [
            'a named physical storage medium with a stated expected lifetime',
            'a plan for format obsolescence — how future readers decode the files',
            'geographic or organizational replication against localized loss',
            'a scheduled integrity check or verification procedure',
            'a migration or refresh cycle with a stated interval',
            'a funding or governance model that survives the founding institution',
            'a stated policy for what is selected and what is discarded',
            'protection against deliberate tampering or censorship, not just decay',
            'a human-readable index or catalogue separate from the data itself',
            'an explicit failure mode the design accepts it cannot prevent',
        ],
    },
}

JUDGES = 3          # independent judge calls per question (the panel)


# ── judging ───────────────────────────────────────────────────────────────────
def _yn(txt):
    m = re.search(r'\b(yes|no)\b', str(txt).strip().lower())
    return None if not m else (m.group(1) == 'yes')


def judge_item(mh, task, answer, item):
    sys_p = ("You are checking whether an answer specifies a particular thing. Answer with exactly "
             "one word: YES or NO. Say YES only if the answer actually specifies it, not merely "
             "gestures at the topic.")
    q = f"TASK:\n{task}\n\nANSWER:\n{answer}\n\nDoes the answer specify {item}?\nYES or NO:"
    return _yn(mh.call(mh.MODEL, sys_p, [{'role': 'user', 'content': q}], 5))


def judge_holistic(mh, task, answer):
    sys_p = ("You are judging the overall quality of an answer. Answer with exactly one word: "
             "YES or NO.")
    q = f"TASK:\n{task}\n\nANSWER:\n{answer}\n\nIs this a high-quality answer to the task?\nYES or NO:"
    return _yn(mh.call(mh.MODEL, sys_p, [{'role': 'user', 'content': q}], 5))


# ── scoring ───────────────────────────────────────────────────────────────────
def rows_from(votes):
    """votes: list of per-subject [bool|None]×JUDGES → Fleiss rows [n_no, n_yes].
       Subjects where a judge failed to answer are dropped (can't be rated)."""
    rows = []
    for v in votes:
        vs = [x for x in v if x is not None]
        if len(vs) == JUDGES:
            rows.append([sum(1 for x in vs if not x), sum(1 for x in vs if x)])
    return rows


def drop_degenerate(item_votes):
    """Preregistered: an item every answer satisfies (or none do) has no variance and
       is dropped before scoring. Returns (kept_rows, n_dropped, n_items)."""
    kept, dropped = [], 0
    for item, votes in item_votes.items():
        rows = rows_from(votes)
        if not rows:
            dropped += 1
            continue
        yes = sum(r[1] for r in rows)
        total = sum(sum(r) for r in rows)
        if yes == 0 or yes == total:            # 0% or 100% presence → no variance
            dropped += 1
            continue
        kept.extend(rows)
    return kept, dropped, len(item_votes)


def verdict(k_rubric, k_holistic):
    if k_rubric != k_rubric:                     # NaN
        return 'INCONCLUSIVE (κ undefined)'
    if k_rubric >= 0.60 and (k_rubric - k_holistic) >= 0.30:
        return 'INSTRUMENT WORKS'
    if k_rubric < 0.40:
        return 'INSTRUMENT FAILS'
    return 'INCONCLUSIVE'


def report(name, rubric_rows, holistic_rows, dropped, n_items):
    kr = fleiss_kappa(rubric_rows) if rubric_rows else float('nan')
    kh = fleiss_kappa(holistic_rows) if holistic_rows else float('nan')
    print(f"\n  ── {name} ──")
    print(f"    rubric   κ = {kr:.3f}   ({len(rubric_rows)} item-judgments, "
          f"{n_items - dropped}/{n_items} items kept)")
    print(f"    holistic κ = {kh:.3f}   ({len(holistic_rows)} answers)")
    if dropped > n_items / 2:
        print(f"    ⚠ {dropped}/{n_items} items dropped for no variance → INCONCLUSIVE by the rule")
        return
    print(f"    →  {verdict(kr, kh)}")


# ── offline smoke: validates the SCORING PIPELINE, not the claim ──────────────
def smoke():
    print("measure.py --smoke · validates the pipeline (κ + item dropping), not the claim")
    perfect = [[0, 3]] * 8 + [[3, 0]] * 8                 # every judge agrees
    split = [[1, 2]] * 8 + [[2, 1]] * 8                   # judges maximally split
    print(f"\n  κ invariants:")
    print(f"    unanimous judges      κ = {fleiss_kappa(perfect):.3f}   (expect 1.000)")
    print(f"    maximally split       κ = {fleiss_kappa(split):.3f}   (expect ≤ 0)")
    assert abs(fleiss_kappa(perfect) - 1.0) < 1e-9, 'κ: unanimous must be 1.0'
    assert fleiss_kappa(split) <= 0.0, 'κ: split must be ≤ 0'

    # item dropping: one all-yes item, one all-no item, one that actually varies
    votes = {
        'always':  [[True, True, True]] * 4,
        'never':   [[False, False, False]] * 4,
        'varies':  [[True, True, True], [False, False, False], [True, True, False], [False, False, True]],
    }
    kept, dropped, n = drop_degenerate(votes)
    print(f"\n  item dropping: {dropped}/{n} degenerate items dropped, {len(kept)} rows kept")
    assert dropped == 2 and len(kept) == 4, 'degenerate items must be dropped'

    # decision rule
    print("\n  decision rule:")
    for kr, kh in [(0.72, 0.10), (0.30, 0.10), (0.55, 0.40)]:
        print(f"    rubric {kr:.2f} vs holistic {kh:.2f}  →  {verdict(kr, kh)}")
    assert verdict(0.72, 0.10) == 'INSTRUMENT WORKS'
    assert verdict(0.30, 0.10) == 'INSTRUMENT FAILS'
    assert verdict(0.55, 0.40) == 'INCONCLUSIVE'

    print("\n  ✓ pipeline valid: κ behaves at both extremes, degenerate items drop, the frozen")
    print("    rule separates the three outcomes. Whether a rubric actually agrees is --live.")
    frozen = ', '.join('{} ({} items)'.format(k, len(v['items'])) for k, v in RUBRICS.items())
    print('  rubrics frozen: ' + frozen)


# ── live ──────────────────────────────────────────────────────────────────────
def run_live(n, out):
    import mcp_harness as mh
    import urllib.error
    from datetime import datetime, timezone
    mh.KEY = mh.api_key()
    print(f"measure.py --live · N={n} · {JUDGES} judges · model {mh.MODEL}")
    try:
        mh.call(mh.MODEL, 'Reply with the single word ok.', [{'role': 'user', 'content': 'ok'}], 5)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("\n  ✗ 401 Unauthorized — the key was rejected. Re-run and paste carefully.")
            return
        raise
    print("  ✓ key ok\n")

    records, all_rubric, all_holistic, dropped_total, items_total = [], [], [], 0, 0
    keys = list(RUBRICS)
    for i in range(n):
        rid = keys[i % len(keys)]
        r = RUBRICS[rid]
        answer = mh.call(mh.MODEL, 'You are a thoughtful systems designer. Answer concretely.',
                         [{'role': 'user', 'content': r['task']}], 900)
        holistic = [judge_holistic(mh, r['task'], answer) for _ in range(JUDGES)]
        item_votes = {it: [judge_item(mh, r['task'], answer, it) for _ in range(JUDGES)]
                      for it in r['items']}
        records.append({'rubric_id': rid, 'answer': answer, 'holistic': holistic,
                        'items': {k: v for k, v in item_votes.items()}})
        kept, dropped, n_items = drop_degenerate({k: [v] for k, v in item_votes.items()})
        all_rubric.extend(kept)
        all_holistic.extend(rows_from([holistic]))
        dropped_total += dropped
        items_total += n_items
        agree = sum(1 for v in item_votes.values() if len(set(x for x in v if x is not None)) == 1)
        print(f"  [{i+1}/{n}] {rid:8} holistic={holistic}  items unanimous: {agree}/{len(r['items'])}")

    if out:
        with open(out, 'w') as f:
            json.dump({'when': datetime.now(timezone.utc).isoformat(), 'judges': JUDGES,
                       'rubrics': RUBRICS, 'records': records}, f, indent=2)
        print(f"\n  wrote {out} — every judgment kept, re-scorable without re-running models")
    report('LIVE · instrument comparison', all_rubric, all_holistic, dropped_total, items_total)


if __name__ == '__main__':
    if '--live' in sys.argv:
        n = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else 20
        o = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
        run_live(n, o)
    else:
        smoke()
