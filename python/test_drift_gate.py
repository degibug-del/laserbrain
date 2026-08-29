"""The gate refuses on a VERDICT, not only on a cadence — and by default refuses nothing.

WHY THIS SUITE EXISTS. Until 2026-08-27 lb_gate.py had two ways to say no: another agent
owns that path, and you have not checked recently enough. Neither read what the check
actually SAID. An agent could be told `goal-drift` in as many words and walk straight into
its next write, because it had satisfied the gate by checking at all. Observed live in
session 18d090f0: a check returned {"drifting": true, "reason": "goal-drift", "phi": 0.54}
and the following tool call ran unopposed.

WHAT IS BEING PINNED HERE. Three properties, and the third is the one that will be under
pressure later:

  1. In `deny` mode a hard verdict refuses a side-effecting call.
  2. Reads, and check_state itself, are NEVER refused — an agent that has drifted works out
     where it is by looking, and a gate that can refuse the call which clears it is a
     deadlock rather than a guard.
  3. The DEFAULT IS SHADOW. Published precision on goal-drift is 14.6%. A gate that blocks
     on a signal wrong six times in seven is worse than no gate, so the default computes
     the decision, logs it and blocks nothing. If a future edit makes enforcement the
     default, this suite fails — which is the point of asserting a default at all.

Soft verdicts (stalled, oscillating) must never gate: drift.ts treats them as a watch until
sustained, and a gate that cannot tell a watch from a stop discards that distinction.

Run:  python3 test_drift_gate.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


def session(reason):
    """A session whose LAST reading is `reason`, with coverage high enough that the
       coverage gate stays silent — otherwise a pass here could be the wrong gate firing."""
    return {'id': 'S', 'steps': 10, 'agent': 'claude', 'checks': [
        {'step': 2, 'run': 'R1', 'run_step': 1, 'goal': 'fix the failing auth test',
         'reason': 'advancing', 'phi': 0.1, 'goal_score': 1.0, 'drifting': False},
        {'step': 4, 'run': 'R1', 'run_step': 2, 'goal': 'fix the auth test',
         'reason': 'advancing', 'phi': 0.2, 'goal_score': 0.8, 'drifting': False},
        {'step': 6, 'run': 'R1', 'run_step': 3, 'goal': 'the auth session path',
         'reason': 'advancing', 'phi': 0.3, 'goal_score': 0.6, 'drifting': False},
        {'step': 10, 'run': 'R1', 'run_step': 4, 'goal': 'refactor the session store',
         'reason': reason, 'phi': 0.54, 'goal_score': 0.03,
         'drifting': reason not in ('advancing', 'grounded')},
    ]}


def run(reason, tool, mode):
    d = tempfile.mkdtemp()
    pathlib.Path(d, 'S.json').write_text(json.dumps(session(reason)))
    env = dict(os.environ)
    env['LASERBRAIN_STATE_DIR'] = d
    env['LASERBRAIN_AGENT'] = 'claude'
    env['PYTHONPATH'] = str(ROOT)
    env.pop('LASERBRAIN_GATE_ON_DRIFT', None)
    if mode is not None:
        env['LASERBRAIN_GATE_ON_DRIFT'] = mode
    ev = json.dumps({'session_id': 'S', 'tool_name': tool, 'tool_input': {'file_path': '/tmp/x'}})
    return subprocess.run([sys.executable, '-m', 'laserbrain.hooks.lb_gate'],
                          input=ev, capture_output=True, text=True, env=env, cwd=str(ROOT))


# The escape door disables the whole hook, so with it in place every assertion below would
# pass for the wrong reason. Checked first, and loudly.
_off = pathlib.Path(os.path.expanduser('~/.config/laserbrain/gate-off'))
show('gate-off is absent, so these results mean something', not _off.exists(), str(_off))

print('\n  enforcement, when it is asked for')
for tool in ('Write', 'Edit', 'Bash'):
    p = run('goal-drift', tool, 'deny')
    show(f'deny mode refuses {tool} after goal-drift',
         p.returncode == 2 and 'permissionDecision' in p.stdout, f'exit={p.returncode}')
p = run('ungrammatical', 'Write', 'deny')
show('deny mode refuses after ungrammatical', p.returncode == 2, f'exit={p.returncode}')

print('\n  what must never be refused')
for tool in ('Read', 'Grep', 'Glob', 'check_state', 'reset_task'):
    p = run('goal-drift', tool, 'deny')
    show(f'{tool} passes even in deny mode', p.returncode == 0, f'exit={p.returncode}')

print('\n  what is not a drift')
for reason in ('advancing', 'grounded', 'reground', 'stalled', 'oscillating'):
    p = run(reason, 'Write', 'deny')
    show(f'{reason} does not gate a write', p.returncode == 0, f'exit={p.returncode}')

print('\n  the default, which is the load-bearing one')
p = run('goal-drift', 'Write', None)
show('unset LASERBRAIN_GATE_ON_DRIFT blocks nothing',
     p.returncode == 0 and 'permissionDecision' not in p.stdout, f'exit={p.returncode}')
show('...and says what it would have done', 'shadow' in p.stderr.lower(), repr(p.stderr[:120]))
show('...and names the precision that is the reason for waiting', '14.6' in p.stderr)
p = run('goal-drift', 'Write', 'off')
show('off evaluates nothing at all',
     p.returncode == 0 and 'drift gate' not in p.stderr, f'exit={p.returncode}')

print('\n  the refusal has to be actionable')
p = run('goal-drift', 'Write', 'deny')
show('names the goal the run started with', 'fix the failing auth test' in p.stderr)
show('names the goal that was spelled', 'refactor the session store' in p.stderr)
show('says the call did not run', 'DID NOT RUN' in p.stderr)
show('offers a way out', 'reset_task' in p.stderr and 'parent_goal' in p.stderr)

print('\n  this suite could have failed')
show('a clean verdict and a drift verdict do not produce the same exit code',
     run('advancing', 'Write', 'deny').returncode != run('goal-drift', 'Write', 'deny').returncode)

print('\n  ' + ('PASS — the gate reads the verdict, and still blocks nothing by default.' if ok
                else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
