#!/usr/bin/env python3
"""The judgment must survive the round trip, note and all — driven through the real server.

WHY THIS EXISTS, AND WHY test_judgment_recorded.py WAS NOT ENOUGH

That suite passes. It has passed every day since it was written. It drives a hook event
through Session and asserts the stored row carries anchored, goal_score and judgment, which
is the artifact and not the step — the lesson of the day it was written.

It still could not see this:

    drift-log.jsonl     0 of 2,555 rows carried a judgment
    session rows        0 of 2,157 carried one, against 44 carrying anchored

`unbacked` fired four times in one run on 2026-08-05 and none of it was stored. The cause
was laserbrain's own PostToolUse hook: it appends an honesty note to the check_state
response — "distance has not fallen across the last two checks" — and that note fires very
nearly when the judgment layer decides to speak. json.loads() demands the whole string be
one value, so the appended sentence made the entire reading unparseable. Server steps 2-5
of that run parsed and stored; steps 6-9 were exactly the four carrying a judgment, and all
four recorded `no-reading` with reason, phi, anchored and goal_score gone with it.

The instrument went blind precisely when it had the most to say, and did it to itself.

WHAT THE OLD SUITE ASSUMED, which is the transferable part: that a payload arrives clean.
It built its own response, so its response was always exactly what the server would send
and never what the agent would receive. This one takes the payload and appends the note —
the thing that actually happens — and it drives the SERVER rather than a constructed dict.

THREE CLAIMS

  1. the extractors survive trailing text     both copies, since a rule kept in two places
                                              diverges and only a test notices
  2. a genuinely broken payload still fails    salvage must not become "accept anything";
                                              a truncated object is a real no-reading
  3. the server logs its own judgment          so recording never again depends on reading
                                              the answer back out of the answer
"""
import collections
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _testhome                                                   # noqa: E402
_testhome.isolate()

sys.path.insert(0, str(HERE.parent / 'lasergear'))
sys.path.insert(0, str(HERE.parent / 'laserbrain-sdk'))
from lb_coverage import _verdict                                   # noqa: E402
from laserbrain.runtime import verdict_of                          # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


PAY = {'drifting': False, 'reason': 'advancing', 'phi': 0.15, 'run': 'r1', 'step': 6,
       'goal_score': 1, 'anchored': 0.5,
       'judgment': {'verdict': 'unbacked',
                    'because': 'Distance is reported down 6 over 7 checks, and not one of '
                               'them was backed by observed work — 0 corroborated of 7.',
                    'counsel': 'Run something and read the output before reporting again.'}}

# The real note, copied from the hook that emits it.
NOTE = ('\n\nPostToolUse:mcp__laserbrain__check_state hook additional context: laserbrain '
        'honesty: distance has not fallen across the last two checks. If you are circling '
        'or stuck, say so — false advancing wastes the dogfood corpus.')


def wrapped(text):
    return {'content': [{'type': 'text', 'text': text}]}


print('the reading survives laserbrain\'s own note — both copies of the extractor\n')
for name, fn in (('lb_coverage._verdict', _verdict), ('runtime.verdict_of', verdict_of)):
    v = fn(wrapped(json.dumps(PAY) + NOTE))
    check(f'{name}: judgment survives', v['judgment'] == 'unbacked', repr(v['judgment']))
    check(f'{name}:   and so does the rest', v['reason'] == 'advancing' and v['anchored'] == 0.5,
          f"reason={v['reason']} anchored={v['anchored']}")
    # Any trailing text, not only ours — a host that appends anything must not blind us.
    v2 = fn(wrapped(json.dumps(PAY) + '\nsome other host appended this'))
    check(f'{name}:   any trailing text', v2['judgment'] == 'unbacked')

print()
print('but salvage is not "accept anything" — a truly broken payload is still no-reading')
for name, fn in (('lb_coverage._verdict', _verdict), ('runtime.verdict_of', verdict_of)):
    v = fn(wrapped('{"drifting": fal'))
    check(f'{name}: truncated object', v['reason'] == 'no-reading' and v['judgment'] is None,
          f"reason={v['reason']}")

