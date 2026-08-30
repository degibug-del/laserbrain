#!/usr/bin/env python3
"""Split test-fixture contexts out of contexts.json.

WHY, AND WHY IT IS WORSE HERE THAN IN THE DRIFT LOG

drift-log.jsonl carries an `agent` field, so synthetic rows were identifiable the moment
anyone counted. contexts.json carries no writer at all — id, tokens, sessions, spellings,
checks — so a fixture context is indistinguishable from a real one by inspection.

And the pollution is far worse by weight than by count. When this was found on 2026-08-05:

    ctx_...  conformance probe        14,508 checks    one context
    ctx_...  page ship                25,604 checks
    ctx_...  x y z                      4,528 checks
    ctx_...  alpha beta gamma           2,393 checks

Real work does not produce a context with fourteen thousand checks. Those are conformance
suites sweeping the grammar. 255 of 679 contexts were fixtures, and because `repetition`
reads the max identical-spelling count, they landed exactly on the tail that decides the
`repetition >= 3` threshold: >= 4 read 18.3% across everything against 4.5% observed.

THE DISCRIMINATOR is a join, not a guess. Every real context lists full run UUIDs in
`sessions`, because that is what check_state passes. The suites use short synthetic ids.
So a context is observed if any of its sessions is a run in the (already cleaned) drift
log, or is a 36-character UUID whose run has rotated out of the log. Everything else is a
fixture, and goes to contexts.synthetic.json rather than being deleted.

  python3 quarantine_contexts.py            # dry run
  python3 quarantine_contexts.py --apply
"""
import argparse
import collections
import json
import pathlib
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import _root                                                       # noqa: E402


def runs_in(path):
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().split('\n'):
        if line.strip():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get('run'):
                out.add(r['run'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    path = _root.config('contexts.json')
    if not path.exists():
        print(f'no contexts file at {path}')
        return 0
    ctx = json.loads(path.read_text())
    observed_runs = runs_in(_root.config('drift-log.jsonl'))

    keep, drop = {}, {}
    for k, v in ctx.items():
        ss = set(v.get('sessions') or [])
        # A real run id, either still in the log or a UUID whose rows have rotated out.
        if (ss & observed_runs) or any(len(s) == 36 and s.count('-') == 4 for s in ss):
            keep[k] = v
        else:
            drop[k] = v

    def rep(d):
        r = [max(v['spellings'].values()) for v in d.values()
             if isinstance(v.get('spellings'), dict) and v['spellings']]
        n = len(r) or 1
        return {t: round(100 * sum(1 for m in r if m >= t) / n, 1) for t in (2, 3, 4)}

    print(f'contexts: {path}')
    print(f'  total={len(ctx)}  observed={len(keep)}  fixtures={len(drop)}')
    if drop:
        big = sorted(drop.items(), key=lambda kv: -(kv[1].get('checks') or 0))[:3]
        for k, v in big:
            print(f'    {v.get("checks"):>7} checks  {" ".join((v.get("tokens") or [])[:6])}')
        print(f'  max-repeat distribution  all={rep(ctx)}  observed-only={rep(keep)}')
    if not drop:
        print('nothing to quarantine')
        return 0

    spath = path.with_name('contexts.synthetic.json')
    if not args.apply:
        print(f'dry-run: would move {len(drop)} fixture contexts → {spath}')
        print(f'dry-run: would leave {len(keep)} observed contexts in {path}')
        return 0

    bak = path.with_suffix(f'.json.bak-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}')
    shutil.copy2(path, bak)
    print(f'backup: {bak}')
    existing = json.loads(spath.read_text()) if spath.exists() else {}
    existing.update(drop)
    spath.write_text(json.dumps(existing, indent=1))
    path.write_text(json.dumps(keep, indent=1))
    print(f'fixtures:  {spath} ({len(existing)})')
    print(f'live now:  {path} ({len(keep)})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
