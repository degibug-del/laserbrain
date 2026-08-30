#!/usr/bin/env python3
"""The gate interval must be falsifiable, and the probe must never be able to deadlock.

WHY THE PROBE EXISTS

BLOCK_AFTER = 4 was chosen from a simulation — 4 -> 20% coverage is arithmetic about how
often a minimal agent would check, not a measurement of whether 4 beats 12 at anything.
And it cannot be measured while it holds, because it manufactures its own evidence:

    2-3 steps    18/224    8.0%
    4-7 steps   154/1397  11.0%     z = 1.35
    8-15 steps    0/5

85% of every gap sits in 4-7 because the gate puts it there. So a stable minority of
sessions run relaxed, both arms are tagged, and the question becomes answerable.

WHAT MUST HOLD, and the last two are the ones that would hurt

  THE ARMS DIFFER          a control session blocks at 4, a relaxed one does not, and
                           blocks at 12. If they behaved the same the probe would collect
                           nothing while looking like it was working.
  BOTH THRESHOLDS MOVE     relaxing only BLOCK_AFTER changes nothing, because the coverage
                           term closes the gate at the floor regardless. The bug this
                           catches is a probe that runs for weeks and yields no long gaps.
  ASSIGNMENT IS STABLE     the hook re-enters on EVERY tool call. An arm that is re-rolled
                           per call would put one session in both arms and destroy the
                           comparison silently.
  AN EXPLICIT FLOOR WINS   a benchmark that sets LASERBRAIN_MIN_COVERAGE has decided its
                           own coverage; it must not be conscripted into an experiment.
  NEITHER ARM DEADLOCKS    check_state must always be allowed. Blocking the call the gate
                           demands is the one bug here with no workaround.
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

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def session(dirpath, sid, steps, checks_at):
    """A session file with `steps` steps and checks recorded at the given step numbers."""
    d = {'id': sid, 'goal': 'ship the parser', 'steps': steps,
         'checks': [{'step': s, 'goal': 'ship the parser', 'drifting': False,
                     'reason': 'advancing'} for s in checks_at],
         'inferred': [], 'catches': [], 'events': []}
    (pathlib.Path(dirpath) / f'{sid}.json').write_text(json.dumps(d))
    return d


def run_gate(dirpath, sid, tool='Bash', env_extra=None):
    """Invoke the gate as the host does. Returns (blocked, reason)."""
    ev = {'session_id': sid, 'tool_name': tool,
          'tool_input': {'command': 'ls'} if tool == 'Bash' else {}}
    env = dict(os.environ, LASERBRAIN_STATE_DIR=str(dirpath))
    env.pop('LASERBRAIN_MIN_COVERAGE', None)
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, str(GATE)], input=json.dumps(ev),
                       capture_output=True, text=True, env=env, timeout=120)
    return p.returncode == 2, (p.stderr or '') + (p.stdout or '')


from lb_gate import probe_arm                                    # noqa: E402
from lb_coverage import load as cov_load                         # noqa: E402

# Find one session id in each arm, so the test does not depend on a particular string
# hashing a particular way.
relaxed_id = next(f's{i}' for i in range(5000) if probe_arm(f's{i}') == 'relaxed')
control_id = next(f's{i}' for i in range(5000) if probe_arm(f's{i}') == 'control')

print(f'  arms found: relaxed={relaxed_id!r}  control={control_id!r}')
print()
print('THE ARMS DIFFER — at 6 steps since the last check')
with tempfile.TemporaryDirectory() as d:
    # 6 steps in, one check at step 0: 6 since the last check, coverage 1/6 = 17%.
    session(d, control_id, 6, [0])
    session(d, relaxed_id, 6, [0])
    cb, creason = run_gate(d, control_id)
    rb, _ = run_gate(d, relaxed_id)
    check('control blocks', cb, creason.strip().splitlines()[0][:60] if cb else 'allowed')
    # The relaxed arm DRAWS its allowance per gap from GAP_DRAWS now, so at 6 steps it
    # blocks or not depending on the draw — asserting "does not" pinned the old flat 12.
    # What must still hold is that it is never STRICTER than control.
    from lb_gate import gap_probe                                 # noqa: E402
    drawn = gap_probe(relaxed_id, 1) or 12
    check('relaxed is never stricter than control', drawn >= 4, f'drew {drawn}')
    check('  and blocks only once past its own draw', rb == (6 >= drawn),
          f'drew {drawn}, since=6, blocked={rb}')

print()
print('BOTH THRESHOLDS MOVED — the relaxed arm survives thin coverage')
# The bug this catches: relaxing only BLOCK_AFTER leaves the coverage term closing the
# gate at the floor, so the probe never produces a single long gap.
with tempfile.TemporaryDirectory() as d:
    # THE CHECK MUST BE RECENT, or this measures the wrong term. A first version used
    # checks at [0, 1] over 20 steps: coverage 10% as intended, but `since` = 19, so the
    # gate closed on the step-gap and the assertion read "blocked" while proving nothing
    # about the floor. Checks at [0, 19] give the same 10% coverage with `since` = 1, so
    # only the coverage term can fire.
    session(d, relaxed_id, 20, [0, 19])      # coverage 10% — under the 20% floor
    rb, reason = run_gate(d, relaxed_id)
    check('10% coverage does not block the relaxed arm', not rb, reason.strip()[:70])
    session(d, control_id, 20, [0, 19])
    cb, creason = run_gate(d, control_id)
    check('  and does block the control arm', cb)
    check('  on the FLOOR, not the step-gap', 'below the' in creason, creason.strip()[:70])

print()
print('the relaxed arm still closes — it is longer, not absent')
with tempfile.TemporaryDirectory() as d:
    session(d, relaxed_id, 14, [0])          # 14 since the last check, past 12
    rb, reason = run_gate(d, relaxed_id)
    check('blocks at 14 steps', rb, reason.strip().splitlines()[0][:60] if rb else 'allowed')

print()
print('AN EXPLICIT FLOOR WINS — a benchmark is not conscripted')
with tempfile.TemporaryDirectory() as d:
    session(d, relaxed_id, 20, [0, 1])
    rb, _ = run_gate(d, relaxed_id, env_extra={'LASERBRAIN_MIN_COVERAGE': '0.5'})
    check('relaxed + explicit floor blocks like control', rb)

print()
print('NEITHER ARM CAN DEADLOCK')
with tempfile.TemporaryDirectory() as d:
    for sid, arm in ((control_id, 'control'), (relaxed_id, 'relaxed')):
        session(d, sid, 40, [0])             # far past every threshold
        blocked, _ = run_gate(d, sid, tool='mcp__laserbrain__check_state')
        check(f'check_state is allowed in the {arm} arm', not blocked)

print()
print('ASSIGNMENT IS STABLE AND PROPORTIONED')
check('the same id always gives the same arm',
      len({probe_arm('abc') for _ in range(50)}) == 1)
# READ THE SHARE, do not retype it. This asserted "~15%" as a literal and went red the
# moment the constant moved to 50 — the test was pinning a number rather than the property
# that the split MATCHES what the gate says it is.
from lb_gate import probe_share                                  # noqa: E402
_share = probe_share()
n = sum(probe_arm(f'id-{i}') == 'relaxed' for i in range(4000))
check(f'the split matches the declared share — {_share}% (got {n / 40:.1f}%)',
      abs(n / 40 - _share) <= 5, f'{n}/4000')
check('an empty session id is control, never relaxed', probe_arm('') == 'control')
check('a None session id is control', probe_arm(None) == 'control')

print()
print('THE PROBE CAN BE TURNED OFF')
os.environ['LASERBRAIN_PROBE_SHARE'] = '0'
try:
    import importlib

    import lb_gate as _g
    importlib.reload(_g)
    check('PROBE_SHARE=0 puts everything in control',
          all(_g.probe_arm(f'x{i}') == 'control' for i in range(300)))
    with tempfile.TemporaryDirectory() as d:
        session(d, relaxed_id, 6, [0])
        rb, _ = run_gate(d, relaxed_id, env_extra={'LASERBRAIN_PROBE_SHARE': '0'})
        check('  and the formerly-relaxed session blocks again', rb)
finally:
    os.environ.pop('LASERBRAIN_PROBE_SHARE', None)
    import importlib as _il

    import lb_gate as _g2
    _il.reload(_g2)

print()
print('THE ARM IS RECORDED — and NOT in the file two writers fight over')
# THE BUG THIS REPLACED. The arm was stamped into the session JSON by lb_coverage.load().
# It never survived: laserbrain/runtime.py's Session owns the same path, holds its dict in
# memory across the hook's writes, and saves the whole thing back — so the last writer
# drops the other's keys. Checked 2026-08-03, a day after the probe shipped: not one
# session file carried an arm, including the live one. The gate was assigning arms and
# recording none, and a week of probe data would have been uninterpretable.
#
# probe-arms.jsonl is append-only with a single writer, which has neither failure.
with tempfile.TemporaryDirectory() as d:
    session(d, relaxed_id, 9, [0])
    run_gate(d, relaxed_id)
    log = pathlib.Path(d) / 'arms.jsonl'
    check('the gate writes arms.jsonl', log.exists())
    if log.exists():
        rows = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
        check('  one row for the session', len(rows) == 1, str(len(rows)))
        check('  naming the arm the gate used', rows[0]['arm'] == probe_arm(relaxed_id),
              f"{rows[0]['arm']} vs {probe_arm(relaxed_id)}")
        check('  with the share it was assigned under', rows[0]['share'] == _g.probe_share()
              if '_g' in dir() else rows[0]['share'] == 15, str(rows[0].get('share')))
        check('  and the interval that arm actually ran', rows[0]['block_after'] == 12,
              str(rows[0].get('block_after')))
    run_gate(d, relaxed_id)
    rows2 = [l for l in log.read_text().splitlines() if l.strip()]
    check('  a second gated call does not append again', len(rows2) == 1, str(len(rows2)))

with tempfile.TemporaryDirectory() as d:
    session(d, control_id, 9, [0])
    run_gate(d, control_id)
    rows = [json.loads(l) for l in (pathlib.Path(d) / 'arms.jsonl').read_text().splitlines() if l.strip()]
    check('a control session records block_after 4', rows[0]['block_after'] == 4,
          str(rows[0].get('block_after')))

# And the session file must NOT carry it — writing there is what failed.
with tempfile.TemporaryDirectory() as d:
    p_ = pathlib.Path(d) / f'{relaxed_id}.json'
    session(d, relaxed_id, 3, [0])
    got = cov_load(p_)
    check('load() no longer stamps the contended file', 'probe_arm' not in got,
          str(got.get('probe_arm')))

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    sys.exit(1)
print('  PASS — the arms differ, the relaxed one still closes, and neither can deadlock.')
