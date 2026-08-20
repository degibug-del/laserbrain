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
import statistics
import math
import os
import pathlib
import sys

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
import _root                                                       # noqa: E402

DRIFT = pathlib.Path(os.environ.get('LASERBRAIN_DRIFT_LOG')
                     or _root.config('drift-log.jsonl'))
TRANSCRIPTS = pathlib.Path(os.environ.get('LASERBRAIN_TRANSCRIPTS')
                           or pathlib.Path.home() / '.claude/projects')
OUT = pathlib.Path(__file__).resolve().parent / 'attention.json'

# THE SECOND COPY, and the reason it is named here rather than left to a human.
#
# laserbrain-sdk/laserbrain/attention.json is PACKAGE DATA: it goes out inside the wheel,
# so it is the table every pip-installed agent actually schedules against. This script
# wrote OUT only. On 2026-08-04 a recalibration moved the rates, OUT changed, and the
# shipped copy did not — the two had been byte-identical five minutes earlier and nothing
# would have reported the split. The next release would have carried a table its own
# corpus had already outgrown, and the failure is silent by construction: a stale data
# file raises no error, it just answers an old question confidently.
#
# Byte-identical is the right assertion, not "within tolerance". These are not two
# measurements that ought to agree; they are one artifact stored twice.
SHIPPED = (pathlib.Path(__file__).resolve().parent.parent
           / 'laserbrain-sdk' / 'laserbrain' / 'attention.json')


def _shipped_state(text):
    """(status, detail) for the packaged copy. `text` is what OUT holds or will hold.

    Missing SDK directory is a skip: this script runs on machines that have the corpus and
    not the package, and failing there would train people to ignore it. A missing FILE
    inside an SDK that IS present is a real fault — the package would ship without the
    table it reads.
    """
    if not SHIPPED.parent.exists():
        return 'skip', 'no SDK checkout on this machine'
    if not SHIPPED.exists():
        return 'fail', f'{SHIPPED} is missing — the wheel would ship without its table'
    return ('ok', '') if SHIPPED.read_text() == text else (
        'fail', f'{SHIPPED.name} in the SDK differs from lasermind/{OUT.name}')

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


def _ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except Exception:
        return None


def concurrent_runs(rows):
    """Runs whose lifetimes overlap another run's — i.e. subagents.

    WHY THIS EXISTS. Every band in this table is "time since the last user message", and
    user_messages() is a GLOBAL timeline. A subagent has no user turn of its own, so its
    readings get bucketed against somebody else's — placed on a clock that is not theirs.
    On 2026-08-16 one session spawned 75 workflow subagents and put 289 such rows into the
    corpus, 17% of it in a day. They landed hardest in "under a minute", the band carrying
    the cleanest published claim, taking it from 0.0% (n=57) to 5.6% (n=89).

    WHY CONCURRENCY IS A RULE AND NOT A GUESS. A person's own sessions do not run at the
    same time on one machine; a parent and its children do, by definition. Runs overlapping
    another run, per day across the corpus:

        08-04  0%   08-05  0%   08-06  10%   08-07  0%
        08-08  0%   08-09  0%   08-10   0%   08-16  83.6%

    Validated against a signal that shares no logic with it: matching the goal TEXT against
    the prompts those subagents were actually given. On the contaminated day, text flags 51
    runs and clustering flags 50 of the same 51, with ZERO runs flagged that the text does
    not also flag. One signal is about what an agent was asked, the other about when it ran,
    and they pick out the same set. That is what makes this a discriminator rather than the
    inference session_id_of refuses to make.

    WHY THE PARENT GOES TOO, which was not obvious and took a second finding to settle.
    An earlier version kept the widest run in each cluster, reasoning that the parent is a
    real session with real user turns and its readings are therefore measurable. That is
    true and beside the point: the parent is not a bystander to a concurrent child, it is
    the VICTIM of one. Until this was fixed, a child's reset_task destroyed whatever ground
    was live — usually the parent's — so the parent's subsequent checks were scored against
    a stranger's goal and returned drift that never happened.

    It shows in the rate. On the contaminated day 54 of 110 readings that survived the
    keep-the-parent rule were marked drifting: 49%, against about 17% across the corpus.
    Those verdicts are not measurements of an agent, they are measurements of a defect.

    So both halves of a cluster are corrupt, for two different reasons, and both go:
        children — no user turn of their own, so the band's clock is not theirs
        parents  — ground stolen mid-run, so the verdicts are false

    Containment was also tried and is the leanest: 44 of 51, missing children whose spans
    poke outside the parent's last check. It is kept in the history rather than the code.

    If the host ever sets LASERBRAIN_SESSION_ID per subagent, delete this and read the id.
    """
    span = {}
    for r in rows:
        run, t = r.get('run'), _ts(r.get('ts'))
        if run is None or t is None:
            continue
        a, b = span.get(run, (t, t))
        span[run] = (min(a, t), max(b, t))

    # Sweep by start time, growing a cluster while runs keep overlapping it.
    clusters = []
    for run, (a, b) in sorted(span.items(), key=lambda kv: kv[1][0]):
        for c in clusters:
            if a <= c['end']:
                c['runs'].append((run, a, b))
                c['end'] = max(c['end'], b)
                break
        else:
            clusters.append({'runs': [(run, a, b)], 'end': b})

    out = set()
    for c in clusters:
        if len(c['runs']) < 2:
            continue
        out.update(run for run, _, _ in c['runs'])
    return out


