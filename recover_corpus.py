#!/usr/bin/env python3
"""recover_corpus.py — rebuild the dogfood corpus from a host transcript.

WHY THIS EXISTS. lb_coverage.py's reset_task branch wipes the session record instead of
archiving it, and the design instructs an agent to reset on every genuinely new task. So a
working session resets five or six times and each reset deletes that segment's checks,
fires and catches. On 2026-07-25 a ~100-step session was on disk as "steps: 4", and the
whole nine-session corpus held 0 fires and 3 catches — while the transcript of that ONE
session mentioned check_state on 1695 lines.

The transcript is the real record: every check_state call, its verdict, and every tool
result including the failures. This reconstructs sessions in dogfood.py's schema from it.

    python3 recover_corpus.py ~/.claude/projects/-/<id>.jsonl -o sessions/
    python3 recover_corpus.py <transcript> --stdout | python3 dogfood.py --score /dev/stdin

WHAT COUNTS AS A CATCH, and why this is the only delicate part. dogfood.py defines a catch
as an error found INDEPENDENTLY — a guard that failed, a test that went red, a human who
said "that's wrong". The transcript is full of errored tool results, and a large share of
them are laserbrain's OWN gate and safety hooks refusing a call. Counting those would score
the harness against itself: the coverage gate fires, the gate's refusal is logged as an
independently-detected error, and the harness appears to predict the thing it caused. That
is circular, and it would manufacture a precision figure out of nothing.

So hook output is excluded explicitly (HOOK_MARKERS), and what remains is: non-zero build
exits, failing guards and test suites, and the shell's own errors. Those are found by
something that has never heard of laserbrain.
"""
import sys, json, re, pathlib, argparse, hashlib

# The harness talking to itself. Never a catch.
HOOK_MARKERS = (
    'laserbrain gate:', 'laserbrain safety:', 'laserbrain claim gate:',
    'laserbrain honesty:', 'laserbrain subagent:', 'THIS CALL DID NOT RUN',
)

# Something outside the harness found a real fault.
FAIL_MARKERS = (
    ('BUILD_EXIT=1', 'build failed'),
    ('run-together text:', 'weld guard failed'),
    ('problem(s)', 'a guard reported problems'),
    ('SURVIVED', 'a mutation survived — guard does not cover it'),
    ('FAIL —', 'a check suite failed'),
    ('\n  FAIL', 'a test suite failed'),
    ('Error: Turbopack build failed', 'build failed'),
    ('error TS', 'typescript error'),
    ('Traceback (most recent call last)', 'python raised'),
    ('command not found', 'shell error'),
    ('No such file or directory', 'missing file'),
    ('layout fault(s)', 'layout guard failed'),
)

CHECK = 'check_state'
RESET = 'reset_task'


def blocks(d):
    m = d.get('message') or {}
    c = m.get('content')
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def classify(text):
    """(is_catch, description). Hook output is never a catch — see the module docstring."""
    if any(h in text for h in HOOK_MARKERS):
        return False, None
    for marker, what in FAIL_MARKERS:
        if marker in text:
            return True, what
    return False, None


def parse(path):
    """Walk the transcript once and return a list of segments."""
    results = {}          # tool_use_id -> (text, is_error)
    calls = []            # ordered tool_use blocks

    for line in open(path, errors='ignore'):
        try:
            d = json.loads(line)
        except Exception:
            continue
        for b in blocks(d):
            t = b.get('type')
            if t == 'tool_use':
                calls.append({'id': b.get('id'), 'name': str(b.get('name') or ''),
                              'input': b.get('input') or {}})
            elif t == 'tool_result':
                results[b.get('tool_use_id')] = (str(b.get('content')), bool(b.get('is_error')))

    segments, cur = [], None

    def fresh():
        return {'steps': 0, 'checks': [], 'inferred': [], 'catches': [], 'goal': None}

    cur = fresh()
    for call in calls:
        name = call['name']
        text, is_err = results.get(call['id'], ('', False))

        if RESET in name:
            if cur['steps'] > 0:
                segments.append(cur)
            cur = fresh()
            continue

        # A step is a tool call, matching lb_coverage.py's own counter.
        cur['steps'] += 1
        step = cur['steps']

        if CHECK in name:
            ti = call['input']
            low = text.lower()
            drifting = '"drifting": true' in low or '"drifting":true' in low
            reason = ''
            m = re.search(r'"reason"\s*:\s*"([^"]+)"', text)
            if m:
                reason = m.group(1)
            if cur['goal'] is None:
                cur['goal'] = str(ti.get('goal', ''))[:400]
            cur['checks'].append({'step': step, 'drifting': drifting, 'reason': reason,
                                  'goal': str(ti.get('goal', ''))[:400],
                                  'progress': str(ti.get('progress', '')),
                                  'distance': ti.get('distance')})
            continue

        # Everything else is a candidate catch. A tool that errored counts only if the
        # error is not the harness's own refusal.
        blob = text if not is_err else text
        catch, what = classify(blob)
        if catch:
            cur['catches'].append({'step': step, 'what': what, 'by': 'build/guard/shell',
                                   'tool': name.split('__')[-1]})

    if cur['steps'] > 0:
        segments.append(cur)
    return segments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('transcript')
    ap.add_argument('-o', '--out', help='directory to write one JSON per segment')
    ap.add_argument('--stdout', action='store_true')
    a = ap.parse_args()

    segs = parse(a.transcript)
    stem = pathlib.Path(a.transcript).stem[:8]
    out = []
    for i, s in enumerate(segs, 1):
        s['id'] = f'{stem}-seg{i:02d}'
        out.append(s)

    fires = sum(1 for s in out for c in s['checks'] if c['drifting'])
    catches = sum(len(s['catches']) for s in out)
    steps = sum(s['steps'] for s in out)
    checks = sum(len(s['checks']) for s in out)
    print(f'  {len(out)} segment(s) · {steps} steps · {checks} checks '
          f'({checks / steps:.0%}) · {fires} fires · {catches} catches', file=sys.stderr)
    for s in out:
        cov = len(s['checks']) / s['steps'] if s['steps'] else 0
        f = sum(1 for c in s['checks'] if c['drifting'])
        print(f"    {s['id']}  {len(s['checks']):>3}/{s['steps']:<4} = {cov:>4.0%}  "
              f"fires {f:<3} catches {len(s['catches']):<3} {(s['goal'] or '')[:46]}",
              file=sys.stderr)

    if a.stdout:
        json.dump(out, sys.stdout, indent=2)
    if a.out:
        d = pathlib.Path(a.out)
        d.mkdir(parents=True, exist_ok=True)
        for s in out:
            (d / f"{s['id']}.json").write_text(json.dumps(s, indent=2))
        print(f'  wrote {len(out)} file(s) to {d}/', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
