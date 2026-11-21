"""askllm NOTE mode (lb_askllm_watch.py + lb_coverage.py): a flag from the frozen ask-mismatch
scorer reaches the flagged helper agent once, on its next tool call, and the parent (main)
session once, on its next tool call or prompt. Never a block.

Checked here, synthetic data only, a mock backend, no network: flag -> pending note -> one
delivery to the agent and one to the parent (in process and through lb_coverage as the harness
runs it), the delivery log lines, watch mode writes no note, off mode does nothing, an unknown
mode is silent, no date expiry any more, a corrupt note file is ignored and set aside, old
agent AND parent notes expire on any pass, switching away from note mode drops what is pending,
the note points the agent at its task (not a quoted user message), camelCase hosts are left
alone, the folder-name rule and TTLs shared with lb_coverage and its fast path, the worker's
environment allowlist, hook-side errors that never load the redactor, redaction in the note
text, and the hook-path cost.

usage: python3 test_askllm_notes.py [dir holding the laserbrain package]"""
import datetime
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

PKG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
HOOKS = PKG / 'laserbrain' / 'hooks'
REPO = PKG.parent
EVAL = REPO / 'research' / 'eval'
PY = sys.executable

for k in [k for k in os.environ if k.startswith('LASERBRAIN_')]:
    os.environ.pop(k)
os.environ['LASERBRAIN_STUDY'] = '1'  # the pre-2026-11-19 text; the quiet default is test_quiet_default.py

spec = importlib.util.spec_from_file_location('lb_askllm_watch', str(HOOKS / 'lb_askllm_watch.py'))
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

ok_all = True


def check(name, cond, detail=''):
    global ok_all
    ok_all &= bool(cond)
    print(f"  {'✓' if cond else '✗'} {name}" + (f'  — {detail}' if detail and not cond else ''))


FAKE_GH = 'ghp_' + 'Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2Rr1'                 # an lb_secrets match
REPLY_DRIFT = json.dumps({
    'asks': [{'ask': 'build the calendar week bar', 'in_task': True, 'in_goal': 'missing'}],
    'relay_unrelated': True, 'goal_follows_relay_scope': True, 'start_substituted': True,
    'end_declined': False, 'drift_score': 85,
    'why': f'Goal pursues the relayed message instead (token {FAKE_GH}).'})
REPLY_OK = json.dumps({
    'asks': [{'ask': 'build the calendar week bar', 'in_task': True, 'in_goal': 'covered'}],
    'relay_unrelated': False, 'goal_follows_relay_scope': False, 'start_substituted': False,
    'end_declined': False, 'drift_score': 5, 'why': 'Goal matches the task.'})


def line(**r):
    return json.dumps(r) + '\n'


def make_world(root, sid='lbtest-notes-1', agent='a1', wf='wf_test-002'):
    """A synthetic main transcript + one workflow agent, laid out like Claude Code's."""
    root = pathlib.Path(root)
    proj = root / 'projects'
    proj.mkdir(parents=True, exist_ok=True)
    main = proj / f'{sid}.jsonl'
    with open(main, 'w') as fh:
        fh.write(line(type='user', timestamp='2026-11-16T03:00:00.000Z', sessionId=sid,
                      message={'role': 'user', 'content': 'can u fix the calendar week bar'}))
        fh.write(line(type='queue-operation', operation='enqueue', timestamp='2026-11-16T03:01:00.000Z',
                      content='also the release notes later'))
    adir = proj / sid / 'subagents' / 'workflows' / wf
    adir.mkdir(parents=True, exist_ok=True)
    with open(adir / f'agent-{agent}.jsonl', 'w') as fh:
        fh.write(line(type='user', timestamp='2026-11-16T03:02:00.000Z', agentId=agent, isSidechain=True,
                      message={'role': 'user', 'content': '[Workflow harness — user request] relayed.\n'
                                                          '  also the release notes later'}))
        fh.write(line(type='user', timestamp='2026-11-16T03:02:00.100Z', agentId=agent, isSidechain=True,
                      message={'role': 'user', 'content': '[Workflow harness — computed task] task.\n'
                                                          '  Build the calendar week bar in ~/calendar.'}))
        fh.write(line(type='assistant', timestamp='2026-11-16T03:02:10.000Z', agentId=agent,
                      message={'role': 'assistant', 'content': [
                          {'type': 'text', 'text': 'I will write the release notes.'},
                          {'type': 'tool_use', 'id': 'tu1', 'name': 'mcp__laserbrain__check_state',
                           'input': {'goal': 'Write the release notes', 'progress': 'advancing',
                                     'distance': 8}}]}))
    (adir / f'agent-{agent}.meta.json').write_text(json.dumps(
        {'agentType': 'workflow-subagent', 'description': 'build:weekbar', 'workflowPhase': 'Build'}))
    (proj / sid / 'workflows').mkdir(parents=True, exist_ok=True)
    (proj / sid / 'workflows' / f'{wf}.json').write_text(json.dumps({'workflowName': 'calendar-fixes'}))
    return main


