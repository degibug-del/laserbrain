#!/usr/bin/env python3
"""turn_dev_eval.py — the turnwatch judge (turn_match_llm.py) on the realdrift DEV set.

DEV, NOT HELD OUT. The realdrift labels (eval/realdrift/, gitignored: blind labels by 35 agents,
skeptic-checked; research/DAY-FIVE-REAL-SESSIONS.md) were known before the turnwatch prompt was
written, and the threshold is picked here, on the same turns. Every number this prints is a
development number. The honest test is prospective: the frozen check, watch-only, on turns after
the freeze (python/laserbrain/hooks/lb_turnwatch.py, research/eval/turnwatch_report.py).

ROWS are built the way the live hook builds them: turn_match_llm.parse_records() over the main
transcript, then, for the FIRST check_state after each delivered user message,
turn_match_llm.build_row(). The one difference: the live worker reads only the transcript's
tail (16-64 MB), this reads the whole file, so a live row can show fewer earlier messages.
A labelled turn (eval/realdrift/turns.jsonl) is joined to a row by its message text and time.
A judged turn with no check_state after its message is NOT REACHED: the live trigger never
fires there, and it counts as a miss in `recall (all drift turns)`.

CALLS. Only rows of judged turns are scored, through ask_match_llm's sandboxed `claude -p`
backend (no settings, hooks disabled, no tools), cached by prompt hash in eval/llm-cache/
(gitignored), so a re-run makes no calls. A ledger in the output folder caps the calls made
across runs (--max-calls, default 700). Outputs (rows and replies quote real messages) go to
eval/turnwatch-dev/, which is gitignored.

Usage:
  turn_dev_eval.py --transcript MAIN.jsonl --data eval/realdrift --dry-run     # rows + join, no calls
  turn_dev_eval.py --transcript MAIN.jsonl --data eval/realdrift               # score (calls)
  turn_dev_eval.py --transcript MAIN.jsonl --data eval/realdrift --cache-only --grid
  turn_dev_eval.py --transcript MAIN.jsonl --data eval/realdrift --cache-only --freeze eval/turnwatch-frozen.json
"""
import argparse
import collections
import concurrent.futures as cf
import hashlib
import importlib.util
import itertools
import json
import pathlib
import random
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ask_match_llm as aml                            # noqa: E402
import turn_match_llm as tm                            # noqa: E402

REPO = HERE.parents[1]
DEFAULT_OUT = REPO / 'eval' / 'turnwatch-dev'
DEFAULT_CACHE = REPO / 'eval' / 'llm-cache'
DEV_END = '2026-11-16'                  # the labelled window ends 2026-11-15
CUT = '2026-10-17'                      # ...and starts here (extract_turns.CUT)


