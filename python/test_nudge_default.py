"""The default gate (LASERBRAIN_GATE_MODE unset = nudge), added 2026-10-16.

WHY. The day-one experiment counted 4,775 gate blocks, all from the step count, with 0 kept
by signal mode and 30 of 30 sampled false alarms. So the step count stops refusing by
default, and the rest of what was learned that day rides on the same mode:

  A  the step count never refuses; would-be refusals are logged as nudge-*; the reminder is
     non-blocking additionalContext once per BLOCK_AFTER steps; claims still refuse; drift
     follows LASERBRAIN_GATE_ON_DRIFT; an unknown mode is hard, with one warning
  B  Agent/Task/Workflow spawns get a watch-only ask-match verdict (a note on Workflow)
  C  a <task-notification> enqueue is not a user turn
  D  a read-only shell command counts as a read
  E  steps are counted per agent_id, so a subagent's calls do not count against the parent

Run:  python3 test_nudge_default.py
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


def chk(step, reason='advancing', goal='fix the auth test', rs=1, distance=5):
    return {'step': step, 'run': 'R', 'run_step': rs, 'goal': goal, 'reason': reason,
            'phi': 0.2, 'goal_score': 0.5, 'drifting': reason != 'advancing', 'distance': distance}


def session(kind):
    if kind == 'late':          # since 5: past BLOCK_AFTER=4, not due for a reminder
        return {'agent': 'claude', 'steps': 14, 'checks': [chk(2), chk(5, rs=2), chk(9, rs=3)]}
    if kind == 'late4':         # since 4: exactly at the threshold, reminder due
        return {'agent': 'claude', 'steps': 13, 'checks': [chk(2), chk(5, rs=2), chk(9, rs=3)]}
    if kind == 'hardband':
        return {'agent': 'claude', 'steps': 40, 'checks': [chk(2), chk(5, rs=2), chk(9, rs=3),
                                                           chk(14, rs=4), chk(20, rs=5), chk(25, rs=6)]}
    return {'agent': 'claude', 'steps': 10,
            'checks': [chk(2), chk(5, rs=2), chk(10, kind, 'refactor the session store', rs=3)]}


def env_for(d, mode=None, drift=None, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env['LASERBRAIN_STUDY'] = '1'  # the pre-2026-11-19 text; the quiet default is test_quiet_default.py
    env.update(LASERBRAIN_STATE_DIR=str(d), LASERBRAIN_HOME=str(d / 'home'),
               LASERBRAIN_AGENT='claude', LASERBRAIN_LINK_LOG=str(d / 'link.jsonl'),
               PYTHONPATH=str(ROOT), LASERBRAIN_PROBE_SHARE='0')
    if mode is not None:
        env['LASERBRAIN_GATE_MODE'] = mode
    if drift is not None:
        env['LASERBRAIN_GATE_ON_DRIFT'] = drift
    env.update(extra or {})
    return env


def rows(d, name):
    f = d / name
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


def gate(kind, tool, mode=None, drift=None, claim=False, tool_input=None, d=None, ev_extra=None,
         agents=None, sid='S1'):
    d = d or pathlib.Path(tempfile.mkdtemp())
    if not (d / f'{sid}.json').exists():
        (d / f'{sid}.json').write_text(json.dumps(session(kind)))
    (d / 'link.jsonl').write_text(json.dumps({'kind': 'claim', 'from': 'grok',
                                              'payload': {'paths': ['/tmp/claimed']}}) + '\n'
                                  if claim else '')
    if agents is not None:
        (d / f'{sid}.agents.json').write_text(json.dumps(agents))
    ti = tool_input or {'file_path': '/tmp/claimed/x.py', 'command': 'make build'}
    ev = {'session_id': sid, 'tool_name': tool, 'tool_input': ti, **(ev_extra or {})}
    p = subprocess.run([sys.executable, '-m', 'laserbrain.hooks.lb_gate'], input=json.dumps(ev),
                       capture_output=True, text=True, env=env_for(d, mode, drift), cwd=str(ROOT))
    p.d = d
    p.refusals, p.args_rows = rows(d, 'refusals.jsonl'), rows(d, 'refusal-args.jsonl')
    p.files = sorted(f.name for f in d.iterdir())
    try:
        p.ctx = json.loads(p.stdout)['hookSpecificOutput'].get('additionalContext') if p.stdout.strip() else None
    except Exception:
        p.ctx = None
    return p


def blocked(p):
    return p.returncode == 2 and 'permissionDecision' in p.stdout


def stages(p):
    return [r.get('stage') for r in p.refusals]


print('\n  A. the step count never refuses by default')
p = gate('late', 'Bash')
show('unset: Bash past the threshold runs', p.returncode == 0 and not blocked(p), f'exit={p.returncode}')
BASE = {'at', 'session', 'stage', 'tool', 'arm', 'since', 'coverage', 'floor', 'block_after'}
AGENT = {'would_hard', 'agent', 'agent_stage', 'agent_since', 'agent_steps', 'agent_coverage',
         'shell_read'}
show('...the would-be refusal is logged as nudge-acting: hard\'s schema plus agent fields',
     stages(p) == ['nudge-acting'] and set(p.refusals[0]) == BASE | AGENT
     and p.refusals[0]['would_hard'] is True and p.refusals[0]['since'] == 5, str(p.refusals))
show('...no argument log by default', 'refusal-args.jsonl' not in p.files, str(p.files))
show('...not due (since 5): no reminder printed', p.stdout == '' and p.stderr == '', p.stdout[:80])
p = gate('late4', 'Bash')
show('at the threshold the reminder is non-blocking additionalContext',
     p.returncode == 0 and p.ctx and 'check_state' in p.ctx and 'Not blocking' in p.ctx
     and 'permissionDecision' not in p.stdout, p.stdout[:160])
p = gate('hardband', 'Read')
show('far past twice the threshold a read still runs, logged nudge-hard',
     p.returncode == 0 and stages(p) == ['nudge-hard'], f'{p.returncode} {stages(p)}')
p = gate('hardband', 'Write')
show('...and so does a Write', p.returncode == 0 and not blocked(p), f'exit={p.returncode}')
p = gate('advancing', 'Write', claim=True)
show('claims still refuse', blocked(p), f'exit={p.returncode}')
# The hard drift verdict here is `ungrammatical`: goal-drift left HARD_VERDICTS on
# 2026-11-15 (a note, drifting False) and is pinned as refusing nothing just below.
p = gate('goal-drift', 'Write', drift='deny')
show('goal-drift refuses nothing, even under LASERBRAIN_GATE_ON_DRIFT=deny (a note since 2026-11-15)',
     p.returncode == 0 and not blocked(p) and 'drift-deny' not in stages(p), f'exit={p.returncode} {stages(p)}')
p = gate('ungrammatical', 'Write')
show('drift is shadow when LASERBRAIN_GATE_ON_DRIFT is unset (as in hard)',
     p.returncode == 0 and 'shadow' in p.stderr.lower(), p.stderr[:80])
p = gate('ungrammatical', 'Write', drift='deny')
show('drift refuses under LASERBRAIN_GATE_ON_DRIFT=deny (as in hard)', blocked(p), f'exit={p.returncode}')
show('...logged with the hard stage name drift-deny', 'drift-deny' in stages(p), str(stages(p)))
p = gate('ask-mismatch', 'Write')
show('an ask-mismatch verdict is not enforced', p.returncode == 0 and not blocked(p))
p = gate('late', 'Bash', mode='')
show("LASERBRAIN_GATE_MODE='' is the default", p.returncode == 0 and stages(p) == ['nudge-acting'])
d = pathlib.Path(tempfile.mkdtemp())
p1 = gate('late', 'Bash', mode='hrad', d=d)
p2 = gate('late', 'Bash', mode='hrad', d=d)
show('an unknown mode refuses as hard', blocked(p1) and blocked(p2))
show('...and warns once per state dir', 'hrad' in p1.stderr.split('\n')[0]
     and 'hrad' not in p2.stderr, p2.stderr[:100])
p = gate('late', 'Bash', mode='nudge')
show("LASERBRAIN_GATE_MODE=nudge equals unset", p.returncode == 0 and stages(p) == ['nudge-acting'])

# THE NUDGE LOG IS HARD'S DECISION (checker, 2026-10-17: with per-agent counts the first
# version logged 2 rows where hard refused 6). For every state below, the stage nudge logs
# must be the stage hard records for the same call: warn, acting, hard, or nothing.
GRID = {
    'quiet': {'agent': 'claude', 'steps': 6, 'checks': [chk(2), chk(5, rs=2)]},
    'late4': session('late4'), 'late': session('late'), 'hardband': session('hardband'),
    'thin': {'agent': 'claude', 'steps': 30, 'checks': [chk(28)]},
    'starved': {'agent': 'claude', 'steps': 40, 'checks': [chk(39)]},
    'eight': {'agent': 'claude', 'steps': 17, 'checks': [chk(2), chk(5, rs=2), chk(9, rs=3)]},
}
sys.path.insert(0, str(ROOT / 'laserbrain' / 'hooks'))
from lb_gate import probe_arm  # noqa: E402
ARM_SIDS = (next(f'c{i}' for i in range(5000) if probe_arm(f'c{i}') == 'control'),
            next(f'r{i}' for i in range(5000) if probe_arm(f'r{i}') == 'relaxed'))
mismatch = []
n_cells = 0
for gk, gs in GRID.items():
    for tool, ti in (('Read', {'file_path': '/tmp/x'}), ('Bash', {'command': 'ls'}),
                     ('Write', {'file_path': '/tmp/w.py', 'content': 'x'}),
                     ('Edit', {'file_path': '/tmp/w.py'})):
        for sid in ARM_SIDS:
            got = {}
            for mode in ('hard', None):
                dd = pathlib.Path(tempfile.mkdtemp())
                (dd / f'{sid}.json').write_text(json.dumps(gs))
                q = gate(None, tool, mode=mode, tool_input=ti, d=dd, sid=sid)
                got[mode] = [r['stage'].replace('nudge-', '') for r in q.refusals]
            n_cells += 1
            if got['hard'] != got[None]:
                mismatch.append((gk, tool, sid, got))
show(f'nudge logs exactly hard\'s stage in all {n_cells} grid cells (states x tools x arms)',
     mismatch == [], str(mismatch[:3]))

print('\n  D. read-only shell commands count as reads')
p = gate('late', 'Bash', tool_input={'command': 'ls -la && git status'})
show('`ls -la && git status`: hard\'s stage stays nudge-acting, the agent\'s own is warn (a read)',
     stages(p) == ['nudge-acting'] and p.refusals[0]['agent_stage'] == 'warn'
     and p.refusals[0]['shell_read'] is True, str(p.refusals))
p = gate('late', 'Bash', tool_input={'command': 'ls > out.txt'})
show('`ls > out.txt` is acting for the agent too',
     stages(p) == ['nudge-acting'] and p.refusals[0]['agent_stage'] == 'acting'
     and p.refusals[0]['shell_read'] is False, str(p.refusals))
p = gate('late', 'Bash', tool_input={'command': 'ls # x\nrm -f victim'})
show('a comment cannot hide a later line: acting', p.refusals and p.refusals[0]['agent_stage'] == 'acting',
     str(p.refusals))
p = gate('ungrammatical', 'Bash', drift='deny', tool_input={'command': 'grep -n x f.py | head'})
show('drift is unchanged: after ungrammatical with deny a shell read is refused, as in hard',
     blocked(p) and 'drift-deny' in stages(p), f'exit={p.returncode} {stages(p)}')
p = gate('ungrammatical', 'Bash', drift='deny', tool_input={'command': 'ls # x\nrm -f victim'})
show('...so `ls # x<newline>rm -f victim` is refused too (it ran under the first version)', blocked(p),
     f'exit={p.returncode}')
p = gate('ungrammatical', 'Bash', tool_input={'command': 'ls -la'})
show('...and in shadow a shell read is still logged and warned, as in hard',
     p.returncode == 0 and 'drift-shadow' in stages(p) and 'shadow' in p.stderr, str(stages(p)))
p = gate('ungrammatical', 'Bash', mode='hard', drift='deny', tool_input={'command': 'ls'})
show('hard mode is unchanged: `ls` after ungrammatical with deny is refused', blocked(p))

print('\n  E. steps are attributed to the agent that made them')
ag = {'main': {'steps': 10, 'checks': 3, 'check_step': 9}, 'kid': {'steps': 3, 'checks': 1, 'check_step': 2},
      'lazy': {'steps': 9, 'checks': 1, 'check_step': 2}}
p = gate('late', 'Bash', agents=ag)
r = p.refusals[0] if p.refusals else {}
show('main thread: hard\'s decision is still logged (session-wide since 5, would_hard)...',
     stages(p) == ['nudge-acting'] and r.get('would_hard') is True and r.get('since') == 5, str(p.refusals))
show('...beside its own numbers: since 1, coverage 30%, no stage of its own, no reminder',
     r.get('agent') == 'main' and r.get('agent_since') == 1 and r.get('agent_coverage') == 0.3
     and r.get('agent_stage') is None and p.ctx is None and p.returncode == 0, str(r))
p = gate('late', 'Bash', agents=ag, ev_extra={'agent_id': 'kid'})
show('subagent with since 1: agent_stage None, no reminder',
     p.refusals and p.refusals[0]['agent_stage'] is None and p.ctx is None, str(p.refusals))
p = gate('late', 'Bash', agents=ag, ev_extra={'agent_id': 'lazy'})
show('subagent with since 7 and coverage 11%: agent_stage acting, agent_since 7',
     [(x['agent_stage'], x['agent_since']) for x in p.refusals] == [('acting', 7)], str(p.refusals))
p = gate('late', 'Bash', agents=ag, ev_extra={'agent_id': 'fresh'})
show('a subagent with no calls yet has since 0', p.refusals and p.refusals[0]['agent_since'] == 0
     and p.refusals[0]['agent_stage'] is None, str(p.refusals))
p = gate('advancing', 'Bash', agents={'main': {'steps': 12, 'checks': 1, 'check_step': 4}})
show('the agent alone can be behind (session since 0): logged as nudge-agent, reminder due at 8',
     stages(p) == ['nudge-agent'] and p.refusals[0]['would_hard'] is False and p.ctx
     and '8 of your steps' in p.ctx, f'{stages(p)} {p.ctx}')
p = gate('late', 'Bash', mode='hard', agents=ag, ev_extra={'agent_id': 'kid'})
show('hard mode ignores attribution (session-wide since 5 refuses)', blocked(p))


def post(d, ev, mode=None):
    ev = {'hook_event_name': 'PostToolUse', 'session_id': 'S1', **ev}
    return subprocess.run([sys.executable, str(ROOT / 'laserbrain/hooks/lb_coverage.py')],
                          input=json.dumps(ev), capture_output=True, text=True,
                          env=env_for(d, mode), cwd=str(ROOT))


d = pathlib.Path(tempfile.mkdtemp())
for _ in range(3):
    post(d, {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'tool_response': {}})
for _ in range(5):
    post(d, {'tool_name': 'Read', 'tool_input': {}, 'tool_response': {}, 'agent_id': 'a1'})
post(d, {'tool_name': 'mcp__laserbrain__check_state', 'agent_id': 'a1',
         'tool_input': {'goal': 'g', 'progress': 'advancing', 'distance': 4},
         'tool_response': {'drifting': False, 'reason': 'advancing', 'phi': 0.1, 'run': 'r'}})
post(d, {'tool_name': 'Read', 'tool_input': {}, 'tool_response': {}, 'agent_id': 'a1'})
ag = json.loads((d / 'S1.agents.json').read_text())
show('PostToolUse counts per agent: main 3, a1 7 with its check at 6',
     ag['main']['steps'] == 3 and ag['a1']['steps'] == 7 and ag['a1']['check_step'] == 6, str(ag))
sess = json.loads((d / 'S1.json').read_text())
show('...while the session file still counts every call (8 + the check = 10 steps)',
     int(sess.get('steps', 0)) == 10, str(sess.get('steps')))
d2 = pathlib.Path(tempfile.mkdtemp())
post(d2, {'tool_name': 'Read', 'tool_input': {}, 'tool_response': {}, 'agent_id': 'a1'}, mode='hard')
show('hard mode writes no per-agent file', not (d2 / 'S1.agents.json').exists())


def hook_call(d, tool, ti, agent=None, resp=None):
    ev = {'session_id': 'S1', 'tool_name': tool, 'tool_input': ti}
    if agent:
        ev['agent_id'] = agent
    g = subprocess.run([sys.executable, '-m', 'laserbrain.hooks.lb_gate'],
                       input=json.dumps(dict(ev, hook_event_name='PreToolUse')),
                       capture_output=True, text=True, env=env_for(d), cwd=str(ROOT))
    po = post(d, dict(ev, tool_response=resp if resp is not None else {}))
    return g, po


# THE CHECKER'S SCENARIO (2026-10-17): the parent checks in after every 2 of its own calls
# while two subagents make 3 Reads each between them. Before the fix 11 of the parent's 12
# calls were logged as would-be refusals and it got 4 reminders quoting its subagents' calls.
d = pathlib.Path(tempfile.mkdtemp())
CK = {'goal': 'fix parser', 'progress': 'advancing', 'distance': 5}
CKR = {'content': [{'type': 'text', 'text': json.dumps({'drifting': False, 'reason': 'advancing',
                                                         'phi': 0.1, 'run': 'r1'})}]}
notes, parent_rows = [], []
for _ in range(6):
    hook_call(d, 'mcp__laserbrain__check_state', CK, resp=CKR)
    for _k in range(2):
        before = len(rows(d, 'refusals.jsonl'))
        g, po = hook_call(d, 'Edit', {'file_path': '/r/a.py', 'old_string': 'a', 'new_string': 'b'})
        parent_rows += rows(d, 'refusals.jsonl')[before:]
        notes += [x for x in (g.stdout, po.stdout) if 'steps since' in x]
        for sub in ('a1', 'a2'):
            for _j in range(3):
                hook_call(d, 'Read', {'file_path': '/r/b.py'}, agent=sub)
show('a parent that checks in regularly gets no reminder from its subagents\' calls', notes == [],
     str(notes)[:200])
show('...and none of its rows has a stage of its own (agent_stage None, agent main)',
     parent_rows and all(x['agent'] == 'main' and x['agent_stage'] is None for x in parent_rows),
     str(parent_rows[:2])[:200])
sub_notes = [x for x in rows(d, 'refusals.jsonl') if x['agent'] == 'a1' and x['agent_stage']]
show('...while the subagents that never check are behind on their own numbers', len(sub_notes) > 0)

# lb_coverage's PostToolUse reminder (runtime Session.nudge) counted the session total.
d = pathlib.Path(tempfile.mkdtemp())
post(d, {'tool_name': 'mcp__laserbrain__check_state', 'agent_id': 'a1', 'tool_input': CK,
         'tool_response': CKR})
outs = [post(d, {'tool_name': 'Read', 'tool_input': {}, 'tool_response': {}}).stdout for _ in range(7)]
a1 = post(d, {'tool_name': 'Read', 'tool_input': {}, 'tool_response': {}, 'agent_id': 'a1'}).stdout
show('a subagent one step past its check is not told "8 steps since" by lb_coverage',
     'steps since' not in a1, a1[:160])
m8 = post(d, {'tool_name': 'Read', 'tool_input': {}, 'tool_response': {}}).stdout
show('...the main thread at 8 of its own steps is, with its own numbers',
     '8 of your steps' in m8 and 'over your 8 steps' in m8, m8[:200])
sess = json.loads((d / 'S1.json').read_text())
show('...while the session file still counts all 10 calls', int(sess.get('steps', 0)) == 10)


def stop_snake(d, agent=None):
    ev = {'session_id': 'S1', 'hook_event_name': 'SubagentStop' if agent else 'Stop', 'reason': 'end_turn'}
    if agent:
        ev['agent_id'] = agent
    return subprocess.run([sys.executable, str(ROOT / 'laserbrain/hooks/lb_coverage.py')],
                          input=json.dumps(ev), capture_output=True, text=True, env=env_for(d),
                          cwd=str(ROOT)).stdout


post(d, {'tool_name': 'Read', 'tool_input': {}, 'tool_response': {}})       # main: 9 of its own
show('Stop: the main thread hears its own 9 steps', '9 of your steps' in stop_snake(d))
show('SubagentStop: a subagent 1 step past its check hears nothing', 'steps since' not in stop_snake(d, 'a1'))

print('\n  B. spawn-time ask-match: watch-only')
tr = pathlib.Path(tempfile.mkdtemp()) / 't.jsonl'
tr.write_text('\n'.join(json.dumps(r) for r in [
    {'type': 'user', 'message': {'role': 'user', 'content': 'rebuild the parser test fixtures'}},
    {'type': 'user', 'message': {'role': 'user', 'content':
        'make the dragon sprite wings bigger and recolor the scales green'}},
]) + '\n')
OFF = {'prompt': 'Rebuild the parser test fixtures and rerun the parser suite.'}
p = gate('advancing', 'Workflow', tool_input={'script': f'agent({json.dumps(OFF["prompt"])})'},
         ev_extra={'transcript_path': str(tr)})
am = rows(p.d, 'ask-match.jsonl')
show('Workflow whose script misses the latest message: flagged and logged, not refused, not said',
     p.returncode == 0 and am and am[0]['verdict'] == 'relay-gap' and not am[0]['noted']
     and am[0]['would_note'] and not p.ctx, f'{p.returncode} {am} {p.stdout[:120]}')
_d = pathlib.Path(tempfile.mkdtemp())
(_d / 'S1.json').write_text(json.dumps(session('advancing')))
_ev = {'session_id': 'S1', 'tool_name': 'Workflow', 'transcript_path': str(tr),
       'tool_input': {'script': f'agent({json.dumps(OFF["prompt"])})'}}
_p = subprocess.run([sys.executable, '-m', 'laserbrain.hooks.lb_gate'], input=json.dumps(_ev),
                    capture_output=True, text=True, cwd=str(ROOT),
                    env=env_for(_d, extra={'LASERBRAIN_ASKMATCH_NOTE': '1'}))
show('...LASERBRAIN_ASKMATCH_NOTE=1 hands the parent the note (opt-in: live replay 15/64 false flags)',
     _p.returncode == 0 and 'ask-match' in _p.stdout and 'permissionDecision' not in _p.stdout,
     _p.stdout[:120])
show('...the log holds no message or prompt text',
     'dragon' not in json.dumps(am) and 'parser' not in json.dumps(am), json.dumps(am)[:120])
p = gate('advancing', 'Agent', tool_input=OFF, ev_extra={'transcript_path': str(tr)})
am = rows(p.d, 'ask-match.jsonl')
show('Agent spawn: verdict logged, no note (nothing is relayed to an Agent child)',
     am and am[0]['flag'] and not am[0]['noted'] and not p.ctx, str(am))
ON = {'prompt': 'Make the dragon sprite wings bigger and recolor the scales green.'}
p = gate('advancing', 'Agent', tool_input=ON, ev_extra={'transcript_path': str(tr)})
am = rows(p.d, 'ask-match.jsonl')
show('a prompt carrying the latest message is aligned', am and am[0]['verdict'] == 'aligned', str(am))
p = gate('advancing', 'Agent', tool_input=OFF, ev_extra={'transcript_path': '/nonexistent/x.jsonl'})
show('an unreadable transcript fails open', p.returncode == 0, f'exit={p.returncode}')
p = gate('advancing', 'Workflow', mode='hard', tool_input={'script': 'x'},
         ev_extra={'transcript_path': str(tr)})
show('hard mode runs no ask-match', not (p.d / 'ask-match.jsonl').exists() and p.stdout == '')

print('\n  C. a task notification is not a user turn')
d = pathlib.Path(tempfile.mkdtemp())
t = d / 'main.jsonl'
t.write_text('{"type":"user","message":{"content":"hi"}}\n')
post(d, {'tool_name': 'Read', 'transcript_path': str(t), 'tool_response': {}})   # first sight
flag = d / 'home' / 'config' / 'user-turn'
cands = lambda: [f for f in (d / 'home').rglob('user-turn')] if (d / 'home').exists() else []  # noqa: E731
with t.open('a') as fh:
    fh.write(json.dumps({'type': 'queue-operation', 'operation': 'enqueue',
                         'content': '<task-notification><status>completed</status></task-notification>'}) + '\n')
post(d, {'tool_name': 'Read', 'transcript_path': str(t), 'tool_response': {}})
show('enqueue of a <task-notification> writes no re-ground flag', cands() == [], str(cands()))
with t.open('a') as fh:
    fh.write(json.dumps({'type': 'queue-operation', 'operation': 'enqueue',
                         'content': 'actually use the other file'}) + '\n')
post(d, {'tool_name': 'Read', 'transcript_path': str(t), 'tool_response': {}})
show('enqueue of a user message does', len(cands()) == 1, str(cands()))

print('\n  Stop hook (camelCase hosts)')


def stop(mode):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / 'C1.json').write_text(json.dumps({'steps': 30, 'checks': [{'step': 2, 'reason': 'advancing'}]}))
    ev = {'sessionId': 'C1', 'hook_event_name': 'Stop', 'reason': 'end_turn'}
    p = subprocess.run([sys.executable, str(ROOT / 'laserbrain/hooks/lb_coverage.py')],
                       input=json.dumps(ev), capture_output=True, text=True,
                       env=env_for(d, mode), cwd=str(ROOT))
    p.refusals = rows(d, 'refusals.jsonl')
    return p


p = stop(None)
show('unset: no decision=block at a lapsed turn end', '"block"' not in p.stdout, p.stdout[:100])
show('...the reminder is non-blocking context', 'additionalContext' in p.stdout and 'Not blocking' in p.stdout)
show('...and the would-be block is logged as nudge-stop', [r['stage'] for r in p.refusals] == ['nudge-stop'],
     str(p.refusals))
p = stop('hard')
show('hard: decision=block as before', '"decision": "block"' in p.stdout)

print('\n  ' + ('PASS' if ok else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
