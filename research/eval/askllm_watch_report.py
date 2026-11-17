#!/usr/bin/env python3
"""askllm_watch_report.py — summarise the live askllm watch for the end-of-week review.

The watch (python/laserbrain/hooks/lb_askllm_watch.py) scored each helper agent once, at its
first check_state, with the frozen ask_match_llm.py scorer, from 2026-11-15 to 2026-11-22, and
wrote one line per agent to <STATE_DIR>/askllm-watch.jsonl. This prints:

  counts by status (scored / skipped / error), skip reasons, errors
  flags: how many, where, which verdict, drift scores
  per day and per workflow: agents scored and flagged, model calls, cost
  latency: hook milliseconds, call seconds
  which inputs were present (relayed request, user messages, early text)
  every flagged agent with its why, the asks it left out and redacted snippets

Reference: offline (research/DAY-FIVE-REAL-SESSIONS.md) the same scorer caught 10 of 12 drifted
agents, 9 of them at the start, with 8 of 537 false flags (1.5%). The live watch is the
START-ONLY variant, and the offline numbers are NOT a start-only baseline: offline, every
prompt also held the agent's final report, and its first words could come from anywhere in
the finished run ("9 at start" is where the model placed the drift, not what it was shown).
Live prompts have no final report and only the text from the first ~30 s. So the offline
figures are context, not a like-for-like target: a lower catch rate or a different false-flag
rate here may be the missing inputs, not the scorer. To compare fairly, re-score the same
agents offline once they finish (score_fresh.py) and compare the two on the same agents.
A flag here is not a verdict: label the flagged agents (and a sample of the rest) by hand.

Read-only. Snippets in the log were redacted when written; nothing here prints more.

Usage:
  askllm_watch_report.py [--log PATH] [--since YYYY-MM-DD] [--json]
"""
import argparse
import collections
import json
import os
import pathlib
import statistics
import sys

OFFLINE = {'caught': 10, 'positives': 12, 'caught_at_start': 9, 'false_flags': 8, 'negatives': 537}


def default_log():
    d = os.environ.get('LASERBRAIN_STATE_DIR')
    if d:
        base = pathlib.Path(d).expanduser()
    elif os.environ.get('LASERBRAIN_HOME'):
        base = pathlib.Path(os.environ['LASERBRAIN_HOME']).expanduser() / 'sessions'
    else:
        base = pathlib.Path.home() / '.claude' / 'laserbrain'
    return base / 'askllm-watch.jsonl'


def read(path, since=None):
    out = []
    try:
        fh = open(path, encoding='utf-8')
    except OSError:
        return out
    with fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if since and str(r.get('ts') or '') < since:
                continue
            out.append(r)
    return out


def workflow_name(r, cache={}):
    """The workflow's name from the log, else from <session dir>/workflows/<wf>.json, which
    Claude Code writes when the workflow finishes (it usually does not exist at scoring time)."""
    if r.get('workflow_name'):
        return r['workflow_name']
    wf, sd = r.get('workflow'), r.get('session_dir')
    if not wf or not sd:
        return None
    key = (sd, wf)
    if key not in cache:
        name = None
        try:
            p = pathlib.Path(sd) / 'workflows' / f'{wf}.json'
            if p.exists():
                name = json.loads(p.read_text()).get('workflowName')
        except Exception:
            name = None
        cache[key] = name
    return cache[key]


def pct(vals, q):
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    k = min(len(vals) - 1, max(0, int(round(q * (len(vals) - 1)))))
    return vals[k]


def summarise(rows):
    st = collections.Counter(r.get('status') for r in rows)
    scored = [r for r in rows if r.get('status') == 'scored']
    flagged = [r for r in scored if r.get('flag')]
    skips = collections.Counter(r.get('reason') for r in rows if r.get('status') == 'skipped')
    errs = collections.Counter(r.get('reason') for r in rows if r.get('status') == 'error')
    err_examples = {}
    for r in rows:
        if r.get('status') == 'error' and r.get('reason') not in err_examples:
            err_examples[r.get('reason')] = r.get('error')
    per_day = collections.defaultdict(lambda: {'scored': 0, 'flagged': 0, 'calls': 0, 'cost_usd': 0.0})
    for r in rows:
        day = str(r.get('ts') or '')[:10]
        d = per_day[day]
        d['calls'] += int(r.get('calls') or 0)
        d['cost_usd'] += float(r.get('cost_usd') or 0)
        if r.get('status') == 'scored':
            d['scored'] += 1
            d['flagged'] += bool(r.get('flag'))
    per_wf = collections.defaultdict(lambda: {'name': None, 'scored': 0, 'flagged': 0, 'skipped': 0,
                                              'errors': 0, 'labels': set()})
    for r in rows:
        k = r.get('workflow') or '(plain subagent)'
        w = per_wf[k]
        w['name'] = w['name'] or workflow_name(r)
        if r.get('label'):
            w['labels'].add(str(r['label']).split(':')[0])
        s = r.get('status')
        if s == 'scored':
            w['scored'] += 1
            w['flagged'] += bool(r.get('flag'))
        elif s == 'skipped':
            w['skipped'] += 1
        elif s == 'error':
            w['errors'] += 1
    inputs = collections.Counter()
    n_recent = []
    for r in scored:
        for k, v in (r.get('inputs') or {}).items():
            if k == 'user_recent':
                n_recent.append(v)
                inputs['user_recent>0'] += bool(v)
            else:
                inputs[k] += bool(v)
    return {
        'lines': len(rows), 'status': dict(st), 'skip_reasons': dict(skips),
        'error_reasons': dict(errs), 'error_examples': err_examples,
        'scored': len(scored), 'flagged': len(flagged),
        'flag_rate': round(len(flagged) / len(scored), 3) if scored else None,
        'where': dict(collections.Counter(r.get('where') for r in flagged)),
        'verdict': dict(collections.Counter(r.get('verdict') for r in flagged)),
        'drift_score': {'median': statistics.median([r['drift_score'] for r in scored])
                        if scored else None,
                        'ge_50': sum((r.get('drift_score') or 0) >= 50 for r in scored)},
        'inputs_present': dict(inputs), 'user_recent_median': statistics.median(n_recent) if n_recent else None,
        'latency': {'hook_ms_p50': pct([r.get('hook_ms') for r in rows], 0.5),
                    'hook_ms_max': pct([r.get('hook_ms') for r in rows], 1.0),
                    'call_s_p50': pct([r.get('call_s') for r in scored], 0.5),
                    'call_s_max': pct([r.get('call_s') for r in scored], 1.0)},
        'calls': sum(int(r.get('calls') or 0) for r in rows),
        'cost_usd': round(sum(float(r.get('cost_usd') or 0) for r in rows), 4),
        'per_day': {k: {**v, 'cost_usd': round(v['cost_usd'], 4)} for k, v in sorted(per_day.items())},
        'per_workflow': {k: {**v, 'labels': sorted(v['labels'])} for k, v in sorted(per_wf.items())},
        'frozen_shas': sorted({r.get('frozen_sha') for r in rows if r.get('frozen_sha')}),
        'flagged_agents': [{k: r.get(k) for k in ('ts', 'session', 'agent_id', 'workflow', 'label',
                                                   'lane', 'where', 'verdict', 'drift_score', 'why',
                                                   'missing', 'snippets', 'inputs')}
                           for r in flagged],
        'offline_reference': OFFLINE,
    }