def readings(keep_concurrent=False):
    if not DRIFT.exists():
        return []
    rows = [json.loads(l) for l in DRIFT.read_text().splitlines() if l.strip()]
    rows = sorted((r for r in rows if r.get('ts') and r.get('drifting') is not None),
                  key=lambda r: r['ts'])
    if keep_concurrent:
        return rows
    drop = concurrent_runs(rows)
    return [r for r in rows if r.get('run') not in drop]


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


SESSIONS = _root.sessions_dir()

# Step-gaps between one spelled check and the next.
AGENT_BANDS = [(1, 1, '1 step'), (2, 3, '2-3 steps'), (4, 7, '4-7 steps'),
               (8, 15, '8-15 steps'), (16, 60, '16+ steps')]


def agent_clock():
    """Drift against the AGENT's own clock — steps since it last spelled its state.

    THE HUMAN CLOCK AND THE AGENT CLOCK ARE NOT THE SAME MEASUREMENT, and only one of them
    survives contact with this corpus.

    Time since the user last spoke is an external clock. Nothing in laserbrain controls it,
    so the bands are free to be whatever they are, and they turn out to be strong.

    Steps since the agent's own last check is an INTERNAL clock, and the coverage gate
    forces a check at 4 steps whenever coverage is under floor. So the gate manufactures
    the distribution it would be tuned against: 85% of all gaps land in 4-7 steps, and
    gaps of 8 or more are 0.3% of the sample — five readings. Whether an agent left for
    twelve steps drifts more than one left for four is not a hard question here, it is an
    unaskable one, because the instrument prevents the twelve from happening.

    Inside the range the gate does permit, the effect is small and not significant. That is
    reported rather than buried: a flat result from a censored sample is not evidence that
    the interval does not matter, only that this corpus cannot see it.

    `censored_beyond` records where the sample stops being the world and starts being the
    policy, so nobody reads the tail as a measurement.
    """
    gaps = collections.Counter()
    drift = collections.Counter()
    pairs = 0
    for f in glob.glob(str(SESSIONS / '*.json')):
        try:
            d = json.load(open(f))
        except (OSError, ValueError):
            continue
        for seg in [d] + (d.get('segments') or []):
            checks = sorted((c for c in (seg.get('checks') or []) if c.get('step') is not None),
                            key=lambda c: c['step'])
            for prev, cur in zip(checks, checks[1:]):
                gap = cur['step'] - prev['step']
                if not 1 <= gap <= 60:
                    continue            # a reset between them, or a corrupt pair
                pairs += 1
                gaps[gap] += 1
                drift[gap] += cur.get('reason') == 'goal-drift'
    if not pairs:
        return None

    bands = []
    for lo, hi, label in AGENT_BANDS:
        n = sum(gaps[g] for g in range(lo, hi + 1))
        dd = sum(drift[g] for g in range(lo, hi + 1))
        bands.append({'label': label, 'from_steps': lo, 'to_steps': hi,
                      'drift': dd, 'n': n,
                      'rate': round(dd / n, 4) if n >= MIN_N else None,
                      'underpowered': n < MIN_N})
    long_gaps = sum(gaps[g] for g in range(8, 61))
    return {
        'what': ('Drift against steps since the agent last spelled its own state. Reported '
                 'with its censoring, not as a schedule.'),
        'bands': bands,
        'pairs': pairs,
        # Same key names as the human table. A first version prefixed these with 'agent_'
        # to avoid a collision that cannot happen — the block is already nested under
        # agent_clock — and the only effect was that every reader looking for
        # z_between_best_powered found nothing and printed None.
        **_best_powered(bands),
        'censored_beyond_steps': 8,
        'censored_share': round(long_gaps / pairs, 4),
        'censoring': (
            'The coverage gate forces a check at 4 steps when coverage is under floor, so '
            'gaps of 8+ are %.2f%% of the sample (%d of %d). The distribution is the '
            "gate's policy, not the agent's behaviour, and the interval cannot be "
            'evaluated against data the interval produced. To settle it the gate would '
            'have to let a random share of runs go long on purpose.'
            % (long_gaps / pairs * 100, long_gaps, pairs)),
    }


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


