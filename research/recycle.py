#!/usr/bin/env python3
"""
recycle.py — the preregistered token-recycling study ([[RECYCLE]]).

Does resuming a multi-session task through a COMPRESSED GROUND cost fewer net tokens
than resuming by re-sending the accumulated history?

  arm A  history  : each session receives the transcript so far
  arm B  recycled : each session receives only ground / now / mind, and the history
                    is discarded. Compressing it costs tokens, and those tokens are
                    CHARGED TO B — net, not gross, or this repeats step-count's
                    flattery of the harness.

Frozen before any run (RECYCLE.md): supported iff B's median net tokens is >=20%
lower than A's AND B completes no less often. Completion is a GATE — tokens saved by
an agent that never finishes are not savings.

  python3 recycle.py --smoke
  read -rs K && ANTHROPIC_API_KEY="$K" python3 recycle.py --live --tasks 8 --sessions 3 \
      --out retest_out/recycle.json
"""
import sys, json, re, statistics

SESSIONS = 3          # fixed in advance; task length decides the outcome, so it is not tuned
SAVING_FLOOR = 0.20   # frozen: a smaller saving is not worth a public claim

# Multi-session by construction: too large to finish in one sitting, and each has a
# definite end state so "completed" is checkable rather than judged.
TASKS = [
    "Design a complete governance structure for a lunar research colony of 200 people: authority, recall, succession, resource allocation, dispute resolution, amendment.",
    "Specify a 1000-year archive for civilisation's digital records: medium, format obsolescence, replication, integrity checks, funding, selection policy.",
    "Design a city's water system from source to tap for 500,000 people: capture, treatment, distribution, metering, failure modes, drought policy.",
    "Write a complete curriculum for teaching statistics to adults with maths anxiety: sequence, exercises, assessment, misconception repair.",
    "Design a protocol for transferring a research lab to a new country: equipment, data, staff, ethics approvals, continuity of ongoing studies.",
    "Specify an emergency-response plan for a coastal town facing sea-level rise: triggers, retreat sequencing, funding, holdouts, cultural sites.",
    "Design a fair allocation system for scarce organ transplants: criteria, appeals, gaming resistance, auditability.",
    "Write an onboarding system for a 50-person remote company: first day, first week, mentorship, evaluation, failure handling.",
]

SYS = ("You are working through a large design task across several sessions. Do real "
       "work each session — do not merely plan. When the task is genuinely complete "
       "and every part is specified, begin your reply with the single word COMPLETE.")

COMPRESS = ("Compress your working state so a future session can resume WITHOUT the "
            "transcript. Reply with exactly three lines:\n"
            "GROUND: <the task, as first stated>\n"
            "NOW: <what is done and what remains>\n"
            "MIND: <decisions made and constraints discovered that must not be relitigated>")


def _tok(mh):
    return mh.USAGE['in'] + mh.USAGE['out']


def run_task(mh, task, arm, sessions=SESSIONS, window_chars=120_000):
    """One task, one arm. Returns net tokens, completion, truncation."""
    t0 = _tok(mh)
    completed, truncated = False, False
    convo, carried = [{'role': 'user', 'content': task}], None

    for s in range(sessions):
        if arm == 'B' and carried is not None:
            # resume from the compressed ground alone; the history is gone
            convo = [{'role': 'user', 'content': f"{task}\n\nResuming. Your state:\n{carried}\n\nContinue the work."}]
        # arm A carries the whole transcript; truncate only if it cannot fit — and
        # record that, because a win that only appears after truncation is a
        # different result (RECYCLE.md, threats).
        if arm == 'A':
            size = sum(len(m['content']) for m in convo)
            while size > window_chars and len(convo) > 2:
                convo.pop(1); truncated = True
                size = sum(len(m['content']) for m in convo)

        out = mh.call(mh.MODEL, SYS, convo, 1200)
        convo.append({'role': 'assistant', 'content': out})
        if out.strip().upper().startswith('COMPLETE'):
            completed = True
            break
        if arm == 'B' and s < sessions - 1:
            # the compression call is B's own overhead and is billed to B
            carried = mh.call(mh.MODEL, COMPRESS, convo + [{'role': 'user', 'content': COMPRESS}], 400)
        else:
            convo.append({'role': 'user', 'content': 'Continue the work in the next session.'})

    return {'tokens': _tok(mh) - t0, 'completed': completed, 'truncated': truncated}