def frozen_ok(root):
    s2 = importlib.util.spec_from_file_location('aml_probe', str(EVAL / 'ask_match_llm.py'))
    m = importlib.util.module_from_spec(s2)
    sys.path.insert(0, str(EVAL))
    s2.loader.exec_module(m)
    p = pathlib.Path(root) / 'frozen.json'
    p.write_text(json.dumps({'frozen': {
        'model': m.MODEL, 'prompt_hash': {'askllm': m.prompt_hash('askllm')},
        'thresholds': m.THRESHOLDS, 'ask_match_llm_sha256': m.file_sha()}}))
    return p


class Mock:
    def __init__(self, text):
        self.text, self.calls = text, 0
        self.name, self.model, self.credential = 'mock', 'mock', None

    def call(self, system, prompt, schema):
        self.calls += 1
        return {'text': self.text, 'usage': None, 'meta': {'cost_usd': 0.0}}


def read_log(state):
    p = pathlib.Path(state) / W.LOG_NAME
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def job_for(main, state, sid='lbtest-notes-1', agent='a1'):
    return {'session': sid, 'agent_id': agent, 'agent_type': 'workflow-subagent', 'lane': 'build:weekbar',
            'tool_use_id': 'tu1', 'transcript_path': str(main), 'goal': 'Write the release notes',
            'hook_ts': '2026-11-16T03:02:11+00:00', 'state_dir': str(state), 'hook_ms': 1.0}


def ev_agent(sid='lbtest-notes-1', agent='a1', tool='Read'):
    return {'hook_event_name': 'PostToolUse', 'session_id': sid, 'agent_id': agent,
            'agent_type': 'workflow-subagent', 'tool_name': tool, 'tool_input': {'file_path': '/x'},
            'tool_response': {}}


def ev_main(sid='lbtest-notes-1', tool='Read'):
    return {'hook_event_name': 'PostToolUse', 'session_id': sid, 'tool_name': tool,
            'tool_input': {'file_path': '/x'}, 'tool_response': {}}


NOOP = lambda s: None  # noqa: E731