def overhead():
    """What fraction of an agent's tool calls ARE laserbrain.

    THE OTHER HALF OF THE LEDGER. The bands above say what the instrument catches. This
    says what it costs, and nothing on the site said it until 2026-08-05 — a page that
    prints its own nulls beside its proofs had a one-sided ledger on the one number a
    reader is actually spending.

    It is a check_state count over a tool-call count, per run: no A/B, no control arm, no
    inference. Measured across 198 runs it sits at a median 22.2% with an IQR of
    20.9-24.0%, which is tight enough to publish as a constant rather than a mood.

    It is also, unsurprisingly, 1/BLOCK_AFTER. The gate forces a check every four steps to
    hold the coverage floor, so the overhead is not emergent — it is the threshold, and
    changing one changes the other. That is worth a reader knowing before they weigh any
    claim about saved tokens: a benefit has to clear this before it is a benefit at all.

    Runs under ten steps are excluded. A three-step run with one check reads as 33% and
    says nothing about sustained cost.
    """
    ratios = []
    # SESSIONS, not DRIFT. The drift log is one line per reading; the session files
    # carry `steps`, and steps is the denominator — it counts tool calls the log
    # never sees. Globbing the log as a directory silently yielded nothing, and the
    # overhead came out None rather than wrong, which is the quieter failure.
    for path in sorted(SESSIONS.glob('*.json')) if SESSIONS.is_dir() else []:
        try:
            d = json.loads(path.read_text())
        except Exception:
            continue
        for seg in [d] + (d.get('segments') or []):
            checks, steps = seg.get('checks') or [], seg.get('steps') or 0
            if steps >= 10 and checks:
                ratios.append(len(checks) / steps)
    if not ratios:
        return None
    ratios.sort()
    n = len(ratios)
    return {
        'what': ('Share of an agent\'s tool calls that are laserbrain itself. A cost, not '
                 'a benefit — measured so a claim about saved tokens has something to clear.'),
        'runs': n,
        'median': round(statistics.median(ratios), 4),
        'iqr': [round(ratios[n // 4], 4), round(ratios[3 * n // 4], 4)],
        'note': ('Runs under ten steps excluded. Equals roughly 1/BLOCK_AFTER by '
                 'construction: the gate forces a check every four steps to hold the '
                 'coverage floor, so this is the threshold, not an emergent property.'),
    }


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
        # The agent's own clock, reported beside the human one so the contrast is legible:
        # the external clock is strong, the internal clock is flat AND censored by the gate
        # that produced it. Kept in the same file because a reader comparing them is the
        # whole point; split across two files, only the flattering one gets quoted.
        'agent_clock': agent_clock(),
        'overhead': overhead(),
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
    ap.add_argument('--ship', action='store_true',
                    help='also write the packaged copy that goes inside the wheel. Off by '
                         'default: a site build must not mutate published package data as '
                         'a side effect. Run this at publish time, after reading the corpus '
                         'composition printed below it.')
    a = ap.parse_args()
    ship = a.ship
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
        status, detail = _shipped_state(OUT.read_text())
        if status == 'fail':
            print(f'  DIVERGED — {detail}')
            print(f'  Run: python3 {pathlib.Path(__file__).name}')
            return 1
        print(f'  the packaged copy is identical.' if status == 'ok'
              else f'  packaged copy unchecked — {detail}.')
        return 0

    # WHAT THE CORPUS IS MADE OF, printed before what was concluded from it.
    #
    # On 2026-08-16 a routine site build recalibrated this table and the numbers moved a
    # lot — one band went n=333 -> 495. The cause was one session that had spawned 75
    # workflow subagents: 436 rows in a day against a previous daily high of 180, 17% of the
    # whole corpus, across 59 distinct runs. Its most frequent goals were "Adversarially
    # verify ..." and "Sweep .../workers/ ...", which are not agent sessions at all.
    #
    # That matters here specifically, not just aesthetically. Every row is bucketed by time
    # since the nearest user message, and user_messages() is a GLOBAL timeline. A subagent
    # has no user turns of its own, so its readings borrow a user turn from a different
    # session — the x-axis is undefined for them and they are assigned a bucket anyway.
    #
    # This does not try to identify those rows. From in here there is no sound way: a drift
    # row carries run, agent and goal, `agent` is the same string for parent and child, and
    # guessing from run-density would be inventing a discriminator — the same guess the SDK
    # refuses in session_id_of, for the same reason. Excluding the wrong rows is worse than
    # including them, because the exclusion is invisible afterwards.
    #
    # So it REPORTS. A recalibration skewed by one day is now something you see at the
    # moment you run it, rather than something discovered later inside a published wheel.
    # No threshold, nothing refused: this project does not assert numbers it has not
    # measured, and "how skewed is too skewed" has not been measured.
    _all = readings(keep_concurrent=True)
    _rows = readings()
    _dropped = len(_all) - len(_rows)
    if _dropped:
        _druns = concurrent_runs(_all)
        _dd = collections.Counter(str(r.get('ts') or '')[:10] for r in _all
                                  if r.get('run') in _druns)
        print(f'  excluded {_dropped} readings from {len(_druns)} runs that ran concurrently — '
              f'children have no user turn to measure from, and their parents had their '
              f'ground stolen mid-run, so both are corrupt')
        for _d, _n in sorted(_dd.items()):
            print(f'    {_d}  {_n:>5} readings')
    _by_day = collections.Counter(str(r.get('ts') or '')[:10] for r in _rows)
    _runs_by_day = collections.defaultdict(set)
    for _r in _rows:
        _runs_by_day[str(_r.get('ts') or '')[:10]].add(_r.get('run'))
    print(f'  corpus: {len(_rows)} rows over {len(_by_day)} days, '
          f'{len(set(r.get("run") for r in _rows))} runs')
    for _d, _n in sorted(_by_day.items())[-5:]:
        _share = _n / max(len(_rows), 1)
        print(f'    {_d}  {_n:>5} rows  {len(_runs_by_day[_d]):>3} runs  {_share * 100:4.1f}% of corpus'
              + ('   <- dominates; check it is not one session with subagents' if _share > 0.15 else ''))

    text = json.dumps(fresh, indent=2) + '\n'
    OUT.write_text(text)
    print(f'  wrote {OUT}')
    # THE PACKAGED COPY IS NOW OPT-IN, and it took two blocked releases in one afternoon to
    # earn that. "Both, always" was written to stop the two diverging, and it did — at the
    # cost of making every ordinary `npm run build` rewrite a file that ships inside the
    # wheel. On 2026-08-16 that fired twice within an hour: a release was prepared, the
    # provenance gate refused it because attention.json was modified-but-uncommitted, the
    # file was restored, and the next site build dirtied it again immediately.
    #
    # Worse than the inconvenience, the numbers it was writing were skewed — 16% of the
    # corpus was a single session that had spawned 75 workflow subagents, which have no user
    # turns and so cannot be bucketed by time-since-user-turn at all. A build has no idea
    # any of that is true, and package data should not change as a side effect of something
    # that never set out to change it.
    #
    # So the wheel's copy changes at PUBLISH time, deliberately, where the composition report
    # above is read by somebody. Divergence is still guarded: --check compares both.
    if not ship:
        print(f'  packaged copy NOT written (pass --ship). {SHIPPED} unchanged.')
    elif SHIPPED.parent.exists():
        SHIPPED.write_text(text)
        print(f'  wrote {SHIPPED}  (package data — ships in the wheel)')
    else:
        print('  no SDK checkout here, packaged copy not written')
    for b in fresh['bands']:
        rate = 'underpowered' if b['rate'] is None else f"{b['rate'] * 100:.1f}%"
        print(f"    {b['label']:<16} {b['drift']:>4}/{b['n']:<5} {rate}")
    pair = fresh.get('best_powered_pair')
    print(f"    z = {fresh['z_between_best_powered']} between {pair[0]} and {pair[1]}"
          f" (n = {fresh.get('best_powered_n')})" if pair else '    z: not computable')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