def score(rows):
    A = [r for r in rows if r['arm'] == 'A']
    B = [r for r in rows if r['arm'] == 'B']
    mA = statistics.median([r['tokens'] for r in A]) if A else float('nan')
    mB = statistics.median([r['tokens'] for r in B]) if B else float('nan')
    cA = sum(r['completed'] for r in A) / len(A) if A else 0
    cB = sum(r['completed'] for r in B) / len(B) if B else 0
    saving = (mA - mB) / mA if mA else float('nan')
    print(f"\n  arm A (history)  median net tokens {mA:>9,.0f}   completed {cA:.0%}"
          f"   truncated {sum(r['truncated'] for r in A)}/{len(A)}")
    print(f"  arm B (recycled) median net tokens {mB:>9,.0f}   completed {cB:.0%}")
    print(f"  saving: {saving:+.1%}   (floor {SAVING_FLOOR:.0%})")
    if saving >= SAVING_FLOOR and cB >= cA:
        v = 'SUPPORTED — recycling is cheaper and completes no less often'
    elif abs(saving) < SAVING_FLOOR:
        v = 'NULL — the difference is below the preregistered floor'
    elif cB < cA:
        v = 'NEGATIVE — B completes LESS often; a token saving behind a completion loss is not a saving'
    else:
        v = 'NEGATIVE — recycling costs more'
    print(f"  ->  {v}")
    return v


def smoke():
    print("recycle.py --smoke · validates the pipeline and the frozen rule, not the claim")
    cases = [
        ('clear win',      [('A', 100, 1), ('A', 100, 1)], [('B', 70, 1), ('B', 70, 1)]),
        ('below floor',    [('A', 100, 1), ('A', 100, 1)], [('B', 90, 1), ('B', 90, 1)]),
        ('cheaper but incomplete', [('A', 100, 1), ('A', 100, 1)], [('B', 50, 0), ('B', 50, 0)]),
        ('costs more',     [('A', 100, 1), ('A', 100, 1)], [('B', 150, 1), ('B', 150, 1)]),
    ]
    for name, a, b in cases:
        rows = [{'arm': x, 'tokens': t, 'completed': bool(c), 'truncated': False} for x, t, c in a + b]
        print(f"\n  -- {name} --")
        score(rows)
    print("\n  ✓ the rule separates all four outcomes, and a token saving behind a")
    print("    completion loss is correctly refused. The claim itself is --live only.")


def run_live(n_tasks, sessions, out):
    import mcp_harness as mh
    import urllib.error
    from datetime import datetime, timezone
    mh.KEY = mh.api_key()
    print(f"recycle.py --live · {n_tasks} tasks x {sessions} sessions x 2 arms · {mh.MODEL}")
    try:
        mh.call(mh.MODEL, 'Reply with the single word ok.', [{'role': 'user', 'content': 'ok'}], 5)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("\n  ✗ 401 — the key was rejected. Re-run and paste carefully.")
            return
        raise
    print("  ✓ key ok\n")
    rows = []
    for i in range(n_tasks):
        task = TASKS[i % len(TASKS)]
        for arm in ('A', 'B'):
            r = run_task(mh, task, arm, sessions)
            r.update(task=task[:48], arm=arm, i=i)
            rows.append(r)
            print(f"  [{i+1}/{n_tasks}] {arm}  {r['tokens']:>8,} tok  "
                  f"{'done' if r['completed'] else 'unfinished'}"
                  f"{'  TRUNCATED' if r['truncated'] else ''}")
    if out:
        with open(out, 'w') as f:
            json.dump({'when': datetime.now(timezone.utc).isoformat(),
                       'sessions': sessions, 'rows': rows}, f, indent=2)
        print(f"\n  wrote {out} — re-scorable without re-running any model")
    score(rows)


if __name__ == '__main__':
    a = sys.argv
    if '--live' in a:
        run_live(int(a[a.index('--tasks') + 1]) if '--tasks' in a else 8,
                 int(a[a.index('--sessions') + 1]) if '--sessions' in a else SESSIONS,
                 a[a.index('--out') + 1] if '--out' in a else None)
    else:
        smoke()