print()
print('and the SERVER logs the judgment itself, so nothing has to read it back out')
SERVER = HERE / 'mcp-server.mjs'
root = pathlib.Path(tempfile.mkdtemp(prefix='lb-judge-'))
(root / 'config').mkdir()
log = root / 'config' / 'drift-log.jsonl'
env = {**os.environ, 'LASERBRAIN_HOME': str(root), 'LASERBRAIN_AGENT': 'test-judgment-lands'}


def call(p, payload):
    p.stdin.write(json.dumps(payload) + '\n')
    p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if not line:
            return {}
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get('id') == payload['id']:
            return d


p = subprocess.Popen(['node', str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, text=True, env=env)
served = []
try:
    call(p, {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
        'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}})
    call(p, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
             'params': {'name': 'reset_task', 'arguments': {}}})
    # A flat run: distance never falls, which is what makes the judgment layer speak.
    for n in range(14):
        r = call(p, {'jsonrpc': '2.0', 'id': 100 + n, 'method': 'tools/call',
                     'params': {'name': 'check_state', 'arguments': {
                         'goal': 'ship the CSV export', 'progress': 'advancing', 'distance': 7}}})
        try:
            m = json.loads(r['result']['content'][0]['text'])
        except Exception:
            m = {}
        served.append((m.get('step'), (m.get('judgment') or {}).get('verdict')))
finally:
    # LET THE APPENDS LAND. logDrift is fire-and-forget — mkdir().then(appendFile).catch() —
    # so killing the server the instant the last response arrives drops whatever has not
    # flushed. First run of this test saw exactly that: 12 judgments spoken, 10 in the log,
    # the two missing being the final two steps.
    #
    # That is a real property of the logger and not only a test artifact: a server killed
    # mid-append loses the tail. It is left as-is deliberately — awaiting the write would
    # put disk latency on the response path of an instrument whose whole claim is that it
    # costs nothing to consult. The corpus tolerates losing the last row of a killed run;
    # it did not tolerate losing every judgment ever made.
    import time as _t
    _t.sleep(1.5)
    p.terminate()
    p.wait(timeout=10)

spoke = [(s, v) for s, v in served if v]
check('the server DID judge this run', bool(spoke),
      f'{len(spoke)} of {len(served)} checks — a run that produced none would prove nothing')

rows = []
if log.exists():
    for line in log.read_text().split('\n'):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
logged = [r for r in rows if r.get('judgment')]
check('and the log holds them', len(logged) >= len(spoke),
      f'{len(logged)} judgment row(s) in the log for {len(spoke)} spoken')

if spoke and logged:
    want = {(s, v) for s, v in spoke}
    got = {(r.get('step'), r.get('judgment')) for r in logged}
    check('  each keyed to the run and step it belongs to', want <= got,
          f'missing: {sorted(want - got)}' if want - got else f'{len(want)} matched exactly')
    check('  and the reasoning is kept, not just the verdict',
          all(r.get('because') for r in logged), 'a verdict with no because cannot be audited')
    # BOTH DECISIONS, side by side, or the split is unmeasurable.
    #
    # `anchored` was reported on every verdict from the day it shipped and logged never
    # once, so it sat broken — returning 0.5 forever — for its entire life, and was found
    # only by instrumenting from scratch. Control must not repeat that. With `judgment` and
    # `control` on the same row, "how often does the evidence-only decision disagree, and
    # who was right afterwards" is a grep rather than a research project. If they never
    # disagree, control is ceremony, and this is what will show it.
    # A VALUE, NOT A KEY. The first version of this asserted `'control' in r` and passed
    # 12/12 while every value was null — the log line writes `?? null`, so the key exists
    # whether or not anything reached it. `judgment` was being rebuilt field by field
    # upstream and control was not among the fields copied. Assert on the value, or the
    # gate tests the log statement rather than the thing it logs.
    check('  and control rides alongside the judgment, with a value',
          all(r.get('control') for r in logged),
          f"{sum(1 for r in logged if r.get('control'))}/{len(logged)} rows carry a decision")
    check('  with the agreement precomputed, so the disagreement rate is countable',
          all(isinstance(r.get('agrees'), bool) for r in logged),
          str(collections.Counter(r.get('agrees') for r in logged).most_common()))

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:3]))
    sys.exit(1)
print('  PASS — the judgment survives the response the agent actually receives, and the')
print('  server records it without anyone having to parse the answer back out of itself.')
