#!/usr/bin/env python3
"""Measure drift against unattended runtime, and freeze it as a calibration.

    python3 calibrate_attention.py            # write attention.json
    python3 calibrate_attention.py --check    # exit 1 if the file is stale

WHAT THIS IS FOR

Detection is a theorem and the return is measured, but the one finding here that is both
powered and nobody else's is simpler than either: drift is a function of how long the
agent has been running unattended.

The rate climbs monotonically from zero under a minute to most readings past half an hour,
and the rise between the two best-powered bands is several sigma.

No figure is quoted in this docstring on purpose. A draft of it carried the four rates and
a z, and they were stale by the time the file first ran — the corpus had grown by a day,
and the z was additionally computed between the wrong pair of bands. The numbers live in
attention.json, which is written from the corpus and checked against it. A docstring
cannot be.

That is a schedule, not a score. It says when a person should look, without asking the
instrument whether this particular step is drifting -- which matters, because the
instrument's precision on clearly-labelled fires is 14.6% while this curve is clean.

WHY IT IS NOT IN grammar.json

grammar.json carries `immutable` as a key, and means it: the stopwords, the stem rule, the
verdicts, the thresholds. This table is the opposite kind of object. It is measured, it
moves as the corpus grows, and it is supposed to be recomputed. Freezing an empirical
calibration inside the frozen grammar would make every recalibration look like a grammar
change, and the content_hash gate would fight it every time.

WHY THE NUMBERS ARE NOT TYPED

Same reason paper-frozen-ground/build.py computes its figures: a file that can drift will.
Every band here is counted from the live corpus at write time, `--check` turns staleness
into a failing build, and the provenance block records the corpus span and the sample size
behind each band so a stale table is legible rather than merely wrong.

TWO CORRECTIONS, BOTH OF WHICH COST THE RESULT

  FRESH GROUND    A reading taken on or straight after a reground/grounded is scored
                  against a ground that was just reset, so it cannot drift by
                  construction. Dropped. Keeping them would manufacture the low end of the
                  curve -- and they are also where redirect-driven fires live, which is a
                  different phenomenon measured separately in calibrate_attention's
                  `fresh_ground` block rather than mixed into the schedule.

  ATTRIBUTION     A reading belongs to the most recent user message before it. No window
                  beyond the band edges, and a reading with no message before it at all is
                  dropped rather than assigned to the start of time.

WHAT IT DOES NOT SUPPORT

The corpus is 92% one agent. This is a calibration for THIS setup, and the provenance
block says so in the file so that nobody reads it as a constant of nature.
"""
import argparse
import bisect
import collections
import datetime
import glob
import json
import math
import os
import pathlib
import sys

DRIFT = pathlib.Path(os.environ.get('LASERBRAIN_DRIFT_LOG')
                     or pathlib.Path.home() / '.config/laserbrain/drift-log.jsonl')
TRANSCRIPTS = pathlib.Path(os.environ.get('LASERBRAIN_TRANSCRIPTS')
                           or pathlib.Path.home() / '.claude/projects')
OUT = pathlib.Path(__file__).resolve().parent / 'attention.json'

# Edges in seconds. Finer at the short end because that is where a scheduler has to make
# its decision, and there is no point resolving beyond half an hour -- past that the advice
# is the same however long it has been.
BANDS = [(0, 60, 'under a minute'), (60, 300, '1-5 minutes'),
         (300, 1800, '5-30 minutes'), (1800, 10 ** 9, 'over 30 minutes')]

# A band needs this many readings before it is allowed to carry a rate. Below it the band
# is written with rate: null rather than a number computed from nothing -- the same refusal
# sensitivity.py makes about d-prime.
MIN_N = 20


def when(s):
    return datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))


def user_messages():
    """Timestamps of every user turn, top-level and mid-work alike."""
    out = set()
    for f in glob.glob(str(TRANSCRIPTS / '**' / '*.jsonl'), recursive=True):
        try:
            for line in open(f, errors='replace'):
                if '"queue-operation"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get('operation') == 'enqueue' and d.get('timestamp'):
                    out.add(d['timestamp'])
        except OSError:
            continue
    return sorted(when(s) for s in out)


