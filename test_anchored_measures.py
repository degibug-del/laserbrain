#!/usr/bin/env python3
"""`anchored` must be able to say 1.0. For its whole life it could not.

THE BUG, found 2026-08-06

anchored() is SIDE-EFFECTING. It reads the observed-work counter and advances `_seenOk` so
the next check measures the next interval. It was called TWICE on every check_state — once
building `scores.evidence`, once building the `anchored` field — and the second call saw the
marker the first had just moved:

    ok=11 seen=10  advanced=true     <- first call, correct
    ok=11 seen=11  advanced=false    <- second call, unanchored

The response carries the second. So `anchored` returned 0.5 no matter what the agent did,
and `unbacked` — the judgment that reads it — fired on runs that WERE backed. Measured
across the corpus: 0 corroborated of 106 recorded checks. Not a sampling result. A
structural impossibility.

It went unseen because 0.5 is the DEFAULT and also a plausible reading. Nothing looked
broken; the number was simply always the same one, and "half the weight rests on the agent's
own word" is exactly what the docs say it means. A wrong value that matches the expected
value is invisible.

WHAT THIS PINS

  work happened      -> 1.0. The assertion that could never have passed before.
  nothing happened   -> 0.5, so the veto did not simply pin it the other way.
  two consumers      -> ONE reading. The memo is per tool call, which is the scope of one
                        check; if a third consumer is added it shares rather than resets.

Driven through the real server over stdio, because the bug lived in the interaction between
two call sites and no unit test of anchored() alone could see it.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SERVER = HERE / 'mcp-server.mjs'
fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


root = pathlib.Path(tempfile.mkdtemp(prefix='lb-anchored-'))
(root / 'config').mkdir()
(root / 'sessions').mkdir()
EV = root / 'config' / 'evidence.json'
EV.write_text(json.dumps({'ok': 10, 'fail': 0}))

env = {**os.environ, 'LASERBRAIN_HOME': str(root), 'LASERBRAIN_AGENT': 'test-anchored'}
p = subprocess.Popen(['node', str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, text=True, env=env)
_n = [0]


def rpc(method, params):
    _n[0] += 1
    p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': _n[0],
                              'method': method, 'params': params}) + '\n')
    p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if not line:
            return {}
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get('id') == _n[0]:
            return d


def step(ok):
    EV.write_text(json.dumps({'ok': ok, 'fail': 0}))
    r = rpc('tools/call', {'name': 'check_state',
                           'arguments': {'goal': 'ship the thing',
                                         'progress': 'advancing', 'distance': 5}})
    return json.loads(r['result']['content'][0]['text'])


print('anchored reports observed work, and can reach 1.0\n')
try:
    rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                       'clientInfo': {'name': 't', 'version': '1'}})
    first = step(10)
    check('the first check has no interval behind it', first.get('anchored') == 0.5,
          str(first.get('anchored')))

    moved = step(11)
    check('work happened -> 1.0', moved.get('anchored') == 1,
          f"{moved.get('anchored')} — this assertion could not have passed before the fix")

    again = step(12)
    check('  and again on the next interval', again.get('anchored') == 1, str(again.get('anchored')))

    still = step(12)
    check('nothing happened -> back to 0.5', still.get('anchored') == 0.5,
          f"{still.get('anchored')} — the fix must not pin it the other way")

    resumed = step(13)
    check('  and it recovers when work resumes', resumed.get('anchored') == 1,
          str(resumed.get('anchored')))

    # THE SECOND CONSUMER. check_state does not surface `scores`, so the duplicate call is
    # invisible from its response — it happens because check_state runs the judgment layer
    # internally, and that builds `scores.evidence` from the same side-effecting reading.
    # phronesis surfaces it, so this is where the shared value can actually be seen.
    EV.write_text(json.dumps({'ok': 20, 'fail': 0}))
    r = rpc('tools/call', {'name': 'phronesis', 'arguments': {}})
    ph = json.loads(r['result']['content'][0]['text'])
    check('the judgment layer sees the work too',
          (ph.get('scores') or {}).get('evidence') == 1,
          f"scores.evidence={(ph.get('scores') or {}).get('evidence')}")
finally:
    p.terminate()
    p.wait(timeout=10)

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — the term that carries half of Φ is a measurement again, not a constant.')
