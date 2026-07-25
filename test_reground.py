#!/usr/bin/env python3
"""test_reground.py — goal-drift must stay silent on redirection and loud on drift.

Drives the real MCP server over stdio, so this tests the thing that actually answers
check_state rather than a reimplementation of it.

The two halves matter equally. Suppressing the false alarm is easy — deleting the rule
does that. What has to be shown is that the rule still fires when nobody redirected
anything, and that one user turn buys exactly ONE re-ground rather than a standing
exemption for an agent that then wanders.
"""
import json, subprocess, pathlib, os, sys

SERVER = pathlib.Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis/laserbrain/mcp-server.mjs'
FLAG = pathlib.Path.home() / '.config/laserbrain/user-turn'

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def run(script):
    """script: list of ('check', goal, progress, distance) or ('user',) or ('reset',)."""
    msgs, i = [], 0
    def send(method, params):
        nonlocal i
        i += 1
        msgs.append(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}))
    send('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                        'clientInfo': {'name': 't', 'version': '1'}})
    marks = []
    for step in script:
        if step[0] == 'user':
            marks.append(len(msgs)); continue
        if step[0] == 'reset':
            send('tools/call', {'name': 'reset_task', 'arguments': {}}); continue
        _, goal, prog, dist = step
        send('tools/call', {'name': 'check_state',
                            'arguments': {'goal': goal, 'progress': prog, 'distance': dist}})
    # user turns are simulated by writing the flag between calls, which is exactly what
    # the UserPromptSubmit hook does — so run the script in pieces around them.
    return msgs


def call(proc, payload):
    proc.stdin.write(json.dumps(payload) + '\n')
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get('id') == payload['id']:
            return d


def session():
    env = {**os.environ, 'LASERBRAIN_AGENT': 'test'}
    p = subprocess.Popen([ 'node', str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env)
    call(p, {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
             'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                        'clientInfo': {'name': 't', 'version': '1'}}})
    return p


def check(p, n, goal, prog='advancing', dist=5):
    r = call(p, {'jsonrpc': '2.0', 'id': n, 'method': 'tools/call',
                 'params': {'name': 'check_state',
                            'arguments': {'goal': goal, 'progress': prog, 'distance': dist}}})
    txt = json.dumps(r)
    m = json.loads(r['result']['content'][0]['text']) if 'result' in r else {}
    return m


def user_spoke():
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    FLAG.write_text('test')


def clear():
    FLAG.unlink(missing_ok=True)


A = 'fix the mobile layout bugs on the laserbrain billboard at 375px'
B = 'write the kuramoto coupling controller for laserbeast joints'
C = 'score the dogfood corpus and report precision honestly'

# ── 1. the false alarm this exists to kill ──────────────────────────────────
clear()
p = session()
check(p, 1, A)                                  # ground
r = check(p, 2, A)
show('a matching goal is not drift', not r.get('drifting'), r.get('reason'))
user_spoke()
r = check(p, 3, B)
show('a new goal right after the user speaks is a REGROUND',
     not r.get('drifting') and r.get('reason') == 'reground', r.get('reason'))
p.kill()

# ── 2. and the detection it must not destroy ────────────────────────────────
clear()
p = session()
check(p, 1, A)
r = check(p, 2, B)
show('the same jump with NO user turn is still goal-drift',
     r.get('drifting') and r.get('reason') == 'goal-drift', r.get('reason'))
p.kill()

# ── 3. one turn buys ONE re-ground, not an exemption ────────────────────────
clear()
p = session()
check(p, 1, A)
user_spoke()
r1 = check(p, 2, B)
r2 = check(p, 3, C)                             # wandered again, user said nothing
show('the flag is consumed, so a second jump still fires',
     (not r1.get('drifting')) and r2.get('drifting') and r2.get('reason') == 'goal-drift',
     f"first={r1.get('reason')} second={r2.get('reason')}")
show('and the flag file is gone after being consumed', not FLAG.exists())
p.kill()

# ── 4. the re-ground actually re-grounds ────────────────────────────────────
clear()
p = session()
check(p, 1, A)
user_spoke()
check(p, 2, B)                                  # reground onto B
r = check(p, 3, B)
show('after a re-ground the NEW goal is the ground',
     not r.get('drifting'), r.get('reason'))
p.kill()

# ── 5. fail open ────────────────────────────────────────────────────────────
clear()
p = session()
check(p, 1, A)
r = check(p, 2, B)
show('with no flag at all the old behaviour is exact',
     r.get('drifting') and r.get('reason') == 'goal-drift', r.get('reason'))
p.kill()
clear()

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