def load_score_real(data_dir):
    p = pathlib.Path(data_dir) / 'score_real.py'
    spec = importlib.util.spec_from_file_location('score_real_dev', str(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _lines_until(path, end):
    """Transcript lines, stopping at the first one stamped at or after `end`."""
    key = '"timestamp":"'
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            i = line.find(key)
            if i >= 0 and line[i + len(key):i + len(key) + 10] >= end:
                break
            yield line


def _norm(t):
    return ' '.join(str(t or '').split())[:200]


def build_rows(transcript, window_s=tm.FIRST_WORDS_WINDOW_S):
    sid = pathlib.Path(transcript).stem
    events = tm.parse_records(_lines_until(transcript, DEV_END))
    rows = []
    for ci, ui in tm.first_checks(events):
        r = tm.build_row(events, ci, sid, window_s=window_s)
        if r is not None:
            rows.append(r)
    return events, rows


def join(rows, turns):
    """{tid: row}: each row to the labelled turn whose message it is (same text, the turn's time
    at or before the delivery and within 12 h). A tid keeps its first row."""
    idx = collections.defaultdict(list)
    for t in turns:
        idx[_norm(t['msg'])].append((t['ts'], t['tid']))
    out, unmatched = {}, 0
    for r in rows:
        if str(r['msg_ts']) < CUT:
            continue
        cands = [(ts, tid) for ts, tid in idx.get(_norm(r['msg']), [])
                 if ts <= r['msg_ts'] and (tm._secs(r['msg_ts']) or 0) - (tm._secs(ts) or 0) <= 12 * 3600]
        if not cands:
            unmatched += 1
            continue
        tid = max(cands)[1]
        if tid not in out:
            out[tid] = r
    return out, unmatched


class Ledger:
    """Model calls made across runs, capped. A call past the cap raises BackendUnavailable."""

    def __init__(self, path, cap):
        self.path, self.cap = pathlib.Path(path), cap
        self.lock = threading.Lock()
        try:
            self.n = int(json.loads(self.path.read_text()).get('calls', 0))
        except Exception:
            self.n = 0

    def take(self):
        with self.lock:
            if self.n >= self.cap:
                return False
            self.n += 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({'calls': self.n, 'cap': self.cap, 'at': tm.now_iso()}))
            return True


class Budgeted:
    def __init__(self, inner, ledger):
        self.inner, self.ledger = inner, ledger
        self.name = getattr(inner, 'name', '?')
        self.credential = getattr(inner, 'credential', None)

    def call(self, system, prompt, schema):
        if not self.ledger.take():
            raise aml.BackendUnavailable(f'call budget of {self.ledger.cap} reached')
        return self.inner.call(system, prompt, schema)


def score(rows, backend, cache, concurrency=4, retries=1, log=print):
    """{row id: cache record or {'error'}}. Cached replies are reused."""
    results, jobs = {}, []
    for r in rows:
        system, prompt, schema = tm.render(r)
        key = aml.cache_key(tm.MODEL, system, prompt, schema)
        hit = cache.get(key)
        if hit and hit.get('response') is not None:
            results[r['id']] = hit
        else:
            jobs.append((r, key, system, prompt, schema))
    log(f'  {len(results)} cached, {len(jobs)} to call')
    if not jobs:
        return results
    if backend is None:
        for r, *_ in jobs:
            results[r['id']] = {'error': 'not cached'}
        return results
    stop = threading.Event()

    def work(job):
        r, key, system, prompt, schema = job
        if stop.is_set():
            return r, {'error': 'stopped'}
        t0 = time.time()
        try:
            res, resp, tries = tm.call_turn(backend, system, prompt, schema, retries=retries)
        except aml.BackendUnavailable as e:
            stop.set()
            return r, {'error': f'unavailable: {e}'}
        except aml.TransientError as e:
            return r, {'error': str(e)[:300]}
        rec = {'at': tm.now_iso(), 'key': key, 'model': tm.MODEL, 'backend': backend.name,
               'scorer': tm.SCORER, 'prompt_hash': tm.prompt_hash(), 'row_id': r['id'],
               'response': resp, 'text': res['text'], 'usage': res.get('usage'),
               'meta': res.get('meta'), 'tries': tries, 'elapsed_s': round(time.time() - t0, 2)}
        cache.put(key, rec)
        return r, rec

    done = 0
    with cf.ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        for f in cf.as_completed([ex.submit(work, j) for j in jobs]):
            r, rec = f.result()
            results[r['id']] = rec
            done += 1
            if done % 20 == 0 or done == len(jobs):
                errs = sum(1 for v in results.values() if v.get('error'))
                log(f'  {done}/{len(jobs)} called ({errs} errors)')
    return results


def metrics(judged, reached, results, th, sr):
    """Confusion counts for thresholds `th`. judged: {tid: is_drift}; reached: {tid: row}."""
    flags, scored = {}, {}
    for tid, row in reached.items():
        rec = results.get(row['id']) or {}
        if rec.get('response') is None:
            continue
        scored[tid] = True
        flags[tid] = tm.decide(rec['response'], th, bare=row['bare_approval'])['flag']
    P = sum(judged.values())
    N = len(judged) - P
    tp = sum(1 for t, d in judged.items() if d and flags.get(t))
    fp = sum(1 for t, d in judged.items() if not d and flags.get(t))
    p_reached = sum(1 for t, d in judged.items() if d and t in scored)
    n_reached = sum(1 for t, d in judged.items() if not d and t in scored)
    return {'positives': P, 'negatives': N, 'positives_reached': p_reached,
            'negatives_reached': n_reached, 'tp': tp, 'fp': fp,
            'recall_all': round(tp / P, 3) if P else None, 'recall_all_ci': sr.wilson(tp, P),
            'recall_reached': round(tp / p_reached, 3) if p_reached else None,
            'false_flag_rate_reached': round(fp / n_reached, 4) if n_reached else None,
            'false_flag_ci_reached': sr.wilson(fp, n_reached),
            'precision': round(tp / (tp + fp), 3) if tp + fp else None}


GRID = {'min_drift_score': [30, 40, 50, 60, 70, 80, 90],
        'flag_verdicts': [['narrowing', 'substitution', 'misread'], ['substitution', 'misread'],
                          ['misread']],
        'substituted_flags': [True, False],
        'ambiguous_min_score': [0, 50],
        'ambiguous_needs_bare': [True, False]}


def grid(judged, reached, results, sr):
    keys = list(GRID)
    table = []
    for combo in itertools.product(*(GRID[k] for k in keys)):
        th = dict(zip(keys, combo))
        m = metrics(judged, reached, results, th, sr)
        table.append({'thresholds': th, **{k: m[k] for k in ('tp', 'fp', 'recall_all', 'recall_reached',
                                                          'false_flag_rate_reached', 'precision')}})
    table.sort(key=lambda t: (-t['tp'], t['fp']))
    return table


def per_score(judged, reached, results, sr, base=None):
    """The frozen rule with only min_drift_score varied: the per-threshold table."""
    base = dict(base or tm.THRESHOLDS)
    out = []
    for s in GRID['min_drift_score']:
        th = dict(base, min_drift_score=s)
        m = metrics(judged, reached, results, th, sr)
        out.append({'min_drift_score': s, **{k: m[k] for k in ('tp', 'fp', 'recall_all', 'recall_reached',
                                                               'false_flag_rate_reached', 'precision')}})
    return out


FROZEN_NOTE = (
    'Picked on the realdrift DEV set (one session, 2026-10-17..11-15), whose labels were known before '
    'the prompt was written. These are DEV numbers, not a held-out result; the honest test is '
    'prospective, on turns after this date. Each catch rests on ONE turn: min_drift_score sits where '
    'the non-bare catch scored in run 1 (90; 40 in run 2), and ambiguous_min_score 0 lets in the '
    'bare-approval catch, which scored 35 in both runs. Read flags with their reasons: at 40, about 3 '
    'of the 8 run-1 false flags had factually wrong reasons and 3 more were deferred side questions, '
    'which the prompt says not to flag, and the non-bare catch has the same shape as two of them.')
SELECTION_RULE = ('the most drift turns caught in both of two runs of the same prompt, with at most '
                  '5% false flags in the worse run, then the fewest false flags in the worse run')
MAX_FALSE_FLAG_RATE = 0.05


def select_threshold(two_run, max_rate=MAX_FALSE_FLAG_RATE):
    """SELECTION_RULE over a COMPLETE two-run table: the min_drift_score it picks, or None when
    no threshold keeps the worse run at max_rate or less. Ties: fewer false flags over both runs,
    then the lower threshold."""
    ok = [r for r in two_run or [] if r.get('false_flag_rate_worse_run') is not None
          and r['false_flag_rate_worse_run'] <= max_rate]
    if not ok:
        return None
    best = max(r['tp_both_runs'] for r in ok)
    return min((r for r in ok if r['tp_both_runs'] == best),
               key=lambda r: (max(r['fp_run1'], r['fp_run2']), r['fp_run1'] + r['fp_run2'],
                              r['min_drift_score']))['min_drift_score']


def two_run_table(judged, reached, first, second, base=None):
    """Per min_drift_score: catches and false flags of run 1 (`first`) and run 2 (`second`),
    {tid: reply} each. Only turns with a reply in BOTH runs count: a run-2 slot is never filled
    with the run-1 reply (which made run-1 flags look stable and hid run-2 flags elsewhere)."""
    base = dict(base or tm.THRESHOLDS)
    both_rows = [t for t in reached if first.get(t) and second.get(t)]
    n_neg = sum(1 for t in both_rows if not judged[t])
    out = []
    for s in GRID['min_drift_score']:
        th = dict(base, min_drift_score=s)
        f1 = {t: tm.decide(first[t], th, bare=reached[t]['bare_approval'])['flag'] for t in both_rows}
        f2 = {t: tm.decide(second[t], th, bare=reached[t]['bare_approval'])['flag'] for t in both_rows}
        fp1 = sum(1 for t in both_rows if not judged[t] and f1[t])
        fp2 = sum(1 for t in both_rows if not judged[t] and f2[t])
        out.append({'min_drift_score': s,
                    'tp_run1': sum(1 for t in both_rows if judged[t] and f1[t]),
                    'tp_run2': sum(1 for t in both_rows if judged[t] and f2[t]),
                    'tp_both_runs': sum(1 for t in both_rows if judged[t] and f1[t] and f2[t]),
                    'fp_run1': fp1, 'fp_run2': fp2,
                    'false_flag_rate_worse_run': round(max(fp1, fp2) / n_neg, 4) if n_neg else None})
    return out


def repeat_check(a, out, judged, reached, results, log, backend=None):
    """A second run of the same prompt, bypassing the dev cache (replies are kept in
    <out>/repeat-cache, so the first replies stay the dev replies and a re-run makes no calls).

    --repeat all (the default for a freeze) re-scores EVERY reached row: the two-run table and
    the threshold rule need run 2 on every row. --repeat N re-scores only N rows (the reached
    drift turns, the rows run 1 flagged at 30 or more, then a seeded sample): a noise estimate
    for borderline rows, with NO two-run table and no threshold choice."""
    ids = sorted(reached)
    if str(a.repeat).lower() == 'all':
        pick = ids
    else:
        pos = [t for t in ids if judged[t]]
        flagged = [t for t in ids if not judged[t]
                   and tm.decide(results[reached[t]['id']]['response'], dict(tm.THRESHOLDS, min_drift_score=30),
                                 bare=reached[t]['bare_approval'])['flag']]
        rest = [t for t in ids if t not in pos and t not in flagged]
        random.Random(11).shuffle(rest)
        pick = (pos + flagged + rest)[:int(a.repeat)]
    rcache = aml.Cache(out / 'repeat-cache')
    if backend is None and not (a.cache_only or a.freeze):
        ledger = Ledger(out / 'calls-ledger.json', a.max_calls)
        backend = Budgeted(aml.make_backend('claude', tm.MODEL, a.timeout, cache_dir=a.cache), ledger)
    again = score([reached[t] for t in pick], backend, rcache, a.concurrency, a.retries, log=log)
    first = {t: results[reached[t]['id']]['response'] for t in ids}
    second = {t: (again.get(reached[t]['id']) or {}).get('response') for t in pick}
    second = {t: r for t, r in second.items() if r}
    rows = [{'tid': t, 'drift': bool(judged[t]), 'bare_approval': bool(reached[t]['bare_approval']),
             's1': first[t]['drift_score'], 's2': second[t]['drift_score'],
             'v1': first[t]['verdict'], 'v2': second[t]['verdict']} for t in pick if t in second]
    d = sorted(abs(x['s1'] - x['s2']) for x in rows)
    flips = {s: sum(1 for x in rows if (x['s1'] >= s) != (x['s2'] >= s)) for s in GRID['min_drift_score']}
    complete = len(second) == len(ids)
    two_run = two_run_table(judged, reached, first, second) if complete else None
    th = tm.THRESHOLDS
    bare = [t for t in ids if reached[t]['bare_approval']]
    f1 = {t: tm.decide(first[t], th, bare=True)['flag'] for t in bare}
    f2 = {t: tm.decide(second[t], th, bare=True)['flag'] for t in bare if t in second}
    any_flag = [t for t in bare if f1.get(t) or f2.get(t)]
    cost = round(sum(float((v.get('meta') or {}).get('cost_usd') or v.get('cost_usd') or 0)
                     for v in again.values() if isinstance(v, dict) and v.get('response')), 4)
    # Where the run-2 replies came from: this script, or replies made elsewhere with the same
    # prompt and backend and copied into repeat-cache (their record names a `source`).
    sources = collections.Counter(str((again.get(reached[t]['id']) or {}).get('source') or 'turn_dev_eval.py')
                                  for t in pick if t in second)
    return {'n': len(rows), 'of_reached': len(ids), 'complete': complete,
            'what': ('a second run of every reached row' if complete else
                     f'{len(rows)} of {len(ids)} reached rows re-scored: a noise estimate, not a second run'),
            'abs_delta_median': d[len(d) // 2] if d else None,
            'abs_delta_p90': d[int(0.9 * (len(d) - 1))] if d else None, 'abs_delta_max': d[-1] if d else None,
            'verdict_changed': sum(1 for x in rows if x['v1'] != x['v2']),
            'flips_at_threshold': flips, 'two_run': two_run,
            'selected_min_drift_score': select_threshold(two_run) if complete else None,
            'drift_turn_scores': [{k: x[k] for k in ('tid', 'bare_approval', 'v1', 's1', 'v2', 's2')}
                                  for x in rows if x['drift']],
            'bare_approvals': {'reached': len(bare), 'drift': sum(1 for t in bare if judged[t]),
                               'flagged_run1': sum(1 for t in bare if f1.get(t)),
                               'flagged_run2': sum(1 for t in bare if f2.get(t)),
                               'flagged_either_run': len(any_flag),
                               'flagged_either_run_drift': sum(1 for t in any_flag if judged[t])},
            'cost_usd': cost, 'sources': dict(sources), 'rows': rows}


def judge_files():
    """{file name: sha256} of every research/eval module the judge loads when imported alone
    (in a clean interpreter, so this script's own imports do not count). The live hook checks
    each one before it runs anything, and after loading refuses any research/eval module that
    is not in this list."""
    import subprocess
    code = ('import sys, json, pathlib; sys.path.insert(0, %r); import turn_match_llm; '
            'h = pathlib.Path(%r).resolve(); '
            'print(json.dumps(sorted({pathlib.Path(m.__file__).resolve().name '
            'for m in list(sys.modules.values()) if getattr(m, "__file__", None) '
            'and pathlib.Path(m.__file__).resolve().parent == h})))') % (str(HERE), str(HERE))
    names = json.loads(subprocess.run([sys.executable, '-P', '-c', code], capture_output=True, text=True,
                                      check=True, cwd=str(HERE.parent)).stdout)
    return {n: hashlib.sha256((HERE / n).read_bytes()).hexdigest() for n in names}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--transcript', required=True, help='the main session .jsonl the labels came from')
    ap.add_argument('--data', required=True, help='eval/realdrift (turns.jsonl, labels.json, score_real.py)')
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    ap.add_argument('--cache', default=str(DEFAULT_CACHE))
    ap.add_argument('--max-calls', type=int, default=700)
    ap.add_argument('--concurrency', type=int, default=4)
    ap.add_argument('--timeout', type=int, default=60)
    ap.add_argument('--retries', type=int, default=1)
    ap.add_argument('--limit', type=int, help='score only N rows (positives first, then a seeded sample)')
    ap.add_argument('--dry-run', action='store_true', help='build and join rows; no calls')
    ap.add_argument('--cache-only', action='store_true', help='make no calls')
    ap.add_argument('--grid', action='store_true')
    ap.add_argument('--freeze', metavar='FROZEN_JSON')
    ap.add_argument('--repeat', metavar='all|N',
                    help='a second run bypassing the dev cache: "all" re-scores every reached row '
                         '(the two-run table and the threshold rule need it; a freeze requires it); '
                         'N re-scores only N rows (drift turns, run-1 flags, then a seeded sample), '
                         'a noise estimate with no two-run table')
    a = ap.parse_args(argv)
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    sr = load_score_real(a.data)
    truth = sr.build_truth(sr.load_result())[0]
    turns = [json.loads(x) for x in open(pathlib.Path(a.data) / 'turns.jsonl', encoding='utf-8')]
    M = {i: t for i, t in truth.items() if t['item'] == 'M'}
    judged = {i: (t['label'] in sr.POS_M) for i, t in M.items() if t['label'] not in sr.EXCL_M}

    t0 = time.time()
    events, rows = build_rows(a.transcript)
    by_tid, unmatched = join(rows, turns)
    reached = {tid: r for tid, r in by_tid.items() if tid in judged}
    log(f'{len(events)} events, {len(rows)} first-check rows in {time.time() - t0:.0f}s; '
        f'{len(by_tid)} joined to labelled turns ({unmatched} rows unmatched); '
        f'{len(reached)} of {len(judged)} judged turns reached, '
        f'{sum(judged[t] for t in reached)} of {sum(judged.values())} drift turns reached')
    stats = {'events': len(events), 'rows': len(rows), 'joined': len(by_tid), 'unmatched': unmatched,
             'judged': len(judged), 'reached': len(reached),
             'drift_turns': sum(judged.values()), 'drift_reached': sum(judged[t] for t in reached),
             'bare_approval_rows': sum(1 for r in reached.values() if r['bare_approval']),
             'rows_with_first_text': sum(1 for r in reached.values() if r['first_text']),
             'rows_with_proposal': sum(1 for r in reached.values() if r['proposal']),
             'rows_with_doing': sum(1 for r in reached.values() if r['doing'])}
    log(json.dumps(stats))
    with open(out / 'rows.jsonl', 'w', encoding='utf-8') as fh:
        for tid, r in sorted(reached.items()):
            fh.write(json.dumps({'tid': tid, 'label': M[tid]['label'], **r}, ensure_ascii=False) + '\n')
    if a.dry_run:
        return 0

    todo = sorted(reached.items())
    if a.limit:
        pos = [x for x in todo if judged[x[0]]]
        neg = [x for x in todo if not judged[x[0]]]
        random.Random(7).shuffle(neg)
        todo = sorted(pos + neg[:max(0, a.limit - len(pos))])
    cache = aml.Cache(a.cache)
    backend = None
    if not a.cache_only and not a.freeze:
        ledger = Ledger(out / 'calls-ledger.json', a.max_calls)
        try:
            backend = Budgeted(aml.make_backend('claude', tm.MODEL, a.timeout, cache_dir=a.cache), ledger)
        except aml.BackendUnavailable as e:
            log(f'backend unavailable: {e}')
    results = score([r for _, r in todo], backend, cache, a.concurrency, a.retries, log=log)
    errors = sum(1 for _, r in todo if (results.get(r['id']) or {}).get('response') is None)
    cost = round(sum(float(((results.get(r['id']) or {}).get('meta') or {}).get('cost_usd') or 0)
                     for _, r in todo), 4)
    scored_reached = {t: r for t, r in reached.items() if (results.get(r['id']) or {}).get('response')}

    m = metrics(judged, scored_reached, results, tm.THRESHOLDS, sr)
    table = per_score(judged, scored_reached, results, sr)
    summary = {'at': tm.now_iso(), 'DEV_NOT_HELD_OUT': True, 'thresholds': tm.THRESHOLDS,
               'prompt_hash': tm.prompt_hash(), 'turn_match_llm_sha256': tm.file_sha(),
               'stats': stats, 'scored': len(scored_reached), 'errors': errors, 'cost_usd': cost,
               'metrics': m, 'per_threshold': table}
    pos_items = []
    for tid in sorted(t for t, d in judged.items() if d):
        r = reached.get(tid)
        rec = (results.get(r['id']) or {}) if r else {}
        d = tm.decide(rec['response'], bare=r['bare_approval']) if rec.get('response') else None
        pos_items.append({'tid': tid, 'label': M[tid]['label'], 'kind': M[tid].get('kind'),
                          'reached': bool(r), 'bare_approval': bool(r and r['bare_approval']),
                          'verdict': d and d['verdict'], 'drift_score': d and d['drift_score'],
                          'flag': d and d['flag']})
    summary['positive_items'] = pos_items
    fps = []
    for tid, r in sorted(scored_reached.items()):
        if judged[tid]:
            continue
        d = tm.decide(results[r['id']]['response'], bare=r['bare_approval'])
        if d['flag']:
            fps.append({'tid': tid, 'verdict': d['verdict'], 'drift_score': d['drift_score'],
                        'bare_approval': r['bare_approval']})
    summary['false_flags'] = fps
    summary['verdicts_on_clean'] = dict(collections.Counter(
        results[r['id']]['response']['verdict'] for t, r in scored_reached.items() if not judged[t]))
    if a.grid:
        summary['grid'] = grid(judged, scored_reached, results, sr)[:30]
    if a.repeat:
        summary['repeat'] = repeat_check(a, out, judged, scored_reached, results, log)
    (out / 'summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    with open(out / 'scored.jsonl', 'w', encoding='utf-8') as fh:
        for tid, r in sorted(scored_reached.items()):
            fh.write(json.dumps({'tid': tid, 'label': M[tid]['label'], 'row': r,
                                 'reply': results[r['id']]['response'],
                                 'decision': tm.decide(results[r['id']]['response'],
                                                       bare=r['bare_approval'])},
                                ensure_ascii=False) + '\n')
    print(json.dumps({k: summary[k] for k in ('stats', 'scored', 'errors', 'cost_usd', 'metrics',
                                              'per_threshold', 'positive_items', 'false_flags',
                                              'verdicts_on_clean')}, indent=1))
    if a.grid:
        print(json.dumps(summary['grid'][:15], indent=1))
    if a.repeat:
        print(json.dumps({k: v for k, v in summary['repeat'].items() if k != 'rows'}, indent=1))
        if summary['repeat'].get('complete'):
            log(f"selection rule picks min_drift_score {summary['repeat']['selected_min_drift_score']} "
                f"(THRESHOLDS has {tm.THRESHOLDS['min_drift_score']})")

    if a.freeze:
        if errors:
            sys.exit(f'refusing to freeze with {errors} unscored reached turns')
        if a.limit:
            sys.exit('refusing to freeze on a --limit run')
        rep = summary.get('repeat') or {}
        if not rep.get('complete'):
            sys.exit('refusing to freeze without a complete second run (--repeat all, every reached row)')
        if rep.get('selected_min_drift_score') != tm.THRESHOLDS['min_drift_score']:
            sys.exit(f"refusing to freeze: the rule picks min_drift_score {rep.get('selected_min_drift_score')}, "
                     f"turn_match_llm.THRESHOLDS has {tm.THRESHOLDS['min_drift_score']}")
        p = pathlib.Path(a.freeze)
        ledger_calls = (json.loads((out / 'calls-ledger.json').read_text()).get('calls')
                        if (out / 'calls-ledger.json').exists() else None)
        imported = sum(n for k, n in (rep.get('sources') or {}).items() if k != 'turn_dev_eval.py')
        block = {
            'frozen': {
                'at': tm.now_iso(), 'scorer': tm.SCORER, 'model': tm.MODEL, 'effort': tm.EFFORT,
                'backend': 'claude', 'prompt_hash': tm.prompt_hash(), 'thresholds': tm.THRESHOLDS,
                'limits': tm.LIMITS, 'first_words_window_s': tm.FIRST_WORDS_WINDOW_S,
                'turn_match_llm_sha256': tm.file_sha(), 'ask_match_llm_sha256': aml.file_sha(),
                'eval_files_sha256': judge_files(),
                'note': FROZEN_NOTE,
            },
            'dev': {'at': tm.now_iso(), 'DEV_NOT_HELD_OUT': True, 'judged_turns': len(judged),
                    'drift_turns': sum(judged.values()), 'reached_turns': len(scored_reached),
                    'drift_turns_reached': m['positives_reached'], 'metrics': m,
                    'per_threshold': table, 'scored': len(scored_reached), 'cost_usd': cost,
                    'selection_rule': SELECTION_RULE,
                    'repeat': ({k: v for k, v in summary['repeat'].items() if k != 'rows'}
                               if summary.get('repeat') else None),
                    'model_calls_ledger': ledger_calls,
                    'model_calls_imported': imported,
                    'model_calls_total': (ledger_calls or 0) + imported},
            'prospective': None,
        }
        p.write_text(json.dumps(block, indent=1) + '\n')
        log(f'frozen -> {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