print('flag -> pending note -> delivered once to the agent, once to the parent (in process)')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    os.environ[W.ENV_FROZEN] = str(frozen_ok(td))
    main = make_world(td)
    check('note is the default mode', W.mode(state) == 'note' and W.DEFAULT_MODE == 'note')
    rec = W.run_job(job_for(main, state), backend=Mock(REPLY_DRIFT), delay=0, sleep=NOOP)
    nd = W.notes_dir(state, 'lbtest-notes-1')
    check('a flag in note mode writes a pending note for the agent and for the parent',
          rec['status'] == 'scored' and rec['flag'] and rec.get('note') == 'written'
          and rec.get('mode') == 'note' and (nd / 'a1.agent').exists() and (nd / 'a1.parent').exists(),
          f"{rec.get('status')} {rec.get('note')} {sorted(os.listdir(nd)) if nd.exists() else None}")
    check('no temp file is left behind (atomic write)', not [n for n in os.listdir(nd) if n.endswith('.tmp')])
    body = json.loads((nd / 'a1.agent').read_text())
    check('the note body carries the label, workflow name, verdict and missing asks',
          body['label'] == 'build:weekbar' and body['workflow_name'] == 'calendar-fixes'
          and body['verdict'] == 'substitution' and body['missing'] == ['build the calendar week bar'])
    check('secrets in the scorer reply never reach the note file',
          FAKE_GH not in (nd / 'a1.agent').read_text() and 'redacted' in (nd / 'a1.agent').read_text())

    out_other = W.deliver_notes(ev_agent(agent='a2'), state, 'posttooluse')
    check('another agent of the session gets nothing', out_other == [], out_other)
    out1 = W.deliver_notes(ev_agent(), state, 'posttooluse')
    out2 = W.deliver_notes(ev_agent(), state, 'posttooluse')
    check('the flagged agent gets ONE note on its next tool call', len(out1) == 1 and out2 == [], f'{out1} {out2}')
    t = out1[0] if out1 else ''
    check('the agent note points at the TASK and says it may carry on',
          t.startswith('laserbrain (askllm): your goal may leave out part of the task you were handed.')
          and 'Left out: build the calendar week bar' in t
          and 'The task text is what you were asked to do; a user message quoted in it can be older '
              'or about something else. Re-read the task before continuing' in t
          and 'if you are sure you are on it, carry on.' in t, t)
    check('...and never sends the agent back to the quoted user request (the cause of the drifts '
          'askllm caught)', 'request quoted' not in t and 'what the user asked' not in t, t)
    check('no secret in the delivered text', FAKE_GH not in t)
    p1 = W.deliver_notes(ev_main(), state, 'posttooluse')
    p2 = W.deliver_notes(ev_main(), state, 'userpromptsubmit')
    check('the parent gets ONE note on its next tool call', len(p1) == 1 and p2 == [], f'{p1} {p2}')
    pt = p1[0] if p1 else ''
    check('the parent note names the helper and its workflow and asks for a check',
          pt.startswith('laserbrain: helper build:weekbar in calendar-fixes may be off its task:')
          and "Check its result against the task you gave it and the user's ask." in pt, pt)
    lg = read_log(state)
    st = [x['status'] for x in lg]
    check('both deliveries are logged with timestamps',
          st.count('note_delivered_agent') == 1 and st.count('note_delivered_parent') == 1
          and all(x.get('ts') and x.get('note_written_ts') for x in lg if x['status'].startswith('note_')), st)
    check('the session folder is gone once nothing is pending', not nd.exists())

    main2 = make_world(pathlib.Path(td) / 'w2', sid='lbtest-notes-2')
    rec_ok = W.run_job(job_for(main2, state, sid='lbtest-notes-2'), backend=Mock(REPLY_OK), delay=0, sleep=NOOP)
    check('no flag, no note', rec_ok['status'] == 'scored' and not rec_ok['flag'] and 'note' not in rec_ok
          and not W.notes_dir(state, 'lbtest-notes-2').exists(), rec_ok.get('reason'))

    print('a prompt delivers the parent note too')
    main3 = make_world(pathlib.Path(td) / 'w3', sid='lbtest-notes-3')
    W.run_job(job_for(main3, state, sid='lbtest-notes-3'), backend=Mock(REPLY_DRIFT), delay=0, sleep=NOOP)
    pp = W.deliver_notes({'hook_event_name': 'UserPromptSubmit', 'session_id': 'lbtest-notes-3',
                          'prompt': 'next thing'}, state, 'userpromptsubmit')
    check('UserPromptSubmit in the main session takes the pending parent note', len(pp) == 1, pp)
    check("a parent's note never goes to another session",
          W.deliver_notes(ev_main(sid='lbtest-notes-2'), state, 'posttooluse') == [])
    rep = EVAL / 'askllm_watch_report.py'
    rj = subprocess.run([PY, str(rep), '--log', str(state / W.LOG_NAME), '--json'], capture_output=True,
                        text=True, timeout=60)
    rt = subprocess.run([PY, str(rep), '--log', str(state / W.LOG_NAME)], capture_output=True, text=True,
                        timeout=60)
    try:
        nj = json.loads(rj.stdout).get('notes') or {}
    except Exception:
        nj = {}
    check('the report shows notes written and delivered',
          nj.get('written') == 2 and nj.get('delivered_agent') == 1 and nj.get('delivered_parent') == 2
          and nj.get('pending') == 1 and 'notes: modes' in rt.stdout and 'note_delivered_parent' in rt.stdout,
          f'{nj} {rt.stdout[-400:]} {rj.stderr[-300:]}')