def readings():
    if not DRIFT.exists():
        return []
    rows = [json.loads(l) for l in DRIFT.read_text().splitlines() if l.strip()]
    return sorted((r for r in rows if r.get('ts') and r.get('drifting') is not None),
                  key=lambda r: r['ts'])


def split(rows):
    """(settled, fresh) -- readings on a ground that has held, and ones on a new one."""
    by_run = collections.defaultdict(list)
    for r in rows:
        by_run[r.get('run')].append(r)
    settled, fresh = [], []
    for seq in by_run.values():
        for i, r in enumerate(seq):
            new = (r.get('reason') in ('reground', 'grounded')
                   or (i and seq[i - 1].get('reason') in ('reground', 'grounded')))
            (fresh if new else settled).append(r)
    return settled, fresh


def tabulate(rows, speaks):
    out = []
    for lo, hi, label in BANDS:
        drift = n = 0
        for r in rows:
            t = when(r['ts'])
            i = bisect.bisect_right(speaks, t)
            if not i:
                continue                      # nothing said before it; not attributable
            gap = (t - speaks[i - 1]).total_seconds()
            if lo <= gap < hi:
                n += 1
                drift += r.get('reason') == 'goal-drift'
        out.append({'label': label, 'from_seconds': lo,
                    'to_seconds': None if hi > 10 ** 8 else hi,
                    'drift': drift, 'n': n,
                    'rate': round(drift / n, 4) if n >= MIN_N else None,
                    'underpowered': n < MIN_N})
    return out


def two_proportion_z(a, b):
    if not (a['n'] and b['n']):
        return None
    pool = (a['drift'] + b['drift']) / (a['n'] + b['n'])
    se = math.sqrt(pool * (1 - pool) * (1 / a['n'] + 1 / b['n']))
    return round((b['drift'] / b['n'] - a['drift'] / a['n']) / se, 3) if se else None


def _best_powered(bands):
    """The strongest adjacent comparison the table can support, named as such.

    Adjacent because the claim is that the curve RISES with unattended time; comparing two
    non-neighbouring bands would skip whatever happens between them. Largest total n
    because the outer bands are thin — "over 30 minutes" is 22 readings — and a result that
    rested on those would be a result about 22 readings.
    """
    ok = [b for b in bands if not b['underpowered']]
    pairs = [(a, b) for a, b in zip(ok, ok[1:])]
    if not pairs:
        return {'z_between_best_powered': None, 'best_powered_pair': None}
    a, b = max(pairs, key=lambda p: p[0]['n'] + p[1]['n'])
    return {'z_between_best_powered': two_proportion_z(a, b),
            'best_powered_pair': [a['label'], b['label']],
            'best_powered_n': a['n'] + b['n']}


def build():
    rows = readings()
    if not rows:
        print(f'  no corpus at {DRIFT} — refusing to write a calibration with nothing '
              'behind it.')
        return None
    speaks = user_messages()
    if not speaks:
        print(f'  no transcripts under {TRANSCRIPTS} — the join needs user-message '
              'timestamps, and without them every band would be empty.')
        return None

    settled, fresh = split(rows)
    bands = tabulate(settled, speaks)
    powered = [b for b in bands if not b['underpowered']]

    agents = collections.Counter(r.get('agent') for r in rows)
    top = agents.most_common(1)[0] if agents else ('unknown', 0)
    ts = [r['ts'] for r in rows]

    return {
        'laserbrain_attention': 1,
        'kind': 'calibration',
        'immutable': False,
        'what': ('Rate at which a reading is goal-drift, against how long the agent has '
                 'run since the user last spoke. Measured, not decreed — recompute with '
                 'calibrate_attention.py.'),
        'bands': bands,
        'min_n': MIN_N,
        # THE TWO LARGEST BANDS, and adjacent — not simply the first two that clear MIN_N.
        # Taking powered[0], powered[1] compared "under a minute" (n=29) against "1-5
        # minutes" and reported z = 2.60 under a key that claims to be the best-powered
        # comparison. The honest one is 1-5 vs 5-30, which together hold most of the
        # corpus. The extreme bands are small, and the claim must not rest on them.
        **_best_powered(bands),
        'fresh_ground': {
            'what': ('The same table over readings on a ground that was just set. Kept '
                     'OUT of the schedule: a reading cannot drift from a ground reset one '
                     'step ago, so including it would manufacture the low end. Recorded '
                     'because redirect-driven fires live here and are worth watching.'),
            'bands': tabulate(fresh, speaks),
        },
        'provenance': {
            'written': datetime.date.today().isoformat(),
            'corpus_from': ts[0][:10], 'corpus_to': ts[-1][:10],
            'readings_total': len(rows),
            'readings_settled': len(settled), 'readings_fresh_ground': len(fresh),
            'user_messages': len(speaks),
            'dominant_agent': top[0], 'dominant_agent_share': round(top[1] / len(rows), 3),
            'caveat': ('One machine, and %.0f%% one agent. This calibrates THIS setup. It '
                       'is not a constant of nature and should be recomputed anywhere '
                       'else.' % (top[1] / len(rows) * 100)),
        },
    }


