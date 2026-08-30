#!/usr/bin/env python3
"""What laserbrain's own record actually says. The evidence half of self-design.

    python3 read_corpus.py            # readable
    python3 read_corpus.py --json     # for a designer to consume

WHY THIS EXISTS. laserbrain has been recording itself since June — checks, refusals, drift
fires, catches, arm assignments — and until 2026-08-16 nothing had ever read any of it
back. The first attempt found, in three queries: that 41 of 56 live checks held no server
response at all, that blind readings were being stored as parse failures, and that the
"2,483 checks" everyone quoted was really about 290. None of that needed a model. It needed
somebody to open the files.

So this is deliberately NOT a proposer. It assembles evidence and stops. A designer reading
its output can propose changes; this refuses to, because the moment the same program both
measures and recommends, the recommendation starts shaping the measurement — which is the
whole argument at /papers/frozen-reference/ and the reason the RAG gate once blocked 74.3%
of correct answers.

WHAT IT WILL NOT DO:

  - Report a rate without its n. A percentage over four observations is a story.
  - Call an unobserved response a check. See lb_coverage.py: a row holding only what the
    agent typed is not a reading, and counting it inflates coverage and poisons any arm
    comparison.
  - Merge the arms. Blind and sighted are kept apart everywhere, because the probe is
    pre-registered (BLIND-PROBE.md) and reading them together early is the one thing that
    would waste it.
"""
import collections
import datetime as dt
import glob
import json
import pathlib
import sys

HOME = pathlib.Path.home()
LIVE = HOME / '.claude' / 'laserbrain'
ARCHIVE = HOME / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis/lasermind/sessions/recovered'

# Below this, a proportion is an anecdote wearing a percent sign.
MIN_N = 20


def _load(paths):
    for p in paths:
        try:
            yield p, json.load(open(p))
        except Exception:
            continue


def is_reading(c):
    """The rule from lb_coverage.py, applied to history.

    `run`, `phi` and `arm` are recent fields — testing only for them calls every archived
    check hollow, though those rows carry real verdicts from an older hook. A reading is
    evidenced by any of them, or by a reason that is not the no-reading default.
    """
    r = c.get('reason')
    return (c.get('run') is not None or c.get('phi') is not None or bool(c.get('arm'))
            or (bool(r) and r not in ('no-reading', 'unparsed')))


def gather():
    sessions = []
    for src, paths in (('archive', sorted(glob.glob(str(ARCHIVE / '*.json')))),
                       ('live', [p for p in sorted(glob.glob(str(LIVE / '*.json')))
                                 if 'current-arm' not in p and 'arms' not in pathlib.Path(p).stem])):
        for path, j in _load(paths):
            if not isinstance(j, dict):
                continue
            sessions.append({
                'src': src,
                'id': j.get('id') or pathlib.Path(path).stem,
                'goal': j.get('goal'),
                'steps': int(j.get('steps') or 0),
                'checks': [c for c in (j.get('checks') or []) if isinstance(c, dict)],
                'catches': [c for c in (j.get('catches') or []) if isinstance(c, dict)],
            })
    refusals = []
    rp = LIVE / 'refusals.jsonl'
    if rp.exists():
        for line in open(rp):
            line = line.strip()
            if line:
                try:
                    refusals.append(json.loads(line))
                except Exception:
                    pass
    arms = []
    ap = LIVE / 'blind-arms.jsonl'
    if ap.exists():
        for line in open(ap):
            line = line.strip()
            if line:
                try:
                    arms.append(json.loads(line))
                except Exception:
                    pass
    return sessions, refusals, arms


def rate(num, den):
    """A proportion, or an honest refusal to give one."""
    if den < MIN_N:
        return {'n': den, 'of': num, 'rate': None, 'note': f'n={den}, below {MIN_N} — no rate reported'}
    return {'n': den, 'of': num, 'rate': round(num / den, 4)}


