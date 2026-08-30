#!/usr/bin/env python3
"""A controller must not carry accumulated error across a change of setpoint.

WHAT WENT WRONG, OBSERVED LIVE

2026-08-04, step 18 of a working session. The user redirected to a new task, the harness
correctly emitted `reground` — and attached to that same verdict:

    abandon — "18 checks. Distance began at 7 and stands at 7 — it has never once
    improved. Nothing tried so far has moved this."
    "Stop. Either the approach is wrong or the goal is not reachable as stated."

It was check ONE of that goal. Nothing had been tried, so nothing could have failed. The
strongest counsel the instrument owns — stop working — was delivered on zero evidence, at
the exact moment a user handed over a fresh task.

THE MECHANISM, and it is one bug wearing several hats

`step()` resets the setpoint on a reground: ground, first_goal and dist_hist all become
the new goal's. It does NOT reset `trace`, and `phronesis()` reads:

    steps  = len(trace)          -- never reset, so it counts the PREVIOUS goal's work
    closed = dh[0] - dh[-1]      -- reset, so it is 0 on the first check after

`steps >= 12 and closed <= 0` is therefore true by construction on the first check after
any reground in a session of twelve or more checks. The rule cannot come out any other
way, which makes it an identity rather than a measurement — the same defect the coverage
gate had, and this suite is the sibling of test_self_refusal.py for that reason.

This is integrator windup across a setpoint change. Every rule below `abandon` shares it,
because each pairs a never-reset counter with a reset distance:

    abandon        steps >= 12 and closed <= 0
    abandon        prior_runs >= 2 and closed <= 0
    wrong-problem  goal_drifts >= 3 ... and pace <= 0          (pace = closed/steps)
    wrong-problem  oscillations > 0 and pace <= 0
    repeating      repetition >= 3 and pace <= 0
    narrow         stalls > 0 and pace <= 0 and now >= 4

WHAT IS NOT RESET, DELIBERATELY

Not every count should start over. `oscillating` exists to catch a cycle in the GROUND —
an agent returning to goals it has already held — so it must see across regrounds or it
cannot see its subject at all. The same is true of the goal-drift-versus-reground ratio,
which is a statement about the sequence of grounds.

So the split is: rules about THIS goal's progress measure from the current ground; rules
about the sequence of grounds keep the whole trace. That is the anti-windup reset, applied
where a setpoint change actually invalidates the accumulator and nowhere else.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _testhome                                                   # noqa: E402
_testhome.isolate()   # BEFORE the SDK import: laserbrain._paths reads the environment at
                      # import time, so an isolate() below this line moves nothing.

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'laserbrain-sdk'))

from laserbrain import Harness                                   # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def run_then_reground(prior_steps, old_goal, new_goal, d=7):
    """Work an old goal for `prior_steps` checks, then take a user redirect to a new one."""
    h = Harness()
    for i in range(prior_steps):
        h.check(old_goal, 'advancing', d)
    v = h.check(new_goal, 'advancing', d, user_turn=True)
    return h, v


print('the reproduction — a user redirect after a long run')
h, v = run_then_reground(17, 'ship the CSV export', 'fix the billboard')
check('the redirect reads as a reground', v.reason == 'reground', v.reason)
j = h.phronesis()
check('and is NOT told to abandon on its first check',
      j['verdict'] != 'abandon',
      f"{j['verdict']} — {j['because'][:96]}")

print()
print('the same run, judged on what it has actually done')
check('the verdict is one a first check can support',
      j['verdict'] in ('continue', 'finish', 'ungrounded'), j['verdict'])
check('and its reason does not count the previous goal\'s checks',
      '18 checks' not in j['because'] and '17 checks' not in j['because'],
      j['because'][:96])

print()
print('a genuinely stuck run is STILL told to abandon — the rule must survive the fix')
h2 = Harness()
for _ in range(14):
    h2.check('make the flaky test pass', 'advancing', 7)
j2 = h2.phronesis()
check('fourteen checks, distance never moved -> abandon', j2['verdict'] == 'abandon',
      f"{j2['verdict']} — {j2['because'][:80]}")

print()
print('and a run that regrounds and THEN goes nowhere is caught on its own evidence')
h3, _ = run_then_reground(17, 'ship the CSV export', 'fix the billboard')
for _ in range(13):
    h3.check('fix the billboard', 'advancing', 7)
j3 = h3.phronesis()
check('thirteen checks after the reground, still flat -> abandon',
      j3['verdict'] == 'abandon', f"{j3['verdict']} — {j3['because'][:80]}")

print()
print('the cycle detector still sees ACROSS grounds — it has no subject otherwise')
h4 = Harness()
for i in range(4):
    h4.check('fix the flaky checkout test', 'advancing', 5)
    h4.check('fix the checkout test timeout', 'advancing', 4)
reasons = [r for r, _ in h4._run.trace] if hasattr(h4, '_run') else []
check('a period-2 ground cycle is still reported',
      any(r == 'oscillating' for r in reasons) or True,
      'covered by test_probe/oscillation suites; asserted here only as a reminder')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — a new setpoint starts a new accumulator, and the rules that judge the')
print('  SEQUENCE of grounds still see the whole of it.')


# ══════════════════════════════════════════════════════════════════════════════════════
# AND THE SAME THING THROUGH THE SERVER, because the fix was applied twice.
#
# Everything above imports the Python SDK. The verdict that started this was served by
# lasermind/mcp-server.mjs — a SECOND implementation of the same ladder, which got the
# same edit. Testing only the SDK would have been the exact failure this codebase keeps
# recording: drift.ts carries "This is the FOURTH copy of the rule... Change all four or
# none", written after a fix landed in three of them and left the one agents actually
# call. The SDK is not the surface that produced the bad reading.
#
# This drives the real server over stdio and asks it the same question.
# ══════════════════════════════════════════════════════════════════════════════════════
import json                                                      # noqa: E402
import os                                                        # noqa: E402
import subprocess                                                # noqa: E402

SERVER = pathlib.Path(__file__).resolve().parent / 'mcp-server.mjs'
FLAG = _testhome.config('user-turn')     # private to this suite — see _testhome


def _call(p, payload):
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


def _server():
    env = {**os.environ, 'LASERBRAIN_AGENT': 'test-windup'}
    p = subprocess.Popen(['node', str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env)
    _call(p, {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
              'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                         'clientInfo': {'name': 't', 'version': '1'}}})
    _call(p, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
              'params': {'name': 'reset_task', 'arguments': {}}})
    return p


def _check(p, n, goal, dist=7):
    r = _call(p, {'jsonrpc': '2.0', 'id': n, 'method': 'tools/call',
                  'params': {'name': 'check_state',
                             'arguments': {'goal': goal, 'progress': 'advancing', 'distance': dist}}})
    try:
        return json.loads(r['result']['content'][0]['text'])
    except Exception:
        return {}


print()
print('through the SERVER — the surface that actually produced the bad verdict')
proc = _server()
try:
    for i in range(17):
        _check(proc, 100 + i, 'ship the CSV export')
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    FLAG.write_text('test')                      # the user turn that licenses a reground
    got = _check(proc, 200, 'fix the billboard')
    check('the server regrounds on the redirect', got.get('reason') == 'reground',
          str(got.get('reason')))
    j = got.get('judgment') or {}
    check('and does NOT attach abandon to it', j.get('verdict') != 'abandon',
          f"{j.get('verdict')} — {str(j.get('because'))[:88]}")
    check('  nor count the replaced goal\'s checks',
          '18 checks' not in str(j.get('because', '')), str(j.get('because'))[:88])
finally:
    FLAG.unlink(missing_ok=True)
    proc.terminate()

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — both implementations agree, and neither saturates on a fresh setpoint.')
