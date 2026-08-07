#!/usr/bin/env python3
"""The join must actually join — proved on synthetic data, and against the live server.

    python3 test_join.py

WHY THIS FILE IS SHAPED LIKE THIS

sensitivity.py currently prints "NO JOINABLE CATCHES", which is the correct reading on the
day the fields land and is also exactly what a completely broken join would print. Those
two states are indistinguishable from the output alone, and a silent no-op that looks like
a clean pass is the failure mode this project has been bitten by most. So the join is
proved on data constructed to have a known answer, and separately proved end-to-end by
starting the real server and reading what check_state actually returns — because the whole
chain rests on two fields crossing a process boundary, and nothing else checks that they do.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sensitivity as S                                            # noqa: E402

# ONE STATE ROOT — a private tree, so this suite cannot write into the live corpus.
#
# It could, and it did. On 2026-08-05 the live drift log held 2,644 rows of which 1,058 —
# 40% — were written by suites spawning the server against the real ~/.config/laserbrain.
# Synthetic runs are pathological ON PURPOSE (flat distance, repeated goals, abandon bait),
# so they do not dilute the corpus evenly: `stalled` is 39.7% of the test rows against 3.2%
# of the real ones, which makes the whole-log rate 5.6x the truth. Every threshold ever read
# off this log was read off that mixture.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _testhome                                                   # noqa: E402
_testhome.isolate()


fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def sess(checks, catches, segments=None):
    return {'id': 'test', 'checks': checks, 'catches': catches, 'segments': segments or []}


def chk(step, run, run_step, drifting, reason='advancing', phi=0.1):
    return {'step': step, 'run': run, 'run_step': run_step, 'drifting': drifting,
            'reason': reason, 'phi': phi, 'goal': 'g', 'progress': 'advancing', 'distance': 5}


def cat(step, run, run_step, since, what='non-zero exit: pytest', clean=True):
    """A catch as the fixed recorder writes one.

    `clean` defaults True because every case below is about the JOIN — which reading a
    catch belongs to — and a catch without the stamp is dropped before the join is ever
    attempted. Added 2026-08-02 with the gate-block exclusion: collect() now discards
    unstamped catches as belonging to the era when a coverage-gate block still counted as
    ground truth. Leaving the helper unstamped silently zeroed every count in this file.
    """
    c = {'step': step, 'by': 'build', 'what': what,
         'run': run, 'run_step': run_step, 'since': since}
    if clean:
        c['clean'] = True
    return c


print('a catch under a firing reading is a HIT; under a quiet one, a MISS')

s = sess(
    checks=[chk(1, 'r1', 1, True, 'goal-drift', 0.6), chk(5, 'r1', 2, False)],
    catches=[cat(2, 'r1', 1, since=1), cat(6, 'r1', 2, since=1)],
)
d = S.collect([s], window=4, exclude_intentional=True)
check('one hit', len(d['hits']) == 1, f"{len(d['hits'])}")
check('one miss', len(d['misses']) == 1, f"{len(d['misses'])}")
check('  the hit names the reading that fired',
      d['hits'][0]['reason'] == 'goal-drift', str(d['hits'][0].get('reason')))
check('  and nothing is left unjoinable', d['unjoinable'] == 0, str(d['unjoinable']))

print()
print('attribution decays — a catch past the window is not scored either way')

# THE ONE THAT MATTERS. Coverage runs near 24%, so most catches land in a stretch the
# instrument never saw. Counting those as misses would blame the detector for not firing
# on steps it was never shown, and would make the miss rate a function of coverage rather
# than of detection.
s2 = sess(checks=[chk(1, 'r2', 1, False)],
          catches=[cat(20, 'r2', 1, since=19)])
d2 = S.collect([s2], window=4, exclude_intentional=True)
check('a far catch is neither hit nor miss', not d2['hits'] and not d2['misses'],
      f"hits {len(d2['hits'])} misses {len(d2['misses'])}")
check('  it is counted as out-of-window, not discarded silently', d2['far'] == 1, str(d2['far']))
d2w = S.collect([s2], window=20, exclude_intentional=True)
check('  and widening the window does score it', len(d2w['misses']) == 1,
      'the window is the knob, and it moves the answer — which is why it prints')

print()
print('a deliberately-failing command is not an error the instrument should have caught')

s3 = sess(checks=[chk(1, 'r3', 1, False)],
          catches=[cat(2, 'r3', 1, 1, what='non-zero exit: ./mutate.sh --deep')])
d3 = S.collect([s3], window=4, exclude_intentional=True)
check('the mutation gate is excluded', not d3['misses'] and d3['dropped'] == 1,
      f"misses {len(d3['misses'])} dropped {d3['dropped']}")
d3k = S.collect([s3], window=4, exclude_intentional=False)
check('  --keep-intentional counts it', len(d3k['misses']) == 1, str(len(d3k['misses'])))

print()
print('a catch that cannot be trusted is set aside, never scored as a miss')

# Two distinct reasons a catch is unusable, and they are counted separately because they
# retire on different days: the join fields arrived 2026-08-01, the gate exclusion
# 2026-08-02. Scoring either as a miss would invent a 0% hit rate out of rows that simply
# lack a field — the fabrication sensitivity.py exists to refuse.
s4 = sess(checks=[chk(1, 'r4', 1, False)],
          catches=[cat(2, None, None, None, what='non-zero exit: old')])
d4 = S.collect([s4], window=4, exclude_intentional=True)
check('a stamped catch with no run/run_step is unjoinable',
      d4['unjoinable'] == 1 and not d4['misses'],
      f"unjoinable {d4['unjoinable']} misses {len(d4['misses'])}")

# The gate-block era. An unstamped catch is dropped before the join is attempted, because
# the coverage gate fires exactly when the instrument is quiet — so these can only ever
# land on quiet readings and score as misses, which is how 0 hits / 8 misses happened.
s4b = sess(checks=[chk(1, 'r4b', 1, False)],
           catches=[cat(2, 'r4b', 1, since=1, clean=False)])
d4b = S.collect([s4b], window=4, exclude_intentional=True)
check('  an unstamped catch is excluded, not counted',
      d4b['precontam'] == 1 and not d4b['misses'] and not d4b['hits'],
      f"precontam {d4b['precontam']} misses {len(d4b['misses'])}")
check('  and it does not leak into unjoinable either', d4b['unjoinable'] == 0,
      str(d4b['unjoinable']))

print()
print('segments are read — a reset must not hide a task')

s5 = sess(checks=[], catches=[],
          segments=[{'checks': [chk(1, 'r5', 1, True, 'stalled')],
                     'catches': [cat(2, 'r5', 1, since=1)]}])
d5 = S.collect([s5], window=4, exclude_intentional=True)
check('an archived segment still joins', len(d5['hits']) == 1, str(len(d5['hits'])))

print()
print("d' is withheld on a sample that cannot support it")

dp, why = S.dprime(1, 2, 1, 2)
check('two trials get no number', dp is None, str(dp))
check('  and the refusal says why', 'n too small' in (why or ''), str(why))
dp2, why2 = S.dprime(30, 40, 10, 60)
check('a real sample does get one', dp2 is not None and dp2 > 0, f'{dp2}')
# 0/N and N/N must not send z to infinity.
dp3, _ = S.dprime(40, 40, 0, 60)
check('  a perfect rate is corrected, not infinite',
      dp3 is not None and dp3 < 10, f'{dp3}')

print()
print('END TO END — the live server must actually return run and step')

# The synthetic tests above would all pass if check_state returned neither field: they feed
# the join by hand. This is the only check that the two numbers cross the process boundary,
# and it is the single point the whole chain hangs on.
SERVER = HERE / 'mcp-server.mjs'


def rpc(proc, obj):
    proc.stdin.write(json.dumps(obj) + '\n')
    proc.stdin.flush()


if not SERVER.exists():
    print(f'  SKIPPED: no server at {SERVER}')
else:
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ,
                   LASERBRAIN_DRIFT_LOG=str(pathlib.Path(td) / 'drift.jsonl'),
                   LASERBRAIN_AGENT='test-join')
        p = subprocess.Popen([os.environ.get('NODE', 'node'), str(SERVER)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, env=env)
        try:
            rpc(p, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                    'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                               'clientInfo': {'name': 'test-join', 'version': '1'}}})
            p.stdout.readline()
            rpc(p, {'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            seen = []
            for i, dist in enumerate((7, 5), start=2):
                rpc(p, {'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',
                        'params': {'name': 'check_state',
                                   'arguments': {'goal': 'prove the join crosses the boundary',
                                                 'progress': 'advancing', 'distance': dist}}})
                line = p.stdout.readline()
                body = json.loads(line)
                text = body['result']['content'][0]['text']
                seen.append(json.loads(text))
        finally:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()

    a, b = seen
    check('check_state returns a run', bool(a.get('run')), repr(a.get('run'))[:40])
    check('check_state returns a step', a.get('step') == 1, repr(a.get('step')))
    check('  the step increments', b.get('step') == 2, repr(b.get('step')))
    # `a == b` alone passes when BOTH are None, which is precisely the broken state this
    # section exists to catch — verified by removing the fields from the server, where this
    # line stayed green while the three above went red. Identity is only meaningful once
    # there is something to be identical to.
    check('  and the run is stable across the task',
          bool(a.get('run')) and a.get('run') == b.get('run'),
          'a run groups a task; a run that changed per step would join nothing')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(f.strip() for f in fails))
    sys.exit(1)
print('  PASS — catches join to readings, the window cuts, and the server ships both fields.')