def build():
    sessions, refusals, arms = gather()
    checks = [c for s in sessions for c in s['checks']]
    readings = [c for c in checks if is_reading(c)]
    hollow = [c for c in checks if not is_reading(c)]
    catches = [c for s in sessions for c in s['catches']]

    by_src = collections.Counter(s['src'] for s in sessions)
    read_by_src = collections.Counter(
        s['src'] for s in sessions for c in s['checks'] if is_reading(c))
    hollow_by_src = collections.Counter(
        s['src'] for s in sessions for c in s['checks'] if not is_reading(c))

    reasons = collections.Counter(c.get('reason') for c in readings)
    drift = [c for c in readings if c.get('drifting') is True]

    # WHAT THE AGENT CLAIMED vs WHAT WAS READ. The one comparison the corpus can make that
    # nothing else can: self-reported progress against a measured verdict.
    claim_vs_read = collections.Counter(
        (str(c.get('progress') or '?'), 'drifting' if c.get('drifting') else 'held')
        for c in readings)

    # Distance is what the agent SAYS about itself. Whether high self-reported distance
    # predicts a drift verdict is a question about the instrument, not about the agent.
    dist_drift = collections.defaultdict(lambda: [0, 0])
    for c in readings:
        d = c.get('distance')
        if isinstance(d, (int, float)):
            b = 'high (7-10)' if d >= 7 else ('mid (4-6)' if d >= 4 else 'low (0-3)')
            dist_drift[b][1] += 1
            if c.get('drifting'):
                dist_drift[b][0] += 1

    out = {
        'read_at': dt.datetime.now().isoformat(timespec='seconds'),
        'health': {
            'sessions': dict(by_src),
            'checks_total': len(checks),
            'readings': len(readings),
            'hollow': len(hollow),
            'readings_by_source': dict(read_by_src),
            'hollow_by_source': dict(hollow_by_src),
            'note': ('hollow rows hold only what the agent typed — no server response was '
                     'observed. They are historical; lb_coverage.py stopped writing them '
                     'on 2026-08-16.'),
        },
        'verdicts': {
            'reasons': dict(reasons.most_common()),
            'drift': rate(len(drift), len(readings)),
        },
        'self_report_vs_verdict': {f'{k[0]} -> {k[1]}': v for k, v in claim_vs_read.most_common()},
        'distance_claimed_vs_drift': {
            k: rate(v[0], v[1]) for k, v in sorted(dist_drift.items())
        },
        'gate': {
            'refusals': len(refusals),
            'by_stage': dict(collections.Counter(str(r.get('stage')) for r in refusals).most_common()),
            'by_tool': dict(collections.Counter(str(r.get('tool')) for r in refusals).most_common(8)),
            'coverage_when_refused': _spread([r.get('coverage') for r in refusals]),
        },
        'catches': {
            'total': len(catches),
            'by_source': dict(collections.Counter(str(c.get('by')) for c in catches).most_common(6)),
            'note': ('errors something INDEPENDENT found — the compiler, the tests, the '
                     'shell. The one signal laserbrain cannot manufacture, and therefore '
                     'the only honest referee for any change it proposes to itself.'),
        },
        'blind_probe': {
            'assignments_logged': len(arms),
            'by_arm': dict(collections.Counter(str(a.get('blind')) for a in arms).most_common()),
            'fallback_rows': sum(1 for a in arms if a.get('fallback')),
            'note': ('PRE-REGISTERED in lasergear/BLIND-PROBE.md: stop at 20 per arm, no '
                     'interim looks. No outcome comparison is computed here and none should '
                     'be until then.'),
        },
        'anomalies': _anomalies(sessions, checks, readings, hollow, refusals, arms),
    }
    return out


