#!/usr/bin/env python3
"""The gate's response must be proportional to the lapse, not bang-bang.

WHAT THIS REPLACES

The gate did nothing until BLOCK_AFTER and then refused EVERYTHING. That is the crudest
controller there is, and the cost landed on the wrong calls: in practice most refusals hit
a Read or a grep — work that changes nothing and existed only to inform the next check.
Each one cost a full round trip AND the drafted call, which the gate's own message admits:
"A draft composed inside a blocked call is gone."

The actuator is binary — a call runs or it does not — so proportionality cannot live in the
strength of one refusal. It lives in WHICH calls are refused as the error grows:

    below the threshold      nothing refused
    just past it             side-effecting calls only; reads pass, with a warning
    past block_after * 2     everything, which is the old behaviour

The middle band is the point. A drifted agent can still read, grep and orient — that is how
it works out what to spell — but cannot write or edit against a goal it has not stated. The
instrument's claim is about the relationship between a spelled goal and an ACTION. Refusing
a read was never that claim.

WHAT MUST HOLD

  READS PASS IN THE MIDDLE      the whole cost reduction. If this regresses the change is
                                worthless and the gate is bang-bang again with extra code.
  WRITES DO NOT                 otherwise the middle band is no gate at all.
  THE HARD STOP STILL STOPS     past the multiple, a read is refused too. The old behaviour
                                is kept for the case it was built for.
  NO DEADLOCK                   check_state itself is allowed at every stage. Blocking the
                                call the gate demands is the one bug here with no
                                workaround, and it must be re-proven per stage.
  A WARNING IS NOT A BLOCK      warn() writes stderr and exits 0. The hook contract reads a
                                non-zero exit as a refusal, so a warning built on deny()'s
                                shape would silently become a block.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
GEAR = HERE.parent / 'lasergear'
GATE = GEAR / 'lb_gate.py'
sys.path.insert(0, str(GEAR))

from lb_gate import BLOCK_AFTER, HARD_MULTIPLE, probe_arm       # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


CONTROL = next(f's{i}' for i in range(5000) if probe_arm(f's{i}') == 'control')


def session(dirpath, sid, steps, checks_at):
    d = {'id': sid, 'goal': 'ship the parser', 'steps': steps,
         'checks': [{'step': s, 'goal': 'ship the parser', 'drifting': False,
                     'reason': 'advancing'} for s in checks_at],
         'inferred': [], 'catches': [], 'events': []}
    (pathlib.Path(dirpath) / f'{sid}.json').write_text(json.dumps(d))


def run(dirpath, sid, tool, args=None):
    """Invoke the gate as the host does. Returns (blocked, warned, text)."""
    ev = {'session_id': sid, 'tool_name': tool, 'tool_input': args or {}}
    env = dict(os.environ, LASERBRAIN_STATE_DIR=str(dirpath))
    env.pop('LASERBRAIN_MIN_COVERAGE', None)
    p = subprocess.run([sys.executable, str(GATE)], input=json.dumps(ev),
                       capture_output=True, text=True, env=env, timeout=120)
    text = (p.stderr or '') + (p.stdout or '')
    return p.returncode == 2, ('laserbrain gate' in text and p.returncode == 0), text


MID = BLOCK_AFTER + 1                      # past the threshold, inside the courtesy band
HARD = BLOCK_AFTER * HARD_MULTIPLE + 1     # past the escalation point

print(f'  thresholds: block_after={BLOCK_AFTER}  hard at {BLOCK_AFTER * HARD_MULTIPLE}')
print()
print(f'THE MIDDLE BAND — {MID} steps since a check')
with tempfile.TemporaryDirectory() as d:
    session(d, CONTROL, MID, [0])
    blocked, warned, txt = run(d, CONTROL, 'Read', {'file_path': '/tmp/x'})
    check('a READ passes', not blocked, txt.strip().splitlines()[0][:64] if txt.strip() else 'silent')
    check('  and says what is already being refused', warned and 'Reads still pass' in txt,
          'escalation must never be a surprise')
    check('  naming where the hard stop is', str(BLOCK_AFTER * HARD_MULTIPLE) in txt)

    blocked_w, _, txt_w = run(d, CONTROL, 'Write', {'file_path': '/tmp/x', 'content': 'y'})
    check('a WRITE is refused', blocked_w,
          txt_w.strip().splitlines()[0][:64] if blocked_w else 'ALLOWED — the band is no gate')
    check('  and says reads are still passing', 'reads are still passing' in txt_w)

    blocked_e, _, _ = run(d, CONTROL, 'Edit', {'file_path': '/tmp/x'})
    check('an EDIT is refused too', blocked_e)

print()
print(f'THE HARD STOP — {HARD} steps since a check')
with tempfile.TemporaryDirectory() as d:
    session(d, CONTROL, HARD, [0])
    blocked_r, _, txt_r = run(d, CONTROL, 'Read', {'file_path': '/tmp/x'})
    check('now even a READ is refused', blocked_r,
          'the old behaviour, kept for what it was built for')
    check('  and says so', 'every call' in txt_r, txt_r.strip().splitlines()[0][:60])

print()
print('NO DEADLOCK — check_state is allowed at EVERY stage')
for label, steps in (('middle', MID), ('hard', HARD), ('far past', HARD * 3)):
    with tempfile.TemporaryDirectory() as d:
        session(d, CONTROL, steps, [0])
        blocked_c, _, _ = run(d, CONTROL, 'mcp__laserbrain__check_state')
        check(f'check_state allowed in the {label} stage', not blocked_c)

print()
print('A WARNING IS NOT A BLOCK — the contract reads exit codes, not intent')
with tempfile.TemporaryDirectory() as d:
    session(d, CONTROL, MID, [0])
    ev = {'session_id': CONTROL, 'tool_name': 'Read', 'tool_input': {'file_path': '/tmp/x'}}
    env = dict(os.environ, LASERBRAIN_STATE_DIR=str(d))
    env.pop('LASERBRAIN_MIN_COVERAGE', None)
    p = subprocess.run([sys.executable, str(GATE)], input=json.dumps(ev),
                       capture_output=True, text=True, env=env, timeout=120)
    check('the warning exits 0', p.returncode == 0, f'exit {p.returncode}')
    check('  and emits no deny payload', 'permissionDecision' not in (p.stdout or ''),
          'a deny-shaped warning would silently be a block')

print()
print('AND BELOW THE THRESHOLD THE GATE IS STILL SILENT')
with tempfile.TemporaryDirectory() as d:
    session(d, CONTROL, 2, [0, 1])
    blocked_q, warned_q, txt_q = run(d, CONTROL, 'Write', {'file_path': '/tmp/x'})
    check('no block and no warning while compliant', not blocked_q and not warned_q,
          txt_q.strip()[:60] or 'silent')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    sys.exit(1)
print('  PASS — the refusal is proportional to the lapse: orient freely, act only from a')
print('  position you have spelled, and stop entirely once it has gone too far.')


# ══════════════════════════════════════════════════════════════════════════════════════
# A BROKEN GATE MUST FAIL OPEN — AND SAY SO
#
# The handler at the bottom of lb_gate.py swallowed every exception. The policy is right:
# a broken gate must not stop an agent working. The SILENCE was not.
#
# 2026-08-05: a one-character slip in that file — `s` where `sess` was meant — raised
# NameError on every relaxed-arm call, and the handler ate it. The gate was OFF for half of
# all sessions, and the only symptom was that it never fired, which is indistinguishable
# from the relaxed arm working exactly as designed. It surfaced because a test asked where
# the threshold was, not because anything noticed the instrument had stopped.
#
# stderr and a log, never a deny: turning a crash into a block is the one failure direction
# this handler exists to prevent.
# ══════════════════════════════════════════════════════════════════════════════════════
import shutil as _sh                                              # noqa: E402

print()
print('a broken gate fails open, and announces that it has')
with tempfile.TemporaryDirectory() as d:
    session(d, CONTROL, 20, [0])
    _broken = pathlib.Path(d, 'lb_gate_broken.py')
    _broken.write_text(GATE.read_text().replace(
        'arm = probe_arm(sid)', 'arm = probe_arm(undefined_name)', 1))
    _ev = {'session_id': CONTROL, 'tool_name': 'Write', 'tool_input': {'file_path': '/tmp/x'}}
    _env = dict(os.environ, LASERBRAIN_STATE_DIR=str(d))
    _env.pop('LASERBRAIN_MIN_COVERAGE', None)
    _r = subprocess.run([sys.executable, str(_broken)], input=json.dumps(_ev),
                        capture_output=True, text=True, env=_env, timeout=120)
    check('it does NOT block', _r.returncode == 0, f'exit {_r.returncode}')
    check('  it announces on stderr', 'FAILED OPEN' in _r.stderr,
          (_r.stderr.strip().splitlines() or ['(silent)'])[0][:60])
    check('  it names the error', 'NameError' in _r.stderr)
    check('  and it leaves a record', (pathlib.Path(d) / 'gate-errors.jsonl').exists())

    # the healthy gate on the identical session must still refuse — otherwise the test
    # above would pass for a gate that had simply stopped working everywhere.
    _ok = subprocess.run([sys.executable, str(GATE)], input=json.dumps(_ev),
                         capture_output=True, text=True, env=_env, timeout=120)
    check('and the WORKING gate still blocks the same call', _ok.returncode == 2,
          f'exit {_ok.returncode} — without this, the check above proves nothing')

print()
print('the gap probe sweeps only the relaxed arm, and stays inside its bounds')
from lb_gate import GAP_DRAWS, gap_probe                          # noqa: E402
_draws = {gap_probe('abc', i) for i in range(400)}
check('every draw is one of the declared values', _draws <= set(GAP_DRAWS), str(sorted(_draws)))
check('  and it never exceeds the relaxed arm it inherits from',
      max(GAP_DRAWS) <= 12, f'max draw {max(GAP_DRAWS)}')
check('  stable for a given (session, gap)', len({gap_probe('abc', 7) for _ in range(50)}) == 1)

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    sys.exit(1)
print('  PASS — the response is proportional, the sweep is bounded, and a gate that')
print('  breaks says so instead of quietly protecting nothing.')


# ══════════════════════════════════════════════════════════════════════════════════════
# EVERY FIRE IS RECORDED — otherwise the gate's cost is unknowable
#
# The gate logged its arms and its errors and said nothing about the thing it exists to do.
# That gap is load-bearing:
#
#   /laserbrain publishes "22.2% — what it costs to run", counted from the checks an agent
#   MADE. It cannot count the calls this gate destroyed, each a round trip plus a lost
#   draft. The published figure is a FLOOR, and the distance above it is what this log
#   measures. The proportional band, added the same day on the argument that refusing reads
#   is pure cost, is likewise unmeasured — and the agent who wrote it works mostly through
#   Bash, which the allowlist treats as acting, so it may help almost nobody.
#
# No command text: tool, stage and the numbers behind the decision answer every question
# above, and a log of what an agent was about to run is a privacy surface with no payoff.
# ══════════════════════════════════════════════════════════════════════════════════════
print()
print('every stage leaves a row, and check_state leaves none')
with tempfile.TemporaryDirectory() as d:
    session(d, CONTROL, MID, [0])
    run(d, CONTROL, 'Read', {'file_path': '/tmp/x'})
    run(d, CONTROL, 'Write', {'file_path': '/tmp/x'})
    session(d, CONTROL, HARD, [0])
    run(d, CONTROL, 'Read', {'file_path': '/tmp/x'})
    run(d, CONTROL, 'mcp__laserbrain__check_state')

    _log = pathlib.Path(d) / 'refusals.jsonl'
    check('the log exists', _log.exists())
    _rows = [json.loads(l) for l in _log.read_text().splitlines() if l.strip()] if _log.exists() else []
    _stages = [r.get('stage') for r in _rows]
    check('the allowed read is recorded as a warn', 'warn' in _stages, str(_stages))
    check('the refused write is recorded as acting', 'acting' in _stages, str(_stages))
    check('the hard stop is recorded as hard', 'hard' in _stages, str(_stages))
    check('check_state is never recorded', all('check_state' not in (r.get('tool') or '') for r in _rows),
          'the call the gate demands must not appear in its own refusal log')
    check('every row carries what produced the decision',
          all({'since', 'coverage', 'block_after', 'arm', 'tool'} <= set(r) for r in _rows),
          str(sorted(_rows[0])) if _rows else 'no rows')
    check('and no row carries a command', all('command' not in r for r in _rows),
          'tool names only — a log of pending commands is a privacy surface')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    sys.exit(1)
print('  PASS — the gate is proportional, bounded, loud when broken, and now countable.')