def compare(cur, fresh, tolerance):
    """What has changed enough to matter. Empty list means the table still holds.

    WHY THIS IS NOT AN EQUALITY CHECK, unlike paper-frozen-ground/build.py

    That file compares its render byte for byte, and should: its corpus changes when
    someone deliberately relabels something. This one reads the live drift log, which
    grows every few seconds while an agent is working — the first version of this check
    was written, passed, and was STALE inside the same session that wrote it. A gate that
    is red by construction gets switched off, and then nothing is checked at all.

    So the question is not "have the counts moved" — they always have — but "does the
    shipped table still describe the corpus". Three ways it can stop:

      A RATE MOVED       past `tolerance` in absolute terms. 19% becoming 21% changes no
                         decision; 19% becoming 40% moves every check-in time in the band.
      A BAND CHANGED KIND   powered <-> underpowered. That flips a real number to null or
                         back, which changes whether the scheduler will answer at all.
      THE SHAPE CHANGED  bands added, removed or relabelled. Then it is a different table
                         and nothing about it is comparable.
    """
    out = []
    a = {b['label']: b for b in cur.get('bands', [])}
    b = {x['label']: x for x in fresh.get('bands', [])}
    if set(a) != set(b):
        return [f'bands differ: shipped {sorted(a)} vs measured {sorted(b)}']
    for label in b:
        old, new = a[label], b[label]
        if (old.get('rate') is None) != (new.get('rate') is None):
            out.append(f'{label}: '
                       + ('gained' if old.get('rate') is None else 'lost')
                       + f' a usable rate (n {old.get("n")} -> {new.get("n")})')
            continue
        if old.get('rate') is None:
            continue
        if abs(old['rate'] - new['rate']) > tolerance:
            out.append(f'{label}: {old["rate"] * 100:.1f}% -> {new["rate"] * 100:.1f}% '
                       f'(n {old.get("n")} -> {new.get("n")})')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='exit 1 if attention.json no longer describes the corpus')
    ap.add_argument('--tolerance', type=float, default=0.05,
                    help='how far a band rate may move before the table counts as stale '
                         '(default 0.05, i.e. five percentage points)')
    a = ap.parse_args()
    fresh = build()
    if fresh is None:
        return 1

    if a.check:
        if not OUT.exists():
            print(f'  MISSING — {OUT.name} has never been written. Run: python3 '
                  f'{pathlib.Path(__file__).name}')
            return 1
        drifted = compare(json.loads(OUT.read_text()), fresh, a.tolerance)
        if drifted:
            print(f'  STALE — {OUT.name} no longer describes the corpus:')
            for line in drifted:
                print(f'    {line}')
            print(f'  Run: python3 {pathlib.Path(__file__).name}')
            return 1
        print(f'  {OUT.name} still describes the corpus (rates within '
              f'{a.tolerance:.0%}).')
        return 0

    OUT.write_text(json.dumps(fresh, indent=2) + '\n')
    print(f'  wrote {OUT}')
    for b in fresh['bands']:
        rate = 'underpowered' if b['rate'] is None else f"{b['rate'] * 100:.1f}%"
        print(f"    {b['label']:<16} {b['drift']:>4}/{b['n']:<5} {rate}")
    pair = fresh.get('best_powered_pair')
    print(f"    z = {fresh['z_between_best_powered']} between {pair[0]} and {pair[1]}"
          f" (n = {fresh.get('best_powered_n')})" if pair else '    z: not computable')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