print('watch, off and unknown modes')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    os.environ[W.ENV_FROZEN] = str(frozen_ok(td))
    main = make_world(td)
    os.environ[W.ENV_MODE] = 'watch'
    rec = W.run_job(job_for(main, state), backend=Mock(REPLY_DRIFT), delay=0, sleep=NOOP)
    check('watch mode: scored and flagged, but no note written',
          rec['status'] == 'scored' and rec['flag'] and 'note' not in rec and rec.get('mode') == 'watch'
          and not W.notes_dir(state, 'lbtest-notes-1').exists())
    os.environ[W.ENV_MODE] = 'off'
    spawned = []
    real_spawn = W._spawn
    W._spawn = lambda job: spawned.append(job)
    ev = {'hook_event_name': 'PostToolUse', 'session_id': 'lbtest-notes-1', 'agent_id': 'a9',
          'transcript_path': str(main), 'tool_name': 'mcp__laserbrain__check_state', 'tool_use_id': 'tu1',
          'tool_input': {'goal': 'x', 'progress': 'advancing', 'distance': 5}}
    fresh = pathlib.Path(td) / 'state-off'
    r = W.on_post_tool_use(ev, ev['tool_name'], ev['tool_input'], fresh)
    W._spawn = real_spawn
    check('off mode: nothing spawned, nothing written', r == 'off' and not spawned and not fresh.exists(), r)
    check('off mode: the worker stands down', W.run_job(job_for(main, state), backend=Mock(REPLY_DRIFT),
                                                        delay=0, sleep=NOOP) is None)
    os.environ.pop(W.ENV_MODE)
    W.write_note(state, {'session': 'lbtest-notes-1', 'agent_id': 'a1'}, {'why': 'x', 'missing': []})
    os.environ[W.ENV_MODE] = 'off'
    n_log = len(read_log(state))
    check('off mode: a note already pending is not delivered, it is dropped (logged) and the folder goes',
          W.deliver_notes(ev_agent(), state, 'posttooluse') == []
          and not W.notes_dir(state, 'lbtest-notes-1').exists()
          and sorted((x['status'], x.get('kind'), x.get('mode')) for x in read_log(state)[n_log:])
          == [('note_dropped_mode', 'agent', 'off'), ('note_dropped_mode', 'parent', 'off')],
          read_log(state)[n_log:])
    os.environ[W.ENV_MODE] = 'loud'
    check('an unknown mode runs as watch (silent), never as note', W.mode(state) == 'watch'
          and W.deliver_notes(ev_agent(), state, 'posttooluse') == [])
    os.environ.pop(W.ENV_MODE)
    os.environ[W.ENV_SWITCH] = 'off'
    check('the old LASERBRAIN_ASKLLM_WATCH=off still switches it all off', W.mode(state) == 'off'
          and W.deliver_notes(ev_agent(), state, 'posttooluse') == [])
    os.environ.pop(W.ENV_SWITCH)
    (state / W.OFF_NAME).write_text('')
    check('the askllm-watch.off file still switches it all off', W.mode(state) == 'off')
    (state / W.OFF_NAME).unlink()
    check('no date expiry: still on in 2027 (the 2026-11-22 stop is gone)',
          W.switch_reason(state, datetime.datetime(2027, 1, 1)) is None and not hasattr(W, 'WATCH_END'))
    check('the 80/day cap and the 2-at-once limit are kept', W.DAILY_CAP == 80 and W.MAX_CONCURRENT == 2)

