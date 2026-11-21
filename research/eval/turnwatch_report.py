#!/usr/bin/env python3
"""turnwatch_report.py — summarise the live, watch-only turnwatch check.

The hook (python/laserbrain/hooks/lb_turnwatch.py) judges the main session once per user turn,
at the first check_state after the user's message, with the frozen turn_match_llm.py judge, and
writes one line per turn to <STATE_DIR>/turnwatch.jsonl. This prints:

  counts by status (scored / skipped / error), skip reasons, errors
  flags: how many, which verdict, by which rule, drift scores, bare approvals
  latency: hook milliseconds, wait, call seconds; model calls and cost
  a per-day table: turns scored and flagged, calls, cost
  every flagged turn with its why, the asks it left out and redacted snippets

Reference: the frozen block (eval/turnwatch-frozen.json) holds DEV numbers, from the same labelled
turns the prompt and threshold were developed on, so they are not a target to beat: at the frozen
threshold, run 1 flagged 2 of 10 drift turns (the trigger reached 6 of them) with 1 false flag in
181 reached clean turns, and a second run flagged 1 with 1 false flag; each catch is one turn.
This log is the prospective test. A flag is not a verdict: label the flagged turns (and a sample
of the rest) by hand, their REASONS as well as the flags, before reading anything into the counts.

By trigger and by policy: from 2026-11-19 every row carries `trigger` and `policy`
(lb_turnwatch.py's STAMPS), so the counts are also split by each. A row without the field was
written before the stamps went live and counts as 'unstamped'; a row whose policy is null
(LASERBRAIN_POLICY unset) counts as 'none'.

Read-only. Snippets in the log were redacted when written; nothing here prints more.

Usage:
  turnwatch_report.py [--log PATH] [--since YYYY-MM-DD] [--json]
"""
import argparse
import collections
import json
import os
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
FROZEN = HERE.parents[1] / 'eval' / 'turnwatch-frozen.json'
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
    return base / 'turnwatch.jsonl'


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


def pct(vals, q):
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    return vals[min(len(vals) - 1, max(0, int(round(q * (len(vals) - 1)))))]


def dev_reference():
    try:
        d = json.loads(FROZEN.read_text())
        m = (d.get('dev') or {}).get('metrics') or {}
        return {'drift_caught': m.get('tp'), 'drift_turns': m.get('positives'),
                'drift_reached': m.get('positives_reached'), 'false_flags': m.get('fp'),
                'clean_reached': m.get('negatives_reached'), 'threshold':
                ((d.get('frozen') or {}).get('thresholds') or {}).get('min_drift_score')}
    except Exception:
        return None


def stamp_label(r, field):
    """The row's trigger or policy as a group name: PRE_STAMP when the field is absent,
    NO_POLICY when it is present but null."""
    if field not in r:
        return PRE_STAMP
    v = r.get(field)
    return NO_POLICY if v is None or v == '' else str(v)


def by_stamp(rows, field):
    """Row counts grouped by `field` (trigger or policy)."""
    out = collections.defaultdict(lambda: {'lines': 0, 'scored': 0, 'flagged': 0, 'skipped': 0,
                                           'errors': 0, 'with_row_sha': 0})
    for r in rows:
        s = r.get('status')
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
    per_day = collections.defaultdict(lambda: {'scored': 0, 'flagged': 0, 'skipped': 0, 'errors': 0,
                                               'calls': 0, 'cost_usd': 0.0})
    for r in rows:
        d = per_day[str(r.get('ts') or '')[:10]]
        d['calls'] += int(r.get('calls') or 0)
        d['cost_usd'] += float(r.get('cost_usd') or 0)
        s = r.get('status')
        if s == 'scored':
            d['scored'] += 1
            d['flagged'] += bool(r.get('flag'))
        elif s == 'skipped':
            d['skipped'] += 1
        elif s == 'error':
            d['errors'] += 1
    inputs = collections.Counter()
    for r in scored:
        for k, v in (r.get('inputs') or {}).items():
            inputs[k if k != 'user_recent' else 'user_recent>0'] += bool(v)
    return {
        'lines': len(rows), 'status': dict(st), 'skip_reasons': dict(skips),
        'error_reasons': dict(errs), 'error_examples': err_examples,
        'scored': len(scored), 'flagged': len(flagged),
        'flag_rate': round(len(flagged) / len(scored), 3) if scored else None,
        'verdicts': dict(collections.Counter(r.get('verdict') for r in scored)),
        'flagged_by': dict(collections.Counter(b for r in flagged for b in (r.get('by') or []))),
        'bare_approvals': {'scored': sum(1 for r in scored if r.get('bare_approval')),
                           'flagged': sum(1 for r in flagged if r.get('bare_approval'))},
        'drift_score': {'median': statistics.median([r.get('drift_score') or 0 for r in scored])
                        if scored else None,
                        'ge_40': sum((r.get('drift_score') or 0) >= 40 for r in scored)},
        'inputs_present': dict(inputs),
        'latency': {'hook_ms_p50': pct([r.get('hook_ms') for r in rows], 0.5),
                    'hook_ms_max': pct([r.get('hook_ms') for r in rows], 1.0),
                    'delay_s_p50': pct([r.get('delay_s') for r in scored], 0.5),
                    'call_s_p50': pct([r.get('call_s') for r in scored], 0.5),
                    'call_s_max': pct([r.get('call_s') for r in scored], 1.0),
                    'total_s_p50': pct([r.get('total_s') for r in scored], 0.5)},
        'calls': sum(int(r.get('calls') or 0) for r in rows),
        'cost_usd': round(sum(float(r.get('cost_usd') or 0) for r in rows), 4),
        'per_day': {k: {**v, 'cost_usd': round(v['cost_usd'], 4)} for k, v in sorted(per_day.items())},
        'by_trigger': by_stamp(rows, 'trigger'),
        'by_policy': by_stamp(rows, 'policy'),
        'frozen_shas': sorted({r.get('frozen_sha') for r in rows if r.get('frozen_sha')}),
        'flagged_turns': [{k: r.get(k) for k in ('ts', 'session', 'msg_ts', 'msg_via', 'verdict', 'by',
                                                 'drift_score', 'why', 'missing', 'bare_approval',
                                                 'snippets', 'inputs')} for r in flagged],
        'dev_reference': dev_reference(),
    }


