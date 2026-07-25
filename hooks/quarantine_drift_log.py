#!/usr/bin/env python3
"""quarantine_drift_log.py — split unattributed drift verdicts out of the live corpus.

Before LASERBRAIN_AGENT was written into drift-log.jsonl, verdicts had no agent field.
Claude-vs-Grok studies that include those rows are wrong. This moves rows without a
usable `agent` into drift-log.pre-agent.jsonl and leaves only attributed rows in the
live file.

Usage:
  python3 quarantine_drift_log.py           # dry-run summary
  python3 quarantine_drift_log.py --apply   # rewrite live log

Idempotent: already-quarantined live file (all rows have agent) is a no-op.
"""
import argparse, json, pathlib, shutil, sys
from datetime import datetime, timezone

DEFAULT = pathlib.Path.home() / '.config' / 'laserbrain' / 'drift-log.jsonl'


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
    keep, drop = [], []
    for r in rows:
        a = r.get('agent')
        if a and str(a).strip() and str(a).strip().lower() not in ('unknown', '?'):
            keep.append(r)
        else:
            drop.append(r)

    print(f'live: {path}')
    print(f'  total={len(rows)}  attributed={len(keep)}  unattributed={len(drop)}')
    if not drop:
        print('nothing to quarantine')
        return 0

    qpath = path.with_name(path.stem + '.pre-agent.jsonl')
    bak = path.with_suffix(path.suffix + f'.bak-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}')

    if not args.apply:
        print(f'dry-run: would move {len(drop)} rows → {qpath}')
        print(f'dry-run: would leave {len(keep)} rows in {path}')
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

    qpath.write_text(''.join(json.dumps(r) + '\n' for r in existing_q))
    path.write_text(''.join(json.dumps(r) + '\n' for r in keep))
    print(f'quarantine: {qpath} ({len(existing_q)} rows)')
    print(f'live now:   {path} ({len(keep)} rows)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