print('corrupt and stale note files')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    nd = W.notes_dir(state, 'lbtest-notes-1')
    nd.mkdir(parents=True)
    (nd / 'a1.agent').write_text('{not json')
    (nd / 'a1.parent').write_text('[1, 2]')
    try:
        r1 = W.deliver_notes(ev_agent(), state, 'posttooluse')
        r2 = W.deliver_notes(ev_main(), state, 'posttooluse')
        raised = None
    except BaseException as e:                               # noqa: BLE001
        r1 = r2 = None
        raised = e
    check('a corrupt note file is ignored: nothing delivered, nothing raised', r1 == [] and r2 == [] and raised is None,
          f'{r1} {r2} {raised!r}')
    aside = state / W.NOTES_DIR_NAME / '_set-aside'
    check('and set aside out of the session folder, so it is not read again',
          not nd.exists() and aside.is_dir() and len(os.listdir(aside)) == 2, os.listdir(aside) if aside.exists() else None)
    W.write_note(state, {'session': 'lbtest-notes-1', 'agent_id': 'old'}, {'why': 'x', 'missing': []})
    old = time.time() - W.NOTE_TTL_S - 60
    os.utime(nd / 'old.agent', (old, old))
    got = W.deliver_notes(ev_main(), state, 'posttooluse')
    st = [x['status'] for x in read_log(state)]
    check('an agent note nobody picked up within the TTL expires on the parent pass (logged, not shown)',
          len(got) == 1 and 'note_expired_agent' in st and not nd.exists(), f'{got} {st}')
    check('deliver_notes never raises on a missing state dir',
          W.deliver_notes(ev_agent(), pathlib.Path(td) / 'nope', 'posttooluse') == [])
    check('deliver_notes never raises on a malformed event', W.deliver_notes({}, state, None) == []
          and W.deliver_notes({'session_id': None}, state, None) == [])

print('a mode switch or the TTLs never leave a session folder behind')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    nd = W.notes_dir(state, 'lbtest-notes-1')
    for sw in (('mode', 'watch'), ('mode', 'off'), ('env', 'off'), ('file', None)):
        W.write_note(state, {'session': 'lbtest-notes-1', 'agent_id': 'h1'}, {'why': 'x', 'missing': []})
        if sw[0] == 'mode':
            os.environ[W.ENV_MODE] = sw[1]
        elif sw[0] == 'env':
            os.environ[W.ENV_SWITCH] = 'off'
        else:
            (state / W.OFF_NAME).write_text('')
        n_log = len(read_log(state))
        got = W.deliver_notes(ev_main(), state, 'posttooluse', now=time.time() + 7 * 3600)
        os.environ.pop(W.ENV_MODE, None)
        os.environ.pop(W.ENV_SWITCH, None)
        if (state / W.OFF_NAME).exists():
            (state / W.OFF_NAME).unlink()
        st = [x['status'] for x in read_log(state)[n_log:]]
        check(f'{sw[0]} {sw[1] or "file"}: pending notes are dropped on the next pass, the folder goes',
              got == [] and not nd.exists() and st == ['note_dropped_mode'] * 2, f'{got} {st}')
    W.write_note(state, {'session': 'lbtest-notes-1', 'agent_id': 'h1'}, {'why': 'x', 'missing': []})
    os.environ[W.ENV_MODE] = 'watch'
    W.deliver_notes(ev_agent(agent='other'), state, 'posttooluse')
    os.environ.pop(W.ENV_MODE)
    check("...a helper's pass drops them too", not nd.exists())

    W.write_note(state, {'session': 'lbtest-notes-1', 'agent_id': 'h2'}, {'label': 'L', 'why': 'x', 'missing': []})
    n_log = len(read_log(state))
    got = W.deliver_notes(ev_main(), state, 'posttooluse', now=time.time() + 30 * 86400)
    st = [x['status'] for x in read_log(state)[n_log:]]
    check('a parent note has a TTL too: a session resumed 30 days later gets no stale line',
          got == [] and 'note_expired_parent' in st and 'note_expired_agent' in st and not nd.exists(),
          f'{got} {st}')
    check('the parent TTL is 24 h, the agent TTL 6 h', W.PARENT_NOTE_TTL_S == 24 * 3600 and W.NOTE_TTL_S == 6 * 3600)
    W.write_note(state, {'session': 'lbtest-notes-1', 'agent_id': 'h3'}, {'why': 'x', 'missing': []})
    old = time.time() - W.NOTE_TTL_S - 60
    os.utime(nd / 'h3.agent', (old, old))
    n_log = len(read_log(state))
    got = W.deliver_notes(ev_agent(agent='h4'), state, 'posttooluse')
    st = [x['status'] for x in read_log(state)[n_log:]]
    check("expiry runs on a HELPER's pass too (a workflow's main is blocked in the tool)",
          got == [] and st == ['note_expired_agent'] and not (nd / 'h3.agent').exists()
          and (nd / 'h3.parent').exists(), f'{got} {st}')
    got = W.deliver_notes(ev_main(), state, 'posttooluse')
    check('...while its fresh parent note still goes out once', len(got) == 1 and not nd.exists(), got)