def show(s, path):
    p = print
    p(f'turnwatch report  ({path})')
    p(f"  lines {s['lines']}   " + '  '.join(f'{k} {v}' for k, v in sorted(s['status'].items(),
                                                                       key=lambda kv: str(kv[0]))))
    if not s['lines']:
        p('  (no lines yet)')
        return
    fr = f"{s['flag_rate']:.1%}" if s['flag_rate'] is not None else '-'
    p(f"  scored {s['scored']}   flagged {s['flagged']} ({fr})   by {s['flagged_by'] or {}}")
    p(f"  verdicts {s['verdicts']}")
    p(f"  bare approvals: scored {s['bare_approvals']['scored']}, flagged {s['bare_approvals']['flagged']}")
    p(f"  drift score median {s['drift_score']['median']}, >= 40: {s['drift_score']['ge_40']}")
    ref = s.get('dev_reference')
    if ref:
        p(f"  dev reference (labels known in advance, NOT a target): {ref['drift_caught']} of "
          f"{ref['drift_turns']} drift turns flagged ({ref['drift_reached']} reached), "
          f"{ref['false_flags']} false flags in {ref['clean_reached']} reached clean turns, "
          f"threshold {ref['threshold']}")
    if s['skip_reasons']:
        p('  skipped: ' + ', '.join(f'{k} {v}' for k, v in sorted(s['skip_reasons'].items(),
                                                                  key=lambda kv: -kv[1])))
    if s['error_reasons']:
        p('  errors:')
        for k, v in sorted(s['error_reasons'].items(), key=lambda kv: -kv[1]):
            p(f"    {v} x {k}: {s['error_examples'].get(k) or ''}"[:220])
    p(f"  inputs present (of {s['scored']} scored): {s['inputs_present']}")
    lt = s['latency']
    p(f"  latency: hook p50 {lt['hook_ms_p50']} ms, max {lt['hook_ms_max']} ms; wait p50 {lt['delay_s_p50']} s; "
      f"call p50 {lt['call_s_p50']} s, max {lt['call_s_max']} s; worker total p50 {lt['total_s_p50']} s")
    p(f"  model calls {s['calls']}, cost ${s['cost_usd']}")
    if len(s['frozen_shas']) > 1:
        p(f"  WARNING: more than one frozen sha in the log: {s['frozen_shas']}")
    for field in ('trigger', 'policy'):
        p(f'  by {field}:')
        for k, g in (s.get(f'by_{field}') or {}).items():
            p(f"    {k}: lines {g['lines']}, scored {g['scored']}, flagged {g['flagged']}, "
              f"skipped {g['skipped']}, errors {g['errors']}, with row_sha {g['with_row_sha']}")
    p('  per day:')
    p('    day          scored flagged skipped errors calls   cost')
    for day, d in s['per_day'].items():
        p(f"    {day:12s} {d['scored']:6d} {d['flagged']:7d} {d['skipped']:7d} {d['errors']:6d} "
          f"{d['calls']:5d}  ${d['cost_usd']}")
    if s['flagged_turns']:
        p('  flagged turns:')
        for f in s['flagged_turns']:
            sn = f.get('snippets') or {}
            p(f"    {f['ts']}  {str(f['session'])[:8]}  message {f.get('msg_ts')} ({f.get('msg_via')})"
              f"{'  bare approval' if f.get('bare_approval') else ''}")
            p(f"      {f['verdict']} / drift {f['drift_score']} / by {f.get('by')}: {f.get('why')}")
            if f.get('missing'):
                p(f"      left out: {'; '.join(str(m) for m in f['missing'])}")
            for k in ('msg', 'proposal', 'goal', 'doing'):
                if sn.get(k):
                    p(f"      {k}: {sn[k]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--log', default=None, help='default: <STATE_DIR>/turnwatch.jsonl')
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
