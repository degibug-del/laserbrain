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

# FIRST, above anything that resolves a path: this suite SETS user-turn, and user-turn is
# what turns an excursion into a reground. Shared, it was testing whichever suite ran next.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _testhome                                                   # noqa: E402
_testhome.isolate()

SERVER = pathlib.Path(__file__).resolve().parent / 'mcp-server.mjs'
FLAG = _testhome.config('user-turn')

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
B = 'write the kuramoto coupling controller for laserbot joints'
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

# ── 6. the HOOK actually writes the flag ────────────────────────────────────
# Everything above simulates the user turn by writing the flag itself, so all of it passed
# while the fix was completely inert: the flag write had been put in lb_coverage.py's
# EMBEDDED FALLBACK, which only runs when importing laserbrain.runtime fails. The live
# path never touched it. Five green assertions, one dead feature.
#
# A test that supplies its own precondition can never discover that nothing supplies it in
# production. This is the half that talks to the real hook.
# The path moved on 2026-07-27: the instruction layer got its own home in lasergear, and
# lasermind/hooks/lb_coverage.py became a fail-loud shim that exits with a message saying
# so. This test kept pointing at the shim, which produced a failure worth studying:
#
#   · the three POSITIVE assertions went red — correct, the shim writes no flag;
#   · the one NEGATIVE assertion ("but NOT on an ordinary tool call") stayed GREEN, because
#     nothing ran, so no flag appeared, so "no flag" was satisfied for entirely the wrong
#     reason.
#
# A negative assertion is satisfied by a missing subject. That is the same failure shape as
# a test whose command never executes, and it is why `hook()` now returns the exit status
# and demands the hook actually ran.
HOOK = pathlib.Path(__file__).parent.parent / 'lasergear' / 'lb_coverage.py'
if not HOOK.exists():
    show('the live hook exists', False, f'not at {HOOK}')
    print('\n  FAIL')
    raise SystemExit(1)


def hook(ev):
    """Run the real hook. Returns (flag_written, ran_ok) — never just the flag.

    `ran_ok` exists so a hook that refuses to start cannot satisfy a "did not write the
    flag" assertion. The shim this test used to point at exits non-zero with an
    explanation; it must fail the negative case, not pass it.
    """
    clear()
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev),
                       capture_output=True, text=True)
    return FLAG.exists(), r.returncode == 0


def wrote(ev):
    f, ran = hook(ev)
    return f and ran


show('the live hook writes the flag on a prompt',
     wrote({'session_id': 'probe', 'prompt': 'do the thing'}))
show('and on the camelCase shape a host sends',
     wrote({'sessionId': 'probe', 'userPrompt': 'do the thing'}))
show('and when only the event name says so',
     wrote({'session_id': 'probe', 'hook_event_name': 'UserPromptSubmit', 'prompt': 'x'}))
_flag, _ran = hook({'session_id': 'probe', 'tool_name': 'Bash',
                    'tool_input': {'command': 'ls'}})
show('but NOT on an ordinary tool call', _ran and not _flag,
     'otherwise every step would be a free re-ground'
     if _ran else 'the hook did not run at all — this assertion proves nothing')
clear()

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
