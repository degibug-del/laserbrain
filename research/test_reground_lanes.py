"""One re-ground license per user MESSAGE, not per lane (mcp-server.mjs consumeUserTurn).

WHY THIS SUITE EXISTS. On 2026-10-16 the license was changed to one per LANE per message, to
answer a real loss: in the drift log 6 of the 620 goal-drift readings with a session id came
right after a mid-turn user message, and in all 6 another run had consumed the `reground`
first. A checker then drove the server and showed the cost (2026-10-17): the flag file is one
per machine and carries no session, so every lane grounded before ANY message — parallel
subagents that never saw it, other sessions' runs — got a free pass on its next goal change.
Lanes B and C re-grounded where the original server said goal-drift. Nothing the hook can
write tells the server which lane received the message, so the change was reverted and this
suite pins the original rule:

  1. the first lane to change goal after a message re-grounds,
  2. a second lane changing goal on the same message is goal-drift (no free pass),
  3. the flag is consumed (deleted),
  4. a later message licenses one re-ground again.

Run:  python3 test_reground_lanes.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _testhome                                                   # noqa: E402
_testhome.isolate()
FLAG = _testhome.config('user-turn')
FLAG.unlink(missing_ok=True)

HERE = pathlib.Path(__file__).resolve().parent
SERVER = HERE / 'mcp-server.mjs'
fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(label)


def call(p, i, args):
    p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',
                              'params': {'name': 'check_state', 'arguments': args}}) + '\n')
    p.stdin.flush()
    for _ in range(500):
        line = p.stdout.readline()
        if not line:
            break
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get('id') == i:
            try:
                return json.loads(m['result']['content'][0]['text'])
            except Exception:
                return m.get('result') or {}
    print(f'  FAIL  no response (id {i}); server exit={p.poll()}')
    sys.exit(1)


if not SERVER.exists():
    print(f'  SKIPPED: no server at {SERVER}')
    sys.exit(0)

with tempfile.TemporaryDirectory() as td:
    env = dict(os.environ, LASERBRAIN_DRIFT_LOG=str(pathlib.Path(td) / 'drift.jsonl'),
               LASERBRAIN_AGENT='test-lanes')
    p = subprocess.Popen([os.environ.get('NODE', 'node'), str(SERVER)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    try:
        p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
            'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 't', 'version': '1'}}}) + '\n')
        p.stdin.flush()
        for _ in range(200):
            line = p.stdout.readline()
            if not line or '"id":0' in line.replace(' ', ''):
                break

        def st(i, lane, goal):
            return call(p, i, {'goal': goal, 'progress': 'advancing', 'distance': 5, 'session': lane})

        st(1, 'parent', 'fix the tokenizer bug in the parser module')
        st(2, 'kid', 'write reference docs for every CLI flag')
        time.sleep(1.2)
        FLAG.parent.mkdir(parents=True, exist_ok=True)
        FLAG.write_text('2026-10-16T00:00:00+00:00')           # the user spoke mid-turn
        r = st(3, 'kid', 'paint the company logo purple and gold')
        check('1. the first lane to change goal after the message re-grounds',
              r.get('reason') == 'reground', r.get('reason'))
        r = st(4, 'parent', 'migrate the billing database schema to postgres')
        check('2. a second lane on the same message is goal-drift, not a free pass',
              r.get('reason') == 'goal-drift', r.get('reason'))
        check('3. the flag is consumed', not FLAG.exists())
        time.sleep(1.1)
        FLAG.write_text('next')                                  # a later message
        r = st(5, 'parent', 'design a garden irrigation layout')
        check('4. a later message licenses one re-ground again', r.get('reason') == 'reground',
              r.get('reason'))
    finally:
        p.kill()
        FLAG.unlink(missing_ok=True)

print('\n  ' + ('PASS — one re-ground per user message.' if not fails
                else f'FAIL — {len(fails)}: ' + '; '.join(fails)))
raise SystemExit(0 if not fails else 1)
