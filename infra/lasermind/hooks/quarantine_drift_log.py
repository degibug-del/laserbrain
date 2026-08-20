#!/usr/bin/env python3
"""quarantine_drift_log.py — split rows that are not observations out of the live corpus.

TWO KINDS OF ROW DO NOT BELONG IN A CORPUS OF OBSERVED AGENT BEHAVIOUR.

1. UNATTRIBUTED. Before LASERBRAIN_AGENT was written into drift-log.jsonl, verdicts had
   no agent field, and a Claude-vs-Grok comparison that includes them is wrong. These go
   to drift-log.pre-agent.jsonl.

2. SYNTHETIC — added 2026-08-05, and the larger problem by far. Test suites spawned the
   MCP server against the real ~/.config/laserbrain and their runs were logged as if they
   were an agent working. At the time this was found the live log held 2,644 rows of which
   1,058 — 40% — were written by `test-parity`, `test-windup` and `test`.

   They do not dilute evenly, which is what makes them worse than noise. A test run is
   pathological ON PURPOSE: flat distance to provoke `stalled`, a repeated goal to provoke
   abandon, a redirect to provoke goal-drift. Measured:

       reason        real agents     test agents
       stalled            3.2%           39.7%
       goal-drift        17.2%            0.1%
       reground          18.9%            4.8%

   So the whole-log `stalled` rate is 17.8% against a true 3.2% — off by 5.6x. Every
   threshold ever read off this log was read off that mixture. These go to
   drift-log.synthetic.jsonl, kept rather than deleted: they are a fine record of what the
   suites do, they are just not evidence about agents.

The suites are isolated now (lasermind/_testhome.py sets a private LASERBRAIN_HOME, and
test_corpus_clean.py fails if a test agent ever appears in the live log again). This
cleans up what they already wrote.

Usage:
  python3 quarantine_drift_log.py           # dry-run summary
  python3 quarantine_drift_log.py --apply   # rewrite live log

Idempotent: a clean live file is a no-op.
"""
import argparse, json, pathlib, shutil, sys
from datetime import datetime, timezone

# One state root — lasergear/lb_paths.py. This lives a directory deeper than the other
# scripts, which is exactly why it was missed: it is out of sight of anyone editing
# lasermind/, and it writes the drift log every session.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import _root                                                       # noqa: E402

DEFAULT = _root.config('drift-log.jsonl')


def is_synthetic(agent):
    """A row written by a test suite rather than observed from an agent working.

    Matched on the agent name because that is what the suites set — LASERBRAIN_AGENT=
    test-parity, test-windup, test. Deliberately a prefix/substring rule and not an exact
    list: a new suite invents a new name, and a rule that needs updating for each one is a
    rule that silently stops working. `contest` or `latest` would be false positives; no
    agent is named that, and the cost of one is a row moved to a file that is kept anyway.
    """
    a = str(agent or '').strip().lower()
    return a.startswith('test') or a.endswith('-test') or '-test-' in a


def load_rows(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--path', default=str(DEFAULT))
    args = ap.parse_args()
    path = pathlib.Path(args.path)
    rows = load_rows(path)
    keep, drop, synth = [], [], []
    for r in rows:
        a = str(r.get('agent') or '').strip()
        if is_synthetic(a):
            synth.append(r)
        elif a and a.lower() not in ('unknown', '?'):
            keep.append(r)
        else:
            drop.append(r)

    print(f'live: {path}')
    print(f'  total={len(rows)}  observed={len(keep)}  unattributed={len(drop)}  synthetic={len(synth)}')
    if synth:
        import collections
        by = collections.Counter(str(r.get('agent')) for r in synth)
        print(f'  synthetic agents: {dict(by)}')
        # The number that says why this matters: a test run is pathological on purpose, so
        # the verdicts it contributes are not a sample of anything.
        rs = collections.Counter(r.get('reason') for r in synth)
        ks = collections.Counter(r.get('reason') for r in keep)
        for k in ('stalled', 'goal-drift'):
            tot = (rs.get(k, 0) + ks.get(k, 0)) / max(1, len(synth) + len(keep)) * 100
            obs = ks.get(k, 0) / max(1, len(keep)) * 100
            print(f'    {k:12} mixed {tot:5.1f}%   observed-only {obs:5.1f}%')
    if not drop and not synth:
        print('nothing to quarantine')
        return 0

    qpath = path.with_name(path.stem + '.pre-agent.jsonl')
    spath = path.with_name(path.stem + '.synthetic.jsonl')
    bak = path.with_suffix(path.suffix + f'.bak-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}')

    if not args.apply:
        if drop:  print(f'dry-run: would move {len(drop)} unattributed → {qpath}')
        if synth: print(f'dry-run: would move {len(synth)} synthetic     → {spath}')
        print(f'dry-run: would leave {len(keep)} observed rows in {path}')
        print('re-run with --apply to write')
        return 0

    # append to quarantine (preserve prior quarantine runs)
    existing_q = load_rows(qpath) if qpath.exists() else []
    # de-dupe by full json line
    seen = {json.dumps(r, sort_keys=True) for r in existing_q}
    for r in drop:
        key = json.dumps(r, sort_keys=True)
        if key not in seen:
            existing_q.append(r)
            seen.add(key)

    if path.exists():
        shutil.copy2(path, bak)
        print(f'backup: {bak}')

    if synth:
        # Kept, not deleted. They are an accurate record of what the suites do — just not
        # evidence about agents, which is the only thing the live log is for.
        existing_s = load_rows(spath) if spath.exists() else []
        seen_s = {json.dumps(r, sort_keys=True) for r in existing_s}
        for r in synth:
            k = json.dumps(r, sort_keys=True)
            if k not in seen_s:
                existing_s.append(r); seen_s.add(k)
        spath.write_text(''.join(json.dumps(r) + '\n' for r in existing_s))
        print(f'synthetic:  {spath} ({len(existing_s)} rows)')

    qpath.write_text(''.join(json.dumps(r) + '\n' for r in existing_q))
    path.write_text(''.join(json.dumps(r) + '\n' for r in keep))
    print(f'quarantine: {qpath} ({len(existing_q)} rows)')
    print(f'live now:   {path} ({len(keep)} rows)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