print("lb_coverage's fast path: the module loads only when this call has work")
with tempfile.TemporaryDirectory() as td:
    state, home = pathlib.Path(td) / 'state', pathlib.Path(td) / 'home'
    home.mkdir()
    sid = 'lbtest-notes-fast'
    W.write_note(state, {'session': sid, 'agent_id': 'h1'}, {'why': 'x', 'missing': []})
    nd = W.notes_dir(state, sid)
    probe = (
        'import importlib.util as u, json, pathlib, sys, os\n'
        'sp = u.spec_from_file_location("lbc_probe", sys.argv[1]); C = u.module_from_spec(sp); sp.loader.exec_module(C)\n'
        'd = pathlib.Path(sys.argv[2]); out = {"ttl": C._ASKLLM_NOTE_TTL_S}\n'
        'out["other_helper"] = C._askllm_notes_due(d, "h7")\n'
        'out["own_helper"] = C._askllm_notes_due(d, "h1")\n'
        'os.remove(d / "h1.parent")\n'
        'out["main_agent_only"] = C._askllm_notes_due(d, None)\n'
        'old = __import__("time").time() - 7 * 3600; os.utime(d / "h1.agent", (old, old))\n'
        'out["main_stale_agent"] = C._askllm_notes_due(d, None)\n'
        'os.environ["LASERBRAIN_ASKLLM_MODE"] = "watch"; out["watch_mode"] = C._askllm_notes_due(d, "h7")\n'
        'print(json.dumps(out))\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env['LASERBRAIN_STUDY'] = '1'  # the pre-2026-11-19 text; the quiet default is test_quiet_default.py
    env.update(LASERBRAIN_STATE_DIR=str(state), HOME=str(home), PYTHONPATH=str(PKG))
    r = subprocess.run([PY, '-P', '-c', probe, str(HOOKS / 'lb_coverage.py'), str(nd)], capture_output=True,
                       text=True, env=env, timeout=60)
    try:
        fp = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        fp = {}
    check("another helper's pending note does not load lb_askllm_watch for this helper",
          fp.get('other_helper') is False, r.stdout[-300:] + r.stderr[-300:])
    check("the flagged helper's own note does", fp.get('own_helper') is True)
    check('a main pass with only a fresh agent note pending: no load', fp.get('main_agent_only') is False)
    check('a main pass with a stale agent note: load (to expire it)', fp.get('main_stale_agent') is True)
    check('a mode other than note: load (to drop what is pending)', fp.get('watch_mode') is True)
    check("lb_coverage's TTL copy is lb_askllm_watch's",
          fp.get('ttl') == {'.agent': W.NOTE_TTL_S, '.parent': W.PARENT_NOTE_TTL_S}, fp.get('ttl'))

print("the worker's environment allowlist and hook-side errors")
env = {'PATH': '/usr/bin', 'HOME': '/h', 'USER': 'u', 'LC_ALL': 'C', 'LASERBRAIN_STATE_DIR': '/s',
       'TMPDIR': '/t', 'CLAUDE_EFFORT': 'high', 'CLAUDE_CODE_SIMPLE': '1', 'ANTHROPIC_BASE_URL': 'https://x',
       'CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH': '1', 'CLAUDE_AGENT_SDK_VERSION': '9',
       'CLAUDE_CODE_SESSION_ID': 's', 'CLAUDE_CODE_MESSAGING_SOCKET': '/m', 'CLAUDE_CODE_OAUTH_TOKEN': 'tok'}
kept = W.restrict_child_env(env)
check('only the allowlist survives: host session, effort, SDK, base-URL and token variables are dropped',
      kept == sorted(['PATH', 'HOME', 'USER', 'LC_ALL', 'LASERBRAIN_STATE_DIR', 'TMPDIR']) == sorted(env), kept)
check('every session-link variable is outside the allowlist',
      not [k for k in W.SESSION_LINK_ENV if k in W.CHILD_ENV_KEEP or k.startswith(W.CHILD_ENV_KEEP_PREFIX)])
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    W._REDACT = None
    # A frozen block that exists, so the hook gets past its no-judge return (0.58.0) to the
    # failing call; the one set earlier lived in a temp dir that is gone.
    os.environ[W.ENV_FROZEN] = str(frozen_ok(td))
    path0 = list(sys.path)
    real_ws = W._with_seen
    W._with_seen = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom ' + FAKE_GH))
    main = make_world(td)
    ev = {'hook_event_name': 'PostToolUse', 'session_id': 'lbtest-notes-1', 'agent_id': 'a9',
          'transcript_path': str(main), 'tool_name': 'mcp__laserbrain__check_state', 'tool_use_id': 'tu1',
          'tool_input': {'goal': 'x', 'progress': 'advancing', 'distance': 5}}
    try:
        r = W.on_post_tool_use(ev, ev['tool_name'], ev['tool_input'], state)
    finally:
        W._with_seen = real_ws
    lg = read_log(state)
    check('a hook-side error is one line with its type only, never raised', r == 'error' and lg
          and lg[-1]['reason'] == 'hook: RuntimeError' and lg[-1].get('error') is None
          and FAKE_GH not in (state / W.LOG_NAME).read_text(), lg[-1:])
    check("...and never loads the redactor or touches lb_coverage's sys.path",
          W._REDACT is None and sys.path == path0)

print('hook-path cost (in process)')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    state.mkdir()
    n = 300
    t0 = time.perf_counter()
    for _ in range(n):
        W.deliver_notes(ev_agent(), state, 'posttooluse')
    none_ms = (time.perf_counter() - t0) * 1000 / n
    ms = []
    for i in range(30):
        W.write_note(state, {'session': 'lbtest-notes-1', 'agent_id': f'b{i}'}, {'why': 'x', 'missing': ['y']})
        t1 = time.perf_counter()
        W.deliver_notes(ev_agent(agent=f'b{i}'), state, 'posttooluse')
        ms.append((time.perf_counter() - t1) * 1000)
    ms.sort()
    print(f'    no note pending: {none_ms:.3f} ms per call; claiming one note: median {ms[15]:.2f} ms, max {ms[-1]:.2f} ms')
    check('with nothing pending the check is a stat (< 1 ms)', none_ms < 1.0, f'{none_ms:.3f} ms')
    check('claiming a note stays small (median < 10 ms)', ms[15] < 10.0, f'{ms[15]:.2f} ms')


def run_hook(ev, state, home, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env['LASERBRAIN_STUDY'] = '1'  # the pre-2026-11-19 text; the quiet default is test_quiet_default.py
    env.update(PYTHONPATH=str(PKG), LASERBRAIN_STATE_DIR=str(state), LASERBRAIN_AGENT='claude',
               HOME=str(home), PATH='/usr/bin:/bin', LASERBRAIN_TURNS_HARVEST='0')
    env.update(extra or {})
    t0 = time.perf_counter()
    r = subprocess.run([PY, '-P', '-m', 'laserbrain.hooks.lb_coverage'], input=json.dumps(ev), text=True,
                       capture_output=True, env=env, timeout=60)
    return r, (time.perf_counter() - t0) * 1000


def ctx(stdout):
    try:
        return json.loads(stdout)['hookSpecificOutput']
    except Exception:
        return {}


print('through lb_coverage, as the harness runs it')
with tempfile.TemporaryDirectory() as td:
    td = pathlib.Path(td)
    state, home = td / 'state', td / 'home'
    state.mkdir()
    home.mkdir()
    sid = 'lbtest-notes/odd id:1'                               # the folder-name rule is shared
    W.write_note(state, {'session': sid, 'agent_id': 'a1'},
                 {'label': 'review:sec', 'workflow_name': 'audit-run', 'why': 'Goal reviews only the CSS.',
                  'missing': ['review the auth module']})
    base = []
    for _ in range(3):
        _, ms0 = run_hook(ev_agent(sid='lbtest-other', agent='zz'), state, home)
        base.append(ms0)
    r1, ms1 = run_hook(ev_agent(sid=sid), state, home)
    r2, _ = run_hook(ev_agent(sid=sid), state, home)
    h1, h2 = ctx(r1.stdout), ctx(r2.stdout)
    check("the agent's next PostToolUse carries the note as additionalContext",
          r1.returncode == 0 and 'laserbrain (askllm): your goal may leave out part of the task you were handed.'
          in (h1.get('additionalContext') or '') and h1.get('hookEventName') == 'PostToolUse', r1.stdout[:300])
    check('...once: the following call does not repeat it',
          'laserbrain (askllm)' not in (h2.get('additionalContext') or ''), r2.stdout[:300])
    check('a different agent of the same session never sees it',
          'askllm' not in run_hook(ev_agent(sid=sid, agent='a7'), state, home)[0].stdout)
    camel = {'hookEventName': 'PostToolUse', 'sessionId': sid, 'toolName': 'Read', 'toolInput': {}}
    rc, _ = run_hook(camel, state, home)
    check('a camelCase host (stdout ignored) does not claim the parent note',
          'helper' not in rc.stdout and any(n.endswith('.parent') for n in os.listdir(W.notes_dir(state, sid))),
          rc.stdout[:200])
    rp = run_hook({'hook_event_name': 'UserPromptSubmit', 'session_id': sid, 'prompt': 'what next'}, state, home)[0]
    hp = ctx(rp.stdout)
    check('the parent session gets its note on its next prompt, labelled UserPromptSubmit',
          'laserbrain: helper review:sec in audit-run may be off its task' in (hp.get('additionalContext') or '')
          and hp.get('hookEventName') == 'UserPromptSubmit', rp.stdout[:300])
    rp2 = run_hook(ev_main(sid=sid), state, home)[0]
    check('...once', 'may be off its task' not in rp2.stdout)
    base.sort()
    print(f'    lb_coverage wall time: no note {base[1]:.0f} ms, delivering a note {ms1:.0f} ms')
    check('delivering a note adds little to the hook (< 150 ms over the median)', ms1 - base[1] < 150,
          f'{ms1:.0f} vs {base[1]:.0f} ms')
    st = [x['status'] for x in read_log(state)]
    check('lb_coverage deliveries are logged', st.count('note_delivered_agent') == 1
          and st.count('note_delivered_parent') == 1, st)
    check('every hook call exited 0 with nothing on stderr', all(x.returncode == 0 for x in (r1, r2, rc, rp, rp2))
          and not (r1.stderr or r2.stderr or rp.stderr), (r1.stderr + rp.stderr)[-300:])

print('  PASS' if ok_all else '  FAIL')
raise SystemExit(0 if ok_all else 1)