def _spread(vals):
    v = sorted(x for x in vals if isinstance(x, (int, float)))
    if not v:
        return None
    return {'n': len(v), 'min': round(v[0], 3), 'median': round(v[len(v) // 2], 3), 'max': round(v[-1], 3)}


def _anomalies(sessions, checks, readings, hollow, refusals, arms):
    """Things that look wrong. Stated as observations, never as instructions."""
    out = []
    if checks and len(hollow) / len(checks) > 0.2:
        out.append({
            'what': 'a large share of recorded checks hold no server response',
            'evidence': f'{len(hollow)} of {len(checks)} checks',
            'why_it_matters': 'they inflate coverage and would contaminate any arm comparison',
        })
    live_sessions = [s for s in sessions if s['src'] == 'live']
    empty = [s for s in live_sessions if s['steps'] and not s['checks']]
    if empty:
        out.append({
            'what': 'sessions with steps but no checks at all',
            'evidence': f'{len(empty)} of {len(live_sessions)} live sessions',
            'why_it_matters': 'either the harness was not attached or nothing was spelled',
        })
    if refusals:
        stages = collections.Counter(str(r.get('stage')) for r in refusals)
        top, n = stages.most_common(1)[0]
        if n / len(refusals) > 0.9:
            out.append({
                'what': f'the gate refuses almost entirely at one stage ({top})',
                'evidence': f'{n} of {len(refusals)} refusals',
                'why_it_matters': 'a gate with one firing mode may be one rule wearing two names',
            })
        arms_seen = set(str(r.get('arm')) for r in refusals)
        if len(arms_seen) == 1:
            out.append({
                'what': f'every refusal carries the same probe arm ({arms_seen.pop()})',
                'evidence': f'{len(refusals)} refusals, one arm',
                'why_it_matters': 'that probe has no contrast, so its comparison cannot be made',
            })
    if arms:
        c = collections.Counter(str(a.get('blind')) for a in arms)
        if len(c) == 1:
            out.append({
                'what': 'blind-arm log holds only one arm so far',
                'evidence': dict(c),
                'why_it_matters': 'expected early; noted so it is not mistaken for a result',
            })
    long_goals = [c for c in readings if len(str(c.get('goal') or '')) > 200]
    if long_goals:
        out.append({
            'what': 'goals long enough that the overlap measure may be reading prose',
            'evidence': f'{len(long_goals)} of {len(readings)} readings over 200 chars',
            'why_it_matters': 'the laserscore compares stem sets; a paragraph overlaps everything',
        })
    return out


def human(d):
    L = []
    A = L.append
    h = d['health']
    A('')
    A(f"  laserbrain, read back  ·  {d['read_at']}")
    A('')
    A(f"  sessions   {h['sessions']}")
    A(f"  checks     {h['checks_total']}   readings {h['readings']}   hollow {h['hollow']}")
    A(f"             readings by source {h['readings_by_source']}")
    A('')
    A('  verdicts')
    for k, v in d['verdicts']['reasons'].items():
        A(f"    {str(k):<22} {v}")
    dr = d['verdicts']['drift']
    A(f"    drift                  {dr['of']}/{dr['n']}" + (f"  = {dr['rate']:.1%}" if dr.get('rate') is not None else f"  ({dr['note']})"))
    A('')
    A('  what the agent said, against what was read')
    for k, v in d['self_report_vs_verdict'].items():
        A(f"    {k:<28} {v}")
    A('')
    A('  self-reported distance vs a drift verdict')
    for k, v in d['distance_claimed_vs_drift'].items():
        A(f"    {k:<14} {v['of']}/{v['n']}" + (f"  = {v['rate']:.1%}" if v.get('rate') is not None else '   (too few to rate)'))
    A('')
    g = d['gate']
    A(f"  gate       {g['refusals']} refusals   stages {g['by_stage']}")
    A(f"             coverage when it fired {g['coverage_when_refused']}")
    A(f"             most refused: {list(g['by_tool'].items())[:4]}")
    A('')
    c = d['catches']
    A(f"  catches    {c['total']}  {c['by_source']}")
    A('')
    b = d['blind_probe']
    A(f"  blind probe  {b['assignments_logged']} assignments {b['by_arm']}  fallback {b['fallback_rows']}")
    A(f"               {b['note']}")
    A('')
    A('  anomalies')
    if not d['anomalies']:
        A('    none that this reader can see')
    for a in d['anomalies']:
        A(f"    · {a['what']}")
        A(f"      {a['evidence']}  —  {a['why_it_matters']}")
    A('')
    A('  This reader proposes nothing, on purpose. A program that both measures and')
    A('  recommends starts shaping what it measures.')
    A('')
    return '\n'.join(L)


if __name__ == '__main__':
    data = build()
    if '--json' in sys.argv:
        print(json.dumps(data, indent=2))
    else:
        print(human(data))