def show(s, path):
    p = print
    p(f'askllm watch report  ({path})')
    p(f"  lines {s['lines']}   " + '  '.join(f'{k} {v}' for k, v in sorted(s['status'].items(),
                                                                       key=lambda kv: str(kv[0]))))
    if not s['lines']:
        p('  (no lines yet)')
        return
    fr = f"{s['flag_rate']:.1%}" if s['flag_rate'] is not None else '-'
    p(f"  scored {s['scored']}   flagged {s['flagged']} ({fr})   where {s['where'] or {}}   "
      f"verdict {s['verdict'] or {}}")
    p(f"  drift score median {s['drift_score']['median']}, >= 50: {s['drift_score']['ge_50']}")
    o = s['offline_reference']
    p(f"  offline reference (full-run prompts, not like-for-like): caught {o['caught']} of {o['positives']} ({o['caught_at_start']} placed at start), "
      f"false flags {o['false_flags']} of {o['negatives']} ({o['false_flags'] / o['negatives']:.1%})")
    if s['skip_reasons']:
        p('  skipped: ' + ', '.join(f'{k} {v}' for k, v in sorted(s['skip_reasons'].items(),
                                                                  key=lambda kv: -kv[1])))
    if s['error_reasons']:
        p('  errors:')
        for k, v in sorted(s['error_reasons'].items(), key=lambda kv: -kv[1]):
            p(f"    {v} x {k}: {s['error_examples'].get(k) or ''}"[:220])
    p(f"  inputs present (of {s['scored']} scored): {s['inputs_present']}; "
      f"user messages median {s['user_recent_median']}")
    lt = s['latency']
    p(f"  latency: hook p50 {lt['hook_ms_p50']} ms, max {lt['hook_ms_max']} ms; "
      f"call p50 {lt['call_s_p50']} s, max {lt['call_s_max']} s")
    p(f"  model calls {s['calls']}, cost ${s['cost_usd']}")
    if len(s['frozen_shas']) > 1:
        p(f"  WARNING: more than one frozen sha in the log: {s['frozen_shas']}")
    p('  per day:')
    for day, d in s['per_day'].items():
        p(f"    {day}  scored {d['scored']:3d}  flagged {d['flagged']:2d}  calls {d['calls']:3d}  "
          f"${d['cost_usd']}")
    p('  per workflow:')
    for wf, w in s['per_workflow'].items():
        nm = f" ({w['name']})" if w['name'] else ''
        lb = f" [{', '.join(w['labels'][:4])}]" if w['labels'] else ''
        p(f"    {wf}{nm}{lb}: scored {w['scored']}, flagged {w['flagged']}, skipped {w['skipped']}, "
          f"errors {w['errors']}")
    if s['flagged_agents']:
        p('  flagged agents:')
        for f in s['flagged_agents']:
            sn = f.get('snippets') or {}
            p(f"    {f['ts']}  {str(f['session'])[:8]}  {f['agent_id']}  {f.get('workflow') or '-'}  "
              f"{f.get('label') or f.get('lane') or ''}")
            p(f"      {f['where']} / {f['verdict']} / drift {f['drift_score']}: {f.get('why')}")
            if f.get('missing'):
                p(f"      left out: {'; '.join(str(m) for m in f['missing'])}")
            for k in ('goal', 'relayed', 'latest_user', 'task'):
                if sn.get(k):
                    p(f"      {k}: {sn[k]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--log', default=None, help='default: <STATE_DIR>/askllm-watch.jsonl')
    ap.add_argument('--since', help='only lines at or after this date (YYYY-MM-DD)')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    path = pathlib.Path(a.log) if a.log else default_log()
    s = summarise(read(path, a.since))
    if a.json:
        print(json.dumps(s, indent=1, ensure_ascii=False, default=str))
    else:
        show(s, path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
