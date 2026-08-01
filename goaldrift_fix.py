#!/usr/bin/env python3
"""goaldrift_fix.py — two candidate suppression rules, measured against real fires.

Diego, 2026-07-25: "fix goal-drift so it doesn't fire on user redirection."

The detector lives in laserbrain-sdk/laserbrain/observe.py, which a host holds in the open
wave, so this does not edit it. It does the part that has to happen first anyway: decide
WHICH rule, on evidence, against the 24 real goal-drift fires recovered from the
transcript — 22 of which landed on the first check after Diego spoke.

A rule that suppresses false alarms is easy. A rule that suppresses them without blinding
the detector to an agent that genuinely wandered is the actual problem, and the corpus is
the only place to tell them apart.

    python3 goaldrift_fix.py

CANDIDATE A — "a clean jump from a healthy state is a re-ground."
    Suppress goal-drift when the PREVIOUS check was not drifting. The reasoning is about
    shape: an agent that wanders does it gradually, so the check before the fire is
    already degrading. An agent that is redirected jumps discontinuously out of a healthy
    state. Needs nothing the SDK does not already have — Observer keeps the history.

CANDIDATE B — "the first check after the user speaks is a re-ground."
    Suppress goal-drift on the first check_state following a UserPromptSubmit. Directly
    models the thing being fixed, but the SDK cannot see user turns; it needs the hook to
    set a flag, which means a change in lb_coverage.py (also one host's) and a wire between
    them. More plumbing, more exact.

Both are measured here for suppression AND for what they would cost.
"""
import json, glob, pathlib, sys

TRANSCRIPT = '/Users/diegorincon/.claude/projects/-/18d090f0-063e-446b-ace5-90617fceb301.jsonl'


def user_turn_flags(path):
    """{tool_use_id: True} for each check_state that was the first after a real user turn."""
    flags, seen_user = {}, False
    for line in open(path, errors='ignore'):
        try:
            d = json.loads(line)
        except Exception:
            continue
        m = d.get('message') or {}
        c = m.get('content')
        if d.get('type') == 'user':
            if isinstance(c, str) and c.strip():
                seen_user = True
            elif isinstance(c, list):
                # a tool_result is the harness answering us, not Diego speaking
                if not any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c):
                    if any(isinstance(b, dict) and b.get('type') == 'text'
                           and str(b.get('text', '')).strip() for b in c):
                        seen_user = True
            continue
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get('type') == 'tool_use' \
                        and 'check_state' in str(b.get('name', '')):
                    flags[b.get('id')] = seen_user
                    seen_user = False
    return flags


def main():
    segs = [json.load(open(f)) for f in sorted(glob.glob(
        str(pathlib.Path(__file__).parent / 'sessions/recovered/*.json')))]
    if not segs:
        print('  no recovered corpus — run recover_corpus.py first')
        return 1

    flags = user_turn_flags(TRANSCRIPT)
    # Re-walk the transcript in order so each recovered check lines up with its user flag.
    ordered = [tid for tid in flags]
    idx = 0

    rows = []
    for s in segs:
        prev_drifting = None
        expl = {st for c in s['catches'] for st in range(max(0, c['step'] - 3), c['step'] + 1)}
        for c in s['checks']:
            after_user = flags.get(ordered[idx], False) if idx < len(ordered) else False
            idx += 1
            if c.get('drifting') and (c.get('reason') or '').startswith('goal-drift'):
                rows.append({
                    'after_user': after_user,
                    'prev_healthy': prev_drifting is False,
                    'prev_none': prev_drifting is None,
                    'real_error': c['step'] in expl,
                })
            prev_drifting = bool(c.get('drifting'))

    n = len(rows)
    if not n:
        print('  no goal-drift fires in the corpus'); return 1
    true_pos = sum(1 for r in rows if r['real_error'])

    print(f'  {n} goal-drift fires in the recovered corpus')
    print(f'  of which coincided with an independently-caught error: {true_pos}\n')

    for name, keep in (
        ('A · previous check was healthy', lambda r: not (r['prev_healthy'] or r['prev_none'])),
        ('B · first check after the user spoke', lambda r: not r['after_user']),
        ('A or B', lambda r: not (r['prev_healthy'] or r['prev_none'] or r['after_user'])),
        ('A and B', lambda r: not ((r['prev_healthy'] or r['prev_none']) and r['after_user'])),
    ):
        kept = [r for r in rows if keep(r)]
        suppressed = n - len(kept)
        lost = true_pos - sum(1 for r in kept if r['real_error'])
        print(f'  {name:<38} suppresses {suppressed:>2}/{n}  ({suppressed/n:>4.0%})   '
              f'true positives lost: {lost}')

    print('\n  Reading it: goal-drift has NO measured true positives in this corpus, so no')
    print('  rule here can lose one. That makes the numbers above a measure of reach, not')
    print('  of safety — the safety argument has to come from the shape of the rule, and')
    print('  from re-measuring once the corpus contains a genuine wander.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
