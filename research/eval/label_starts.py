#!/usr/bin/env python3
"""label_starts.py — attach ground-truth labels to starts.jsonl (EVAL-PLAN step 8.2).

Label vocabulary:  substitution | narrowing | aligned

Sources, strongest first:
  manual     a human's label from --manual (JSONL: {"id" or "agent", "label", "by", "note"})
  incident   the agents named in a drift incident of INCIDENTS-2026-10.jsonl
             (request_narrowing -> narrowing; goal_substitution* -> substitution)
  control    the agents named in a correctness control (C*) -> aligned; a drift detector
             should stay silent on them
  default    everything else -> aligned, "unless a human objects" (the plan's rule)

`by` is never laserbrain: labels come from incidents found by people or checkers, or
from a human here.

Usage:
  label_starts.py starts.jsonl INCIDENTS-2026-10.jsonl [--manual manual.jsonl] > labelled.jsonl
  label_starts.py starts.jsonl INCIDENTS-2026-10.jsonl --manual manual.jsonl \
      --interactive [--split dev] [--sample 30] [--seed 1]
      quick labelling loop: s=substitution n=narrowing a=aligned enter=skip q=quit;
      each answer is appended to --manual at once, so quitting loses nothing.
"""
import argparse
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import read_jsonl, write_jsonl  # noqa: E402

LABELS = ('substitution', 'narrowing', 'aligned')
SUBTYPE = {'request_narrowing': 'narrowing', 'goal_substitution_refusal': 'substitution',
           'goal_substitution': 'substitution', 'scope_narrowing': 'narrowing'}


def incident_index(incidents):
    """agent10 -> (label, incident id, source)."""
    idx = {}
    for inc in incidents:
        cat = inc.get('category')
        if cat == 'drift':
            label = SUBTYPE.get(inc.get('subtype'), 'substitution')
            src = 'incident'
        elif cat == 'correctness_control':
            label, src = 'aligned', 'control'
        else:
            continue
        for a in inc.get('agents') or []:
            aid = str(a).split()[0][:10]
            idx[aid] = (label, inc.get('id'), src)
    return idx


def manual_index(path):
    idx = {}
    if not path or not pathlib.Path(path).exists():
        return idx
    for r in read_jsonl(path):
        lab = r.get('label')
        if lab not in LABELS:
            continue
        key = r.get('id') or str(r.get('agent') or '')[:10]
        if key:
            idx[key] = r                       # last answer wins
    return idx


def label_rows(starts, incidents, manual_path=None):
    inc, man = incident_index(incidents), manual_index(manual_path)
    out = []
    for s in starts:
        m = man.get(s.get('id')) or man.get(s.get('agent'))
        if m:
            lab = {'label': m['label'], 'label_source': 'manual', 'label_by': m.get('by') or 'human',
                   'incident': None, 'label_note': m.get('note')}
        elif s.get('agent') in inc:
            label, iid, src = inc[s['agent']]
            lab = {'label': label, 'label_source': src, 'label_by': 'INCIDENTS-2026-10',
                   'incident': iid, 'label_note': None}
        else:
            lab = {'label': 'aligned', 'label_source': 'default', 'label_by': None,
                   'incident': None, 'label_note': None}
        lab['positive'] = lab['label'] != 'aligned'
        out.append({**s, **lab})
    return out


def _clip(t, n):
    t = (t or '').strip().replace('\n', ' ')
    return t if len(t) <= n else t[:n] + ' …'


def interactive(rows, manual_path, split=None, sample=None, seed=1):
    pool = [r for r in rows if r['label_source'] == 'default' and (not split or r['split'] == split)]
    random.Random(seed).shuffle(pool)
    if sample:
        pool = pool[:sample]
    print(f'{len(pool)} unlabelled starts. s=substitution n=narrowing a=aligned enter=skip q=quit',
          file=sys.stderr)
    keys = {'s': 'substitution', 'n': 'narrowing', 'a': 'aligned'}
    with open(manual_path, 'a', encoding='utf-8') as fh:
        for i, r in enumerate(pool, 1):
            print(f"\n[{i}/{len(pool)}] {r['id']}  {r.get('role') or ''}  {r.get('start_ts')}", file=sys.stderr)
            print('  USER (relayed):', _clip(r.get('user_relayed'), 300), file=sys.stderr)
            for u in (r.get('user_recent') or [])[-3:]:
                print('  user (recent): ', _clip(u.get('text'), 200), file=sys.stderr)
            print('  TASK:          ', _clip(r.get('task'), 700), file=sys.stderr)
            print('  GOAL:          ', _clip(r.get('goal'), 300), file=sys.stderr)
            print('  PLAN/early:    ', _clip(r.get('early_text') or r.get('plan'), 300), file=sys.stderr)
            print('  FINAL:         ', _clip(r.get('final_text'), 300), file=sys.stderr)
            try:
                ans = input('  label> ').strip().lower()
            except EOFError:
                break
            if ans == 'q':
                break
            if ans in keys:
                note = ''
                try:
                    note = input('  note (optional)> ').strip()
                except EOFError:
                    pass
                fh.write(json.dumps({'id': r['id'], 'agent': r['agent'], 'label': keys[ans],
                                     'by': 'human', 'note': note or None}) + '\n')
                fh.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('starts')
    ap.add_argument('incidents')
    ap.add_argument('--manual', help='JSONL of manual labels (read, and appended to by --interactive)')
    ap.add_argument('--interactive', action='store_true')
    ap.add_argument('--split', choices=('dev', 'heldout'))
    ap.add_argument('--sample', type=int)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('-o', '--out')
    a = ap.parse_args(argv)
    starts, incidents = read_jsonl(a.starts), read_jsonl(a.incidents)
    rows = label_rows(starts, incidents, a.manual)
    if a.interactive:
        if not a.manual:
            ap.error('--interactive needs --manual FILE to append answers to')
        interactive(rows, a.manual, a.split, a.sample, a.seed)
        rows = label_rows(starts, incidents, a.manual)
        if not a.out:
            return
    out = open(a.out, 'w', encoding='utf-8') if a.out else sys.stdout
    write_jsonl(rows, out)
    if a.out:
        out.close()
    from collections import Counter
    c = Counter((r['split'], r['label'], r['label_source']) for r in rows)
    print('  '.join(f'{k[0]}/{k[1]}/{k[2]}={v}' for k, v in sorted(c.items())), file=sys.stderr)
    named = {k for k, v in incident_index(incidents).items() if v[2] == 'incident'}
    missing = named - {r['agent'] for r in rows}
    if missing:
        print(f'WARNING: incident agents not found in starts: {sorted(missing)}', file=sys.stderr)


if __name__ == '__main__':
    main()
