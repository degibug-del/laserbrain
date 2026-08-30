#!/usr/bin/env python3
"""A subagent must not overwrite its parent's ground.

WHAT HAPPENED, 2026-08-05

`drift` was a single module-level object in mcp-server.mjs. One server process serves one
stdio connection, and that looked like one agent — until subagents. They run inside the same
client process and share its MCP connection, so every one of them landed on that object.

A wave of five was launched. A child's hook called reset_task and check_state on the parent's
server, and the drift log records run ccdb41cb with 39 rows under the goal "Play the
tr87-cd924810 grid puzzle" — the child's task, written into the parent's ground. The parent's
next check scored its own BYTE-IDENTICAL goal string at 0.03 and read goal-drift.

It is the same shared-state class as the corpus pollution fixed the same day: one store, many
writers, no partition, and the symptom is a verdict that looks like a product bug.

WHY IT COULD NOT BE FIXED BY PARTITIONING WHAT WAS THERE

Nothing identifies a caller. A tools/call carries a name and arguments — no session, no
client id, nothing per-connection that differs between a parent and its children. The key
had to be supplied by the caller, so `session` was added.

ADDITIVE. Omit it and every caller shares one lane, byte-identical to the old behaviour.
That is asserted below, because a partition that silently changed the default would break
every agent already running.
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


class Server:
    def __init__(self):
        root = tempfile.mkdtemp(prefix='lb-lanes-')
        env = {**os.environ, 'LASERBRAIN_HOME': root, 'LASERBRAIN_AGENT': 'test-lanes'}
        self.p = subprocess.Popen(['node', str(SERVER)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, env=env)
        self.n = 0
        self._rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                 'clientInfo': {'name': 't', 'version': '1'}})

    def _rpc(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.n,
                                       'method': method, 'params': params}) + '\n')
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                return {}
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get('id') == self.n:
                return d

    def call(self, tool, **args):
        r = self._rpc('tools/call', {'name': tool, 'arguments': args})
        try:
            return json.loads(r['result']['content'][0]['text'])
        except Exception:
            return {'raw': r.get('result', {}).get('content', [{}])[0].get('text')}

    def close(self):
        self.p.terminate()
        self.p.wait(timeout=10)


PARENT = 'benchmark laserbrain on ARC-AGI with fresh naive agents'
CHILD = 'Play the tr87-cd924810 grid puzzle for about 25 steps'

print('a child with its own session cannot touch the parent\'s ground\n')
s = Server()
try:
    s.call('check_state', goal=PARENT, progress='advancing', distance=6, session='parent')
    s.call('check_state', goal=PARENT, progress='advancing', distance=5, session='parent')
    # the child arrives, resets, and runs its own task — the exact sequence that broke it
    s.call('reset_task', session='child-1')
    for d in (9, 8, 7):
        s.call('check_state', goal=CHILD, progress='advancing', distance=d, session='child-1')
    v = s.call('check_state', goal=PARENT, progress='advancing', distance=4, session='parent')
    check('the parent still holds its own goal', v.get('goal_score') == 1,
          f"goal_score {v.get('goal_score')}  reason {v.get('reason')}")
    check('  and is not reading drift', v.get('reason') != 'goal-drift', str(v.get('reason')))
    c = s.call('check_state', goal=CHILD, progress='advancing', distance=6, session='child-1')
    check('  while the child holds ITS goal', c.get('goal_score') == 1,
          f"goal_score {c.get('goal_score')}")
finally:
    s.close()

print()
print('and the bug reproduces exactly when they share a lane — this is the control')
s2 = Server()
try:
    s2.call('check_state', goal=PARENT, progress='advancing', distance=6)
    s2.call('check_state', goal=PARENT, progress='advancing', distance=5)
    s2.call('reset_task')
    for d in (9, 8, 7):
        s2.call('check_state', goal=CHILD, progress='advancing', distance=d)
    v2 = s2.call('check_state', goal=PARENT, progress='advancing', distance=4)
    check('no session -> the parent IS stomped, as before', v2.get('goal_score', 1) < 0.3,
          f"goal_score {v2.get('goal_score')} — the old behaviour, unchanged by default")
finally:
    s2.close()

print()
print('omitting the key changes nothing for a single agent')
s3 = Server()
try:
    out = [s3.call('check_state', goal=PARENT, progress='advancing', distance=d).get('reason')
           for d in (7, 6, 5, 5, 5, 5, 5)]
    check('a lone agent reads exactly as it always did', out[0] == 'grounded' and 'stalled' in out,
          str(out))
finally:
    s3.close()

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — a declared session gets its own ground; omitting it is the old behaviour,')
print('  including the stomping, which is the honest default until callers pass a key.')
