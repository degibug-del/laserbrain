#!/usr/bin/env python3
"""askllm_watch_report.py — summarise the live askllm check (watch, then note mode).

The check (python/laserbrain/hooks/lb_askllm_watch.py) scores each helper agent once, at its
first check_state, with the frozen ask_match_llm.py scorer, and writes one line per agent to
<STATE_DIR>/askllm-watch.jsonl: watch-only from 2026-11-15, then in note mode (the default since
the Unreleased entry after 0.58.0), where a flag also writes a note that reaches the agent and
its parent session, each delivery logged as its own line. This prints:

  counts by status (scored / skipped / error), skip reasons, errors
  flags: how many, where, which verdict, drift scores
  notes: written, delivered to the agent and to the parent, how long after, expired, pending
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

By trigger and by policy: from 2026-11-19 every judge row carries `trigger` and `policy`
(lb_askllm_watch.py's STAMPS), so the counts are also split by each. A row without the field
was written before the stamps went live and counts as 'unstamped'; a row whose policy is null
(LASERBRAIN_POLICY unset) counts as 'none'. Note-delivery lines are not judge rows and are
left out of both splits.

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
PRE_STAMP = 'unstamped'           # a row written before the trigger/policy stamps went live
NO_POLICY = 'none'                # a stamped row whose policy is null (LASERBRAIN_POLICY unset)


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


def stamp_label(r, field):
    """The row's trigger or policy as a group name: PRE_STAMP when the field is absent,
    NO_POLICY when it is present but null."""
    if field not in r:
        return PRE_STAMP
    v = r.get(field)
    return NO_POLICY if v is None or v == '' else str(v)


def by_stamp(rows, field):
    """Judge-row counts grouped by `field` (trigger or policy). Note-delivery lines are left out."""
    out = collections.defaultdict(lambda: {'lines': 0, 'scored': 0, 'flagged': 0, 'skipped': 0,
                                           'errors': 0, 'with_row_sha': 0})
    for r in rows:
        s = str(r.get('status') or '')
        if s.startswith('note_'):
            continue
        g = out[stamp_label(r, field)]
        g['lines'] += 1
        g['with_row_sha'] += bool(r.get('row_sha'))
        if s == 'scored':
            g['scored'] += 1
            g['flagged'] += bool(r.get('flag'))
        elif s == 'skipped':
            g['skipped'] += 1
        elif s == 'error':
            g['errors'] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


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
    # NOTE MODE: a flag writes a note (scored line with note == 'written'); each delivery is its
    # own line (note_delivered_agent / note_delivered_parent), and so is a note that never went
    # out (note_expired_agent / note_expired_parent past its TTL, note_dropped_mode after a switch
    # away from note mode, with kind agent or parent).
    written = [r for r in scored if r.get('note') == 'written']
    deliv = collections.defaultdict(list)
    for r in rows:
        if str(r.get('status') or '').startswith('note_'):
            deliv[r['status']].append(r)
    notes = {
        'modes': dict(collections.Counter(r.get('mode') or 'watch (before note mode)' for r in scored)),
        'written': len(written),
        'write_errors': sum(1 for r in scored if str(r.get('note') or '').startswith('error')),
        'delivered_agent': len(deliv['note_delivered_agent']),
        'delivered_parent': len(deliv['note_delivered_parent']),
        'expired_agent': len(deliv['note_expired_agent']),
        'expired_parent': len(deliv['note_expired_parent']),
        'dropped_mode': len(deliv['note_dropped_mode']),
        'delay_s_p50_agent': pct([r.get('delay_s') for r in deliv['note_delivered_agent']], 0.5),
        'delay_s_p50_parent': pct([r.get('delay_s') for r in deliv['note_delivered_parent']], 0.5),
        'pending': max(0, len(written) - len(deliv['note_delivered_agent']) - len(deliv['note_expired_agent'])
                       - sum(1 for r in deliv['note_dropped_mode'] if r.get('kind') == 'agent')),
        'deliveries': [{k: r.get(k) for k in ('ts', 'status', 'session', 'agent_id', 'label', 'workflow',
                                               'event', 'note_written_ts', 'delay_s')}
                       for k in ('note_delivered_agent', 'note_delivered_parent', 'note_expired_agent',
                                 'note_expired_parent', 'note_dropped_mode')
                       for r in deliv[k]],
    }
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
        'by_trigger': by_stamp(rows, 'trigger'),
        'by_policy': by_stamp(rows, 'policy'),
        'frozen_shas': sorted({r.get('frozen_sha') for r in rows if r.get('frozen_sha')}),
        'flagged_agents': [{k: r.get(k) for k in ('ts', 'session', 'agent_id', 'workflow', 'label',
                                                   'lane', 'where', 'verdict', 'drift_score', 'why',
                                                   'missing', 'snippets', 'inputs')}
                           for r in flagged],
        'offline_reference': OFFLINE,
        'notes': notes,
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
    n = s.get('notes') or {}
    p(f"  notes: modes {n.get('modes')}; written {n.get('written', 0)}"
      f"{' (' + str(n['write_errors']) + ' write errors)' if n.get('write_errors') else ''}, "
      f"delivered to the agent {n.get('delivered_agent', 0)} (p50 {n.get('delay_s_p50_agent')} s after writing), "
      f"to the parent {n.get('delivered_parent', 0)} (p50 {n.get('delay_s_p50_parent')} s), "
      f"expired undelivered: agent {n.get('expired_agent', 0)}, parent {n.get('expired_parent', 0)}; "
      f"dropped on a mode switch {n.get('dropped_mode', 0)}; agent notes still pending {n.get('pending', 0)}")
    for d in (n.get('deliveries') or [])[:20]:
        p(f"    {d['ts']}  {d['status']:22s} {str(d.get('session'))[:8]}  {d.get('agent_id')}  "
          f"{d.get('label') or ''}  on {d.get('event')}  {d.get('delay_s')} s")
    if len(s['frozen_shas']) > 1:
        p(f"  WARNING: more than one frozen sha in the log: {s['frozen_shas']}")
    p('  per day:')
    for day, d in s['per_day'].items():
        p(f"    {day}  scored {d['scored']:3d}  flagged {d['flagged']:2d}  calls {d['calls']:3d}  "
          f"${d['cost_usd']}")
    for field in ('trigger', 'policy'):
        p(f'  by {field}:')
        for k, g in (s.get(f'by_{field}') or {}).items():
            p(f"    {k}: lines {g['lines']}, scored {g['scored']}, flagged {g['flagged']}, "
              f"skipped {g['skipped']}, errors {g['errors']}, with row_sha {g['with_row_sha']}")
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
