"""LASERBRAIN_GATE_MODE: hard | watch | signal. (Unset = nudge since 2026-10-16: test_nudge_default.py.)

WHY THIS SUITE EXISTS. INCIDENTS-2026-10 found 1,559 gate blocks, every one from the
step-count rule, and 30 of 30 sampled were false alarms. EVAL-PLAN §3 needs two more arms
to measure that against: watch-only (B) and signal-gated (D). Both are opt-in. The gate
is live in Diego's sessions, so the property under the most pressure is the first one:

  1. HARD IS UNCHANGED (it was the unset default until 2026-10-16). The step count still refuses, the drift gate is still shadow, the
     claim gate still refuses, and no new file appears in the state dir.
  2. watch refuses nothing — coverage, drift (even with LASERBRAIN_GATE_ON_DRIFT=deny) or
     claim — and records each would-be refusal, with arguments hashed and redacted.
  3. signal never refuses on the step count, refuses on ungrammatical / ask-mismatch,
     and still never refuses a read or check_state. goal-drift refused here until
     2026-11-15; it is a note now (drifting False) and refuses nothing in any mode.

Run:  python3 test_gate_modes.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
ok = True
# Built at runtime so this file holds no credential-shaped literal for lb_secrets to flag.
FAKE_KEY = 'sk-' + 'ant-' + 'x' * 32


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


def chk(step, reason='advancing', goal='fix the auth test', rs=1):
    return {'step': step, 'run': 'R', 'run_step': rs, 'goal': goal, 'reason': reason,
            'phi': 0.2, 'goal_score': 0.5, 'drifting': reason != 'advancing'}


def session(kind):
    if kind == 'late':          # 5 steps since the last check: acting band of the coverage gate
        return {'agent': 'claude', 'steps': 14, 'checks': [chk(2), chk(5, rs=2), chk(9, rs=3)]}
    if kind == 'hardband':      # far past the threshold: even reads are refused today
        return {'agent': 'claude', 'steps': 40, 'checks': [chk(2), chk(5, rs=2), chk(9, rs=3),
                                                           chk(14, rs=4), chk(20, rs=5), chk(25, rs=6)]}
    # a fresh check whose verdict is `kind`; coverage fine, so only a verdict can gate
    return {'agent': 'claude', 'steps': 10,
            'checks': [chk(2), chk(5, rs=2), chk(10, kind, 'refactor the session store', rs=3)]}


def run(kind, tool, mode=None, drift=None, claim=False, args_opt_in=False,
        tool_input=None, sid='S1'):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / f'{sid}.json').write_text(json.dumps(session(kind)))
    link = d / 'link.jsonl'
    link.write_text(json.dumps({'kind': 'claim', 'from': 'grok',
                                'payload': {'paths': ['/tmp/claimed']}}) + '\n' if claim else '')
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env['LASERBRAIN_STUDY'] = '1'  # the pre-2026-11-19 text; the quiet default is test_quiet_default.py
    env.update(LASERBRAIN_STATE_DIR=str(d), LASERBRAIN_AGENT='claude',
               LASERBRAIN_LINK_LOG=str(link), PYTHONPATH=str(ROOT),
               LASERBRAIN_PROBE_SHARE='0')        # control arm: a fixed threshold of 4
    if mode is not None:
        env['LASERBRAIN_GATE_MODE'] = mode
    if drift is not None:
        env['LASERBRAIN_GATE_ON_DRIFT'] = drift
    if args_opt_in:
        env['LASERBRAIN_REFUSAL_ARGS'] = '1'
    ti = tool_input or {'file_path': '/tmp/claimed/x.py', 'command': 'make build'}
    ev = json.dumps({'session_id': sid, 'tool_name': tool, 'tool_input': ti})
    p = subprocess.run([sys.executable, '-m', 'laserbrain.hooks.lb_gate'],
                       input=ev, capture_output=True, text=True, env=env, cwd=str(ROOT))

    def rows(name):
        f = d / name
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []
    p.refusals, p.args_rows = rows('refusals.jsonl'), rows('refusal-args.jsonl')
    p.files = sorted(f.name for f in d.iterdir())
    return p


def blocked(p):
    return p.returncode == 2 and 'permissionDecision' in p.stdout


_off = pathlib.Path(os.path.expanduser('~/.config/laserbrain/gate-off'))
show('gate-off is absent, so these results mean something', not _off.exists(), str(_off))

# Until 2026-10-16 this section ran with the variable unset, because unset WAS hard. The
# default is now nudge (test_nudge_default.py), so the same assertions pin hard explicitly.
print('\n  1. LASERBRAIN_GATE_MODE=hard is the gate as it was')
p = run('late', 'Bash', mode='hard')
show('step count refuses Bash', blocked(p), f'exit={p.returncode}')
show('...recorded as stage acting, schema unchanged',
     [r.get('stage') for r in p.refusals] == ['acting']
     and set(p.refusals[0]) == {'at', 'session', 'stage', 'tool', 'arm', 'since',
                                'coverage', 'floor', 'block_after'}, str(p.refusals))
show('...and no new file is written', 'refusal-args.jsonl' not in p.files, str(p.files))
p = run('late', 'Read', mode='hard')
show('a read in the acting band passes with a warning',
     p.returncode == 0 and 'Reads still pass' in p.stderr, f'exit={p.returncode}')
p = run('hardband', 'Read', mode='hard')
show('far past the threshold, even a read is refused', blocked(p), f'exit={p.returncode}')
p = run('ungrammatical', 'Write', mode='hard')
show('drift gate is still shadow',
     p.returncode == 0 and 'shadow' in p.stderr.lower(), f'exit={p.returncode}')
p = run('ask-mismatch', 'Write', mode='hard')
show('ask-mismatch is not enforced', p.returncode == 0 and not p.stderr,
     f'exit={p.returncode} {p.stderr[:80]!r}')
p = run('advancing', 'Write', claim=True, mode='hard')
show('claim gate refuses an edit in another agent\'s scope', blocked(p), f'exit={p.returncode}')
for v in ('HARD ', ' hard'):
    a, b = run('late', 'Bash', mode=v), run('late', 'Bash', mode='hard')
    show(f'LASERBRAIN_GATE_MODE={v!r} behaves exactly as hard',
         (a.returncode, a.stdout, a.stderr, a.files) == (b.returncode, b.stdout, b.stderr, b.files))
a, b = run('late', 'Bash', mode='bogus'), run('late', 'Bash', mode='hard')
show("LASERBRAIN_GATE_MODE='bogus' refuses as hard does (a typo never disarms the gate)",
     (a.returncode, a.stdout) == (b.returncode, b.stdout) and a.stderr.endswith(b.stderr)
     and 'bogus' in a.stderr.split('\n')[0], a.stderr[:160])
p = run('late', 'Bash', mode='hard', args_opt_in=True)
show('LASERBRAIN_REFUSAL_ARGS=1 adds the argument log and still refuses',
     blocked(p) and len(p.args_rows) == 1 and p.args_rows[0]['blocked'] is True, str(p.args_rows))

print('\n  2. watch refuses nothing and records everything')
p = run('late', 'Bash', mode='watch')
show('step count does not refuse Bash', p.returncode == 0 and not p.stdout, f'exit={p.returncode}')
show('...says so on stderr', '(watch)' in p.stderr and 'would have refused' in p.stderr, p.stderr[:120])
show('...refusals.jsonl gets a watch- stage with the same schema',
     [r.get('stage') for r in p.refusals] == ['watch-acting'], str(p.refusals))
show('...refusal-args.jsonl gets hash, preview, blocked=false',
     len(p.args_rows) == 1 and len(p.args_rows[0]['args_sha256']) == 64
     and p.args_rows[0]['blocked'] is False and p.args_rows[0]['kind'] == 'coverage'
     and 'make build' in (p.args_rows[0]['args_redacted'] or ''), str(p.args_rows))
p = run('hardband', 'Read', mode='watch')
show('far past the threshold, a read still runs', p.returncode == 0, f'exit={p.returncode}')
p = run('ungrammatical', 'Write', mode='watch', drift='deny')
show('drift deny is downgraded: Write runs', p.returncode == 0 and not p.stdout, f'exit={p.returncode}')
show('...and is logged as a drift would-block',
     any(r['kind'] == 'drift' and r['blocked'] is False for r in p.args_rows), str(p.args_rows))
p = run('advancing', 'Write', mode='watch', claim=True)
show('claim gate does not refuse', p.returncode == 0 and not p.stdout, f'exit={p.returncode}')
show('...and is logged', any(r['kind'] == 'claim' for r in p.args_rows), str(p.args_rows))
p = run('late', 'Bash', mode='watch',
        tool_input={'command': f'curl -H "x-api-key: {FAKE_KEY}" https://example.invalid'})
row = (p.args_rows or [{}])[0]
show('a key in the arguments never reaches the log',
     FAKE_KEY not in json.dumps(p.args_rows) and row.get('args_sha256'), str(p.args_rows))
p = run('late', 'Bash', mode='watch', tool_input={'command': 'echo $PASSWORD | login'})
show('a command naming a credential keeps only the placeholder',
     (p.args_rows or [{}])[0].get('args_redacted') == '[input redacted: references a credential]',
     str(p.args_rows))

print('\n  3. signal refuses on verdicts, never on the step count')
p = run('late', 'Bash', mode='signal')
show('step count does not refuse Bash', p.returncode == 0 and not p.stdout, f'exit={p.returncode}')
show('...and is silent about it', not p.stderr, p.stderr[:120])
show('...but the would-block is recorded for the replay',
     [r.get('stage') for r in p.refusals] == ['signal-acting']
     and p.args_rows and p.args_rows[0]['blocked'] is False, str(p.refusals))
p = run('hardband', 'Bash', mode='signal')
show('far past the threshold, Bash still runs', p.returncode == 0, f'exit={p.returncode}')
p = run('goal-drift', 'Write', mode='signal')
show('goal-drift does not refuse a Write (a note since 2026-11-15)',
     p.returncode == 0 and not p.stdout, f'exit={p.returncode}')
show('...and logs no drift would-block for it',
     not any(r.get('kind') == 'drift' for r in p.args_rows), str(p.args_rows))
for reason in ('ungrammatical', 'ask-mismatch'):
    p = run(reason, 'Write', mode='signal')
    show(f'{reason} refuses a Write (no LASERBRAIN_GATE_ON_DRIFT needed)', blocked(p),
         f'exit={p.returncode}')
show('...names signal mode as the reason', 'LASERBRAIN_GATE_MODE=signal' in p.stderr)
show('...and logs blocked=true',
     any(r['kind'] == 'drift' and r['blocked'] is True for r in p.args_rows), str(p.args_rows))
for tool in ('Read', 'Grep', 'mcp__laserbrain__check_state', 'reset_task'):
    p = run('ungrammatical', tool, mode='signal')
    show(f'{tool} passes after ungrammatical', p.returncode == 0, f'exit={p.returncode}')
for reason in ('advancing', 'grounded', 'stalled', 'oscillating'):
    p = run(reason, 'Write', mode='signal')
    show(f'{reason} does not refuse', p.returncode == 0, f'exit={p.returncode}')
p = run('advancing', 'Write', mode='signal', claim=True)
show('claim gate still refuses (a collision guard, not a cadence rule)', blocked(p),
     f'exit={p.returncode}')

print('\n  4. lb_coverage Stop block (camelCase hosts) follows the mode')


def stop(mode):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / 'C1.json').write_text(json.dumps({'steps': 30, 'checks': [{'step': 2, 'reason': 'advancing'}]}))
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env['LASERBRAIN_STUDY'] = '1'  # the pre-2026-11-19 text; the quiet default is test_quiet_default.py
    env.update(LASERBRAIN_STATE_DIR=str(d), PYTHONPATH=str(ROOT))
    if mode:
        env['LASERBRAIN_GATE_MODE'] = mode
    ev = json.dumps({'sessionId': 'C1', 'hook_event_name': 'Stop', 'reason': 'end_turn'})
    p = subprocess.run([sys.executable, str(ROOT / 'laserbrain/hooks/lb_coverage.py')],
                       input=ev, capture_output=True, text=True, env=env, cwd=str(ROOT))
    p.args_file = (d / 'refusal-args.jsonl').exists()
    return p


a = stop('hard')
show('hard: a lapsed camelCase turn end still emits decision=block',
     '"decision": "block"' in a.stdout, a.stdout[:120])
for m in ('watch', 'signal'):
    b = stop(m)
    show(f'{m}: no block is emitted, and the would-block is logged',
         '"block"' not in b.stdout and b.args_file, b.stdout[:120])

print('\n  5. hard keeps the old hook\'s side effects that 2026-10-16 fixed only in nudge')


def cov_env(d, mode):
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env['LASERBRAIN_STUDY'] = '1'  # the pre-2026-11-19 text; the quiet default is test_quiet_default.py
    env.update(LASERBRAIN_STATE_DIR=str(d / 'state'), LASERBRAIN_HOME=str(d / 'home'),
               HOME=str(d / 'home'), PYTHONPATH=str(ROOT), LASERBRAIN_PROBE_SHARE='0')
    if mode:
        env['LASERBRAIN_GATE_MODE'] = mode
    return env


def cov(d, ev, mode):
    return subprocess.run([sys.executable, str(ROOT / 'laserbrain/hooks/lb_coverage.py')],
                          input=json.dumps(ev), capture_output=True, text=True,
                          env=cov_env(d, mode), cwd=str(ROOT))


# camelCase PostToolUse chain past the 8-step reminder. The old hook read an undefined
# `is_grok` there, fell through to its embedded copy and counted the step twice. A checker
# found the first fix ran in hard too (17 differences); hard must keep the old count.
counts, stops = {}, {}
for mode in ('hard', None):
    d = pathlib.Path(tempfile.mkdtemp())
    for i in range(14):
        cov(d, {'sessionId': 'C9', 'toolName': 'Read', 'toolInput': {'file_path': '/x'},
                'hook_event_name': 'PostToolUse', 'toolResponse': {'ok': True}}, mode)
    counts[mode] = json.loads((d / 'state' / 'C9.json').read_text()).get('steps')
    stops[mode] = cov(d, {'sessionId': 'C9', 'hook_event_name': 'Stop', 'reason': 'end_turn'}, mode).stdout
show('hard: 14 camelCase calls leave 15 steps, as the pre-2026-10-16 hook did', counts['hard'] == 15,
     str(counts))
show('...and its Stop block quotes 15 steps', '15 steps since your last check_state' in stops['hard'],
     stops['hard'][:100])
show('nudge (unset): the same 14 calls count 14', counts[None] == 14, str(counts))

# A <task-notification> enqueue wrote the re-ground flag before 2026-10-16. Hard keeps that.
flags = {}
for mode in ('hard', None):
    d = pathlib.Path(tempfile.mkdtemp())
    t = d / 't.jsonl'
    t.write_text('{"type":"user","message":{"content":"hi"}}\n')
    ev = {'session_id': 'T9', 'tool_name': 'Read', 'tool_input': {}, 'tool_response': {},
          'hook_event_name': 'PostToolUse', 'transcript_path': str(t)}
    cov(d, ev, mode)
    with t.open('a') as fh:
        fh.write(json.dumps({'type': 'queue-operation', 'operation': 'enqueue',
                             'content': '<task-notification>done</task-notification>'}) + '\n')
    cov(d, ev, mode)
    flags[mode] = bool(list((d / 'home').rglob('user-turn')))
show('hard: a task-notification enqueue still writes the user-turn flag, as before', flags['hard'], str(flags))
show('nudge (unset): it does not (a notification is not the user)', not flags[None], str(flags))

print('\n  ' + ('PASS — hard unchanged; watch and signal behave as specified.' if ok
                else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
