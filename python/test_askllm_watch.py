"""The live askllm check (lb_askllm_watch.py, change A, since 2026-11-15) runs the FROZEN AI-graded
ask-mismatch scorer once per helper agent, at its first check_state, in a detached process. The
scoring itself says nothing to anyone: no stdout, no stderr, never a block. In watch mode nothing
else happens; in note mode (the default since the Unreleased entry) a flag becomes a note, which
test_askllm_notes.py covers.

Checked here, with a mock backend and no network: trigger-once, main-session skip, silent output
in watch mode (lb_coverage's stdout/stderr are byte-identical with the check on and off), detached
launch, the daily cap, the kill switches, no automatic end date any more, the frozen-mismatch skip,
redaction of secrets in what is logged and what is sent, exception isolation, the not-first
guards, and the row stamps: every row carries trigger and policy (null when LASERBRAIN_POLICY is
unset), every row whose prompt was rendered carries row_sha (16 hex digits of sha256 over the
system text, a newline and the prompt), and the report splits its counts by trigger and policy.

usage: python3 test_askllm_watch.py [dir holding the laserbrain package]"""
import datetime
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

PKG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
HOOKS = PKG / 'laserbrain' / 'hooks'
REPO = PKG.parent
EVAL = REPO / 'research' / 'eval'
PY = sys.executable

spec = importlib.util.spec_from_file_location('lb_askllm_watch', str(HOOKS / 'lb_askllm_watch.py'))
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

ok_all = True


def check(name, cond, detail=''):
    global ok_all
    ok_all &= bool(cond)
    print(f"  {'✓' if cond else '✗'} {name}" + (f'  — {detail}' if detail and not cond else ''))


# Every row this test writes: in process through W._append_log, and the detached workers' rows
# as they are read back (seen_rows). The stamp checks at the end run over all of them.
ROWS = []
_real_append_log = W._append_log


def _recording_append_log(state_dir, rec):
    ROWS.append(json.loads(json.dumps(rec, default=str)))
    return _real_append_log(state_dir, rec)


W._append_log = _recording_append_log


def seen_rows(rows):
    ROWS.extend(rows)
    return rows


def is_row_sha(v):
    return isinstance(v, str) and re.fullmatch(r'[0-9a-f]{16}', v) is not None


def stamped(r, policy=None):
    return r.get('trigger') == 'check_state' and 'policy' in r and r['policy'] == policy


FAKE_ANT = 'sk-ant-' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4'          # an lb_secrets match (labelled openai: sk-)
FAKE_GH = 'ghp_' + 'Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2Rr1'                 # matches 'github-token'

REPLY_DRIFT = json.dumps({
    'asks': [{'ask': 'build the calendar week bar', 'in_task': True, 'in_goal': 'missing'}],
    'relay_unrelated': True, 'goal_follows_relay_scope': True, 'start_substituted': True,
    'end_declined': False, 'drift_score': 85, 'why': 'Goal pursues the relayed message instead.'})
REPLY_OK = json.dumps({
    'asks': [{'ask': 'build the calendar week bar', 'in_task': True, 'in_goal': 'covered'}],
    'relay_unrelated': False, 'goal_follows_relay_scope': False, 'start_substituted': False,
    'end_declined': False, 'drift_score': 5, 'why': 'Goal matches the task.'})


def line(**r):
    return json.dumps(r) + '\n'


def make_world(root, sid='lbtest-watch-1', agent='a1', wf='wf_test-001', task_extra='',
               relayed_extra='', n_checks=1, ids=('tu1', 'tu2', 'tu3')):
    """A fake main transcript + one workflow agent transcript, laid out like Claude Code's."""
    root = pathlib.Path(root)
    proj = root / 'projects'
    proj.mkdir(parents=True, exist_ok=True)
    main = proj / f'{sid}.jsonl'
    with open(main, 'w') as fh:
        fh.write(line(type='user', timestamp='2026-11-16T03:00:00.000Z', sessionId=sid,
                      message={'role': 'user', 'content': 'can u fix the calendar week bar'}))
        fh.write(line(type='assistant', timestamp='2026-11-16T03:00:05.000Z', sessionId=sid,
                      message={'role': 'assistant', 'content': [{'type': 'text', 'text': 'On it.'}]}))
        fh.write(line(type='queue-operation', operation='enqueue', timestamp='2026-11-16T03:01:00.000Z',
                      content='also the release notes later'))
        fh.write(line(type='user', timestamp='2026-11-16T09:00:00.000Z', sessionId=sid,
                      message={'role': 'user', 'content': 'this one comes after the spawn'}))
    adir = proj / sid / 'subagents' / 'workflows' / wf
    adir.mkdir(parents=True, exist_ok=True)
    ap = adir / f'agent-{agent}.jsonl'
    relayed = ('[Workflow harness — user request] The harness relays, verbatim and indented below, '
               'the user request.\n  also the release notes later' + relayed_extra)
    task = ('[Workflow harness — computed task] The task text below was computed.\n'
            '  Build the calendar week bar (item 3) in ~/calendar and run its tests.' + task_extra)
    with open(ap, 'w') as fh:
        fh.write(line(type='user', timestamp='2026-11-16T03:02:00.000Z', agentId=agent, isSidechain=True,
                      message={'role': 'user', 'content': relayed}))
        fh.write(line(type='user', timestamp='2026-11-16T03:02:00.100Z', agentId=agent, isSidechain=True,
                      message={'role': 'user', 'content': task}))
        for i in range(n_checks):
            fh.write(line(type='assistant', timestamp=f'2026-11-16T03:02:{10 + i:02d}.000Z', agentId=agent,
                          message={'role': 'assistant', 'content': [
                              {'type': 'text', 'text': 'I will build the week bar.'},
                              {'type': 'tool_use', 'id': ids[i], 'name': 'mcp__laserbrain__check_state',
                               'input': {'goal': 'Build the calendar week bar', 'progress': 'advancing',
                                         'distance': 8}}]}))
    (adir / f'agent-{agent}.meta.json').write_text(json.dumps(
        {'agentType': 'workflow-subagent', 'description': 'build:weekbar', 'workflowPhase': 'Build'}))
    return main, ap


def event(main, sid='lbtest-watch-1', agent='a1', tool_use_id='tu1', goal='Build the calendar week bar'):
    ev = {'hook_event_name': 'PostToolUse', 'session_id': sid, 'transcript_path': str(main),
          'cwd': '/tmp', 'tool_name': 'mcp__laserbrain__check_state', 'tool_use_id': tool_use_id,
          'tool_input': {'goal': goal, 'progress': 'advancing', 'distance': 8, 'session': 'build:weekbar'},
          'tool_response': json.dumps({'arm': 'sighted', 'drifting': False})}
    if agent:
        ev['agent_id'] = agent
        ev['agent_type'] = 'workflow-subagent'
    return ev


def frozen_ok(root):
    """A frozen block holding the CURRENT scorer's values, so the mechanics are tested even in a
    checkout without eval/. The real frozen block is checked separately below."""
    s2 = importlib.util.spec_from_file_location('aml_probe', str(EVAL / 'ask_match_llm.py'))
    m = importlib.util.module_from_spec(s2)
    sys.path.insert(0, str(EVAL))
    s2.loader.exec_module(m)
    p = pathlib.Path(root) / 'frozen.json'
    p.write_text(json.dumps({'frozen': {
        'model': m.MODEL, 'prompt_hash': {'askllm': m.prompt_hash('askllm')},
        'thresholds': m.THRESHOLDS, 'ask_match_llm_sha256': m.file_sha()}}))
    return p


def read_log(state):
    p = pathlib.Path(state) / W.LOG_NAME
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


class Mock:
    def __init__(self, text):
        self.text, self.calls, self.prompts, self.systems = text, 0, [], []
        self.name, self.model, self.credential = 'mock', 'mock', None

    def call(self, system, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        self.systems.append(system)
        return {'text': self.text, 'usage': None, 'meta': {'cost_usd': 0.0}}


NOW = datetime.datetime(2026, 11, 16, 12, 0, 0)
spawned = []
W._spawn = lambda job: spawned.append(job) or _FakeProc()


class _FakeProc:
    class _In:
        def write(self, b):
            self.data = b

        def close(self):
            pass
    stdin = _In()


for k in [k for k in os.environ if k.startswith('LASERBRAIN_')]:
    os.environ.pop(k)

print('trigger')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    main, ap = make_world(td)
    ev = event(main)
    r1 = W.on_post_tool_use(ev, ev['tool_name'], ev['tool_input'], state, now=NOW)
    r2 = W.on_post_tool_use(ev, ev['tool_name'], ev['tool_input'], state, now=NOW)
    check('first check_state of a helper agent spawns the worker', r1 == 'spawned', r1)
    check('the same agent is never spawned twice (marker persists)', r2 == 'seen' and len(spawned) == 1, r2)
    ev_b = event(main, agent='a2')
    check('another agent of the same session is its own start',
          W.on_post_tool_use(ev_b, ev_b['tool_name'], ev_b['tool_input'], state, now=NOW) == 'spawned')
    job = spawned[0]
    check('the job carries session, agent, lane, goal, tool_use_id, state dir',
          job['session'] == 'lbtest-watch-1' and job['agent_id'] == 'a1' and job['lane'] == 'build:weekbar'
          and job['goal'] == 'Build the calendar week bar' and job['tool_use_id'] == 'tu1'
          and job['state_dir'] == str(state))
    check('the job carries trigger check_state and policy null while LASERBRAIN_POLICY is unset',
          job.get('trigger') == 'check_state' and 'policy' in job and job['policy'] is None, job)
    os.environ[W.ENV_POLICY] = 'quiet-2026-11-19' + 'x' * 40
    ev_p = event(main, agent='a-policy')
    rp_ = W.on_post_tool_use(ev_p, ev_p['tool_name'], ev_p['tool_input'], state, now=NOW)
    os.environ.pop(W.ENV_POLICY)
    check('with LASERBRAIN_POLICY set the job carries it, cut to 40 characters',
          rp_ == 'spawned' and spawned[-1].get('policy') == ('quiet-2026-11-19' + 'x' * 40)[:40]
          and spawned[-1].get('trigger') == 'check_state', spawned[-1])
    ev_m = event(main, agent=None)
    n0 = len(spawned)
    r = W.on_post_tool_use(ev_m, ev_m['tool_name'], ev_m['tool_input'], state, now=NOW)
    check('main session (no agent_id) is never scored', r == 'main' and len(spawned) == n0, r)
    # An installed wheel has no research/eval and no eval/: nothing may start (0.58.0).
    for envk, where in ((W.ENV_EVAL, pathlib.Path(td) / 'no-eval-here'),
                        (W.ENV_FROZEN, pathlib.Path(td) / 'no-frozen-here.json')):
        os.environ[envk] = str(where)
        ev_nj = event(main, agent='a-no-judge-' + envk)
        r = W.on_post_tool_use(ev_nj, ev_nj['tool_name'], ev_nj['tool_input'], state, now=NOW)
        os.environ.pop(envk)
        check(f'with no {"frozen scorer" if envk == W.ENV_EVAL else "frozen block"} on disk: '
              'no-judge, and no worker started', r == 'no-judge' and len(spawned) == n0, r)
    ev_x = dict(event(main, agent='a3'), tool_name='Bash', tool_input={'command': 'ls'})
    check('a non-check_state call does nothing',
          W.on_post_tool_use(ev_x, 'Bash', {'command': 'ls'}, state, now=NOW) == 'not-check')
    ev_n = dict(event(main, agent='a4'), transcript_path='/nonexistent/x.jsonl')
    check('no transcript on disk: nothing spawned (tests and replays never reach a model)',
          W.on_post_tool_use(ev_n, ev_n['tool_name'], ev_n['tool_input'], state, now=NOW) == 'no-transcript')
    (state / 'lbtest-watch-1.agents.json').write_text(json.dumps({'a5': {'steps': 40, 'checks': 6}}))
    ev_5 = event(main, agent='a5')
    n0 = len(spawned)
    r = W.on_post_tool_use(ev_5, ev_5['tool_name'], ev_5['tool_input'], state, now=NOW)
    r_again = W.on_post_tool_use(ev_5, ev_5['tool_name'], ev_5['tool_input'], state, now=NOW)
    check('an agent the sidecar has seen check in before is not-first, marked, never spawned',
          r == 'not-first' and r_again == 'seen' and len(spawned) == n0, f'{r} {r_again}')

print('switches, cap, expiry')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    main, ap = make_world(td)
    ev = event(main)
    os.environ[W.ENV_SWITCH] = 'off'
    n0 = len(spawned)
    r = W.on_post_tool_use(ev, ev['tool_name'], ev['tool_input'], state, now=NOW)
    check('LASERBRAIN_ASKLLM_WATCH=off: nothing spawned, nothing written',
          r == 'off' and len(spawned) == n0 and not (state / W.SEEN_NAME).exists(), r)
    os.environ.pop(W.ENV_SWITCH)
    state.mkdir(parents=True, exist_ok=True)
    (state / W.OFF_NAME).write_text('')
    r = W.on_post_tool_use(ev, ev['tool_name'], ev['tool_input'], state, now=NOW)
    check('file switch askllm-watch.off: nothing spawned', r == 'off' and len(spawned) == n0, r)
    check('run_job also stands down under the file switch', W.run_job(
        {'state_dir': str(state), 'session': 's', 'agent_id': 'a'}, backend=Mock(REPLY_OK), delay=0) is None)
    os.replace(state / W.OFF_NAME, pathlib.Path(td) / 'off.moved')
    # The 2026-11-22 auto-stop is replaced by note mode, which stays on (test_askllm_notes.py).
    late = datetime.datetime(2026, 11, 23, 0, 0, 0)
    check('no longer stops by itself after 2026-11-22: note mode stays on',
          W.switch_reason(state, late) is None and W.mode(state) == 'note')
    os.environ[W.ENV_MODE] = 'off'
    check('LASERBRAIN_ASKLLM_MODE=off: nothing spawned',
          W.on_post_tool_use(ev, ev['tool_name'], ev['tool_input'], state, now=late) == 'off')
    check('run_job stands down in off mode', W.run_job(
        {'state_dir': str(state), 'session': 's', 'agent_id': 'a'}, backend=Mock(REPLY_OK), delay=0,
        now=late) is None and not read_log(state))
    os.environ.pop(W.ENV_MODE)
    d = {'seen': {}, 'calls': {NOW.date().isoformat(): W.DAILY_CAP}}
    (state / W.SEEN_NAME).write_text(json.dumps(d))
    r = W.on_post_tool_use(ev, ev['tool_name'], ev['tool_input'], state, now=NOW)
    lg = read_log(state)
    check('at the daily cap the hook spawns nothing and logs one skip',
          r == 'cap' and len(spawned) == n0 and len(lg) == 1 and lg[0]['reason'] == 'daily cap', r)
    check('the hook-side cap skip row carries trigger and policy (null: unset)',
          lg and stamped(lg[0]) and 'row_sha' not in lg[0], lg[:1])
    check('reserve_call refuses at the cap and counts nothing',
          W.reserve_call(state, now=NOW) is False and W.calls_today(state, now=NOW) == W.DAILY_CAP)
    check('below the cap reserve_call counts one call',
          W.reserve_call(state, cap=2, now=datetime.datetime(2026, 11, 17, 9)) is True
          and W.calls_today(state, now=datetime.datetime(2026, 11, 17, 9)) == 1)

print('worker (mock backend, in process)')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    os.environ[W.ENV_FROZEN] = str(frozen_ok(td))
    main, ap = make_world(td, task_extra=f' Key in config: {FAKE_ANT}', relayed_extra=f' token {FAKE_GH}')
    job = {'session': 'lbtest-watch-1', 'agent_id': 'a1', 'agent_type': 'workflow-subagent',
           'lane': 'build:weekbar', 'tool_use_id': 'tu1', 'transcript_path': str(main),
           'goal': 'Build the calendar week bar', 'hook_ts': '2026-11-16T03:02:11+00:00',
           'state_dir': str(state), 'hook_ms': 3.2}
    mk = Mock(REPLY_DRIFT)
    rec = W.run_job(job, backend=mk, delay=0, sleep=lambda s: None)
    check('scored once with the frozen scorer', rec['status'] == 'scored' and mk.calls == 1, rec.get('reason'))
    check('flag, where, verdict and drift score come from the frozen decide()',
          rec['flag'] is True and rec['where'] == 'start' and rec['verdict'] == 'substitution'
          and rec['drift_score'] == 85)
    inp = rec['inputs']
    check('inputs recorded: user_recent before the spawn only, relayed, task, goal, no final text',
          inp['user_recent'] == 2 and inp['user_relayed'] and inp['task'] and inp['goal']
          and inp['final_text'] is False and inp['early_text'], inp)
    pr = mk.prompts[0]
    check('the prompt is render(row, "askllm"): user messages, relayed, task, goal, start-only',
          'can u fix the calendar week bar' in pr and 'also the release notes later' in pr
          and 'Build the calendar week bar (item 3)' in pr and 'GOAL: Build the calendar week bar' in pr
          and '(no final report)' in pr and 'this one comes after the spawn' not in pr)
    check('secrets never reach the model', FAKE_ANT not in pr and FAKE_GH not in pr
          and pr.count('[redacted:') >= 2 and '[redacted:github-token]' in pr, pr[-900:])
    raw = (state / W.LOG_NAME).read_text()
    check('secrets never reach the log', FAKE_ANT not in raw and FAKE_GH not in raw and 'redacted' in raw)
    check('log line has workflow, label, phase, frozen sha, model, latency',
          rec['workflow'] == 'wf_test-001' and rec['label'] == 'build:weekbar' and rec['phase'] == 'Build'
          and len(rec['frozen_sha'] or '') == 64 and rec['model'] and rec['hook_ms'] == 3.2
          and 'call_s' in rec and rec['variant'] == 'start-only')
    check('snippets are short', all(v is None or len(v) <= 210 for v in rec['snippets'].values()))
    sys_ = mk.systems[0] if mk.systems else ''
    want_sha = hashlib.sha256(f'{sys_}\n{pr}'.encode('utf-8')).hexdigest()[:16]
    check('the scored row carries trigger check_state, policy null (unset) and row_sha',
          stamped(rec) and is_row_sha(rec.get('row_sha')), {k: rec.get(k) for k in ('trigger', 'policy', 'row_sha')})
    check('row_sha is sha256(system + newline + prompt) of exactly what the model was sent, 16 hex',
          rec.get('row_sha') == want_sha == W.row_sha(sys_, pr), f"{rec.get('row_sha')} vs {want_sha}")
    check('row_sha never raises on a lone surrogate (a JSON escape can make one)',
          is_row_sha(W.row_sha('s', 'a\ud800b')) and W.row_sha('s', 'a\ud800b') != W.row_sha('s', 'ab'))
    mk_same = Mock(REPLY_OK)
    rec_same = W.run_job(dict(job, agent_id='a1', session='lbtest-watch-1'), state_dir=pathlib.Path(td) / 'state-same',
                         backend=mk_same, delay=0, sleep=lambda s: None)
    check('the same row rendered again gives the same row_sha (a different reply does not matter)',
          rec_same.get('row_sha') == rec.get('row_sha') and rec_same['status'] == 'scored', rec_same.get('reason'))
    rec_pol = W.run_job(dict(job, policy='quiet-2026-11-19', trigger='check_state'),
                        state_dir=pathlib.Path(td) / 'state-pol', backend=Mock(REPLY_OK), delay=0,
                        sleep=lambda s: None)
    check("a job's policy reaches its row", rec_pol['status'] == 'scored'
          and stamped(rec_pol, 'quiet-2026-11-19') and is_row_sha(rec_pol.get('row_sha')), rec_pol.get('policy'))
    check('the call counted against the cap', W.calls_today(state) == 1)
    mk2 = Mock(REPLY_OK)
    j2 = dict(job, agent_id='a1', tool_use_id='tu2')
    main2, ap2 = make_world(pathlib.Path(td) / 'w2', n_checks=2)
    j2['transcript_path'] = str(main2)
    rec2 = W.run_job(j2, backend=mk2, delay=0, sleep=lambda s: None)
    check('not the first check_state in the transcript: skipped, no call',
          rec2['status'] == 'skipped' and rec2['reason'] == 'not first check_state' and mk2.calls == 0,
          rec2.get('reason'))
    j3 = dict(job, agent_id='nobody')
    rec3 = W.run_job(j3, backend=Mock(REPLY_OK), delay=0, sleep=lambda s: None)
    check('agent transcript missing: skipped and logged', rec3['reason'] == 'agent transcript not found')
    check('skipped rows (not first, no transcript) carry trigger and policy, and no row_sha before a render',
          stamped(rec2) and stamped(rec3) and 'row_sha' not in rec2 and 'row_sha' not in rec3,
          [{k: x.get(k) for k in ('trigger', 'policy', 'row_sha')} for x in (rec2, rec3)])

    print('frozen mismatch')
    bad = pathlib.Path(td) / 'frozen-bad.json'
    fz = json.loads(pathlib.Path(os.environ[W.ENV_FROZEN]).read_text())
    fz['frozen']['ask_match_llm_sha256'] = '0' * 64
    bad.write_text(json.dumps(fz))
    os.environ[W.ENV_FROZEN] = str(bad)
    mk4 = Mock(REPLY_DRIFT)
    rec4 = W.run_job(job, backend=mk4, delay=0, sleep=lambda s: None)
    check('frozen file changed: "skipped: frozen changed", nothing else, no call',
          rec4['status'] == 'skipped' and rec4['reason'] == 'frozen changed' and mk4.calls == 0
          and 'inputs' not in rec4, rec4.get('reason'))
    fz2 = json.loads(pathlib.Path(td, 'frozen.json').read_text())
    fz2['frozen']['prompt_hash']['askllm'] = 'x'
    bad.write_text(json.dumps(fz2))
    rec5 = W.run_job(job, backend=Mock(REPLY_DRIFT), delay=0, sleep=lambda s: None)
    check('prompt hash changed: skipped too', rec5['reason'] == 'frozen changed'
          and rec5.get('frozen_bad') == ['prompt_hash'], rec5.get('frozen_bad'))
    check('frozen-changed skip rows carry trigger and policy', stamped(rec4) and stamped(rec5))
    os.environ[W.ENV_FROZEN] = str(pathlib.Path(td, 'frozen.json'))

    print('exception isolation')
    real = W._with_seen

    def boom(*a, **k):
        raise RuntimeError('disk on fire ' + FAKE_ANT)
    W._with_seen = boom
    try:
        ev = event(main, agent='zz')
        r = W.on_post_tool_use(ev, ev['tool_name'], ev['tool_input'], state)
    except BaseException as e:                               # noqa: BLE001
        r = f'raised {e!r}'
    W._with_seen = real
    errs = [x for x in read_log(state) if x['status'] == 'error']
    check('an exception in the hook side returns "error", never raises', r == 'error', r)
    check('and is logged, redacted', errs and errs[-1]['reason'] == 'hook: RuntimeError'
          and FAKE_ANT not in (state / W.LOG_NAME).read_text())
    check('a hook-side error row (no job built yet) still carries trigger and policy',
          errs and stamped(errs[-1]), errs[-1:])
    real_resolve = W.resolve
    W.resolve = lambda job: (_ for _ in ()).throw(ValueError('bad layout'))
    try:
        rec6 = W.run_job(job, backend=Mock(REPLY_OK), delay=0, sleep=lambda s: None)
    except BaseException as e:                               # noqa: BLE001
        rec6 = {'status': f'raised {e!r}'}
    W.resolve = real_resolve
    check('an exception in the worker is logged as an error line', rec6['status'] == 'error'
          and rec6['reason'] == 'worker: ValueError', rec6)
    check('...with trigger and policy', stamped(rec6), rec6)

print('detached launch')
calls = {}


class _P:
    def __init__(self, argv, **kw):
        calls['argv'], calls['kw'] = argv, kw
        self.stdin = _FakeProc._In()

    def wait(self, *a):
        calls['waited'] = True

    def communicate(self, *a, **k):
        calls['waited'] = True


import subprocess as _sp                                       # noqa: E402
real_popen = _sp.Popen
_sp.Popen = _P
try:
    spec2 = importlib.util.spec_from_file_location('lb_askllm_watch2', str(HOOKS / 'lb_askllm_watch.py'))
    W2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(W2)
    W2._spawn({'state_dir': '/tmp'})
finally:
    _sp.Popen = real_popen
kw = calls.get('kw') or {}
check('worker starts in its own session with stdout and stderr to /dev/null',
      kw.get('start_new_session') is True and kw.get('stdout') == _sp.DEVNULL
      and kw.get('stderr') == _sp.DEVNULL and kw.get('stdin') == _sp.PIPE, kw)
check('the hook never waits on it', not calls.get('waited'))
check('the worker runs isolated (-P) from the hook file', '-P' in calls['argv'] and calls['argv'][-1] == '--worker')


def run_hook(ev, state, home, extra_env):
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env.update(PYTHONPATH=str(PKG), LASERBRAIN_STATE_DIR=str(state), LASERBRAIN_AGENT='claude',
               HOME=str(home), PATH='/usr/bin:/bin')
    env.pop('CLAUDE_CODE_EXECPATH', None)
    env.update(extra_env)
    t0 = time.perf_counter()
    r = subprocess.run([PY, '-P', '-m', 'laserbrain.hooks.lb_coverage'], input=json.dumps(ev), text=True,
                       capture_output=True, env=env, timeout=60)
    return r, (time.perf_counter() - t0) * 1000


def wait_log(state, n=1, secs=20):
    t_end = time.time() + secs
    while time.time() < t_end:
        lg = read_log(state)
        if len(lg) >= n:
            return lg
        time.sleep(0.2)
    return read_log(state)


print('through lb_coverage, as the harness runs it (mock reply, no network)')
with tempfile.TemporaryDirectory() as td:
    td = pathlib.Path(td)
    mock = td / 'reply.json'
    mock.write_text(REPLY_DRIFT)
    frz = frozen_ok(td)
    outs = {}
    for mode in ('off', 'on'):
        state, home = td / f'state-{mode}', td / f'home-{mode}'
        state.mkdir()
        home.mkdir()
        main, ap = make_world(td / f'world-{mode}')
        # Watch mode, the 2026-11-15 behaviour: scoring is silent. In note mode (the default)
        # the Read below may carry the note; test_askllm_notes.py covers that.
        envx = {W.ENV_MOCK: str(mock), W.ENV_DELAY: '0', W.ENV_FROZEN: str(frz), W.ENV_MODE: 'watch',
                W.ENV_POLICY: 'quiet-2026-11-19'}
        if mode == 'off':
            envx[W.ENV_SWITCH] = 'off'
        seq = [event(main), dict(event(main), tool_name='Read', tool_input={'file_path': '/x'},
                                 tool_response={}), event(main, tool_use_id='tu2')]
        res = [run_hook(e, state, home, envx) for e in seq]
        outs[mode] = [(r.returncode, r.stdout, r.stderr) for r, _ in res]
        outs[mode + '_ms'] = res[0][1]
        outs[mode + '_state'] = state
    check('lb_coverage stdout, stderr and exit code are identical with the watch on and off',
          outs['on'] == outs['off'], f"{outs['on']} vs {outs['off']}")
    check('and every call exits 0', all(c == 0 for c, _, _ in outs['on']))
    lg = seen_rows(wait_log(outs['on_state']))
    check('the detached worker wrote exactly one scored line for the agent',
          len(lg) == 1 and lg[0]['status'] == 'scored' and lg[0]['flag'] is True, lg)
    check("LASERBRAIN_POLICY in lb_coverage's environment reaches the detached worker's row, "
          "with trigger and row_sha", lg and stamped(lg[0], 'quiet-2026-11-19') and is_row_sha(lg[0].get('row_sha')),
          lg[:1])
    check('nothing at all was written with the watch off', not read_log(outs['off_state'])
          and not (outs['off_state'] / W.SEEN_NAME).exists())
    print(f"    hook wall time, first check: on {outs['on_ms']:.0f} ms, off {outs['off_ms']:.0f} ms")
    rep_py = EVAL / 'askllm_watch_report.py'
    if rep_py.exists():
        rp = subprocess.run([PY, str(rep_py), '--log', str(outs['on_state'] / W.LOG_NAME)],
                            capture_output=True, text=True, timeout=60)
        rj = subprocess.run([PY, str(rep_py), '--log', str(outs['on_state'] / W.LOG_NAME), '--json'],
                            capture_output=True, text=True, timeout=60)
        try:
            sj = json.loads(rj.stdout)
        except Exception:
            sj = {}
        check('the end-of-week report reads the log: counts, flags and the flagged agent\'s why',
              rp.returncode == 0 and 'flagged 1' in rp.stdout and 'relayed message instead' in rp.stdout
              and sj.get('scored') == 1 and sj.get('flagged') == 1
              and sj.get('per_workflow', {}).get('wf_test-001', {}).get('flagged') == 1,
              rp.stdout[-600:] + rp.stderr[-300:])
        g1 = {'lines': 1, 'scored': 1, 'flagged': 1, 'skipped': 0, 'errors': 0, 'with_row_sha': 1}
        check('the report splits the counts by trigger and by policy',
              sj.get('by_trigger') == {'check_state': g1} and sj.get('by_policy') == {'quiet-2026-11-19': g1}
              and 'by trigger:' in rp.stdout and 'by policy:' in rp.stdout,
              {k: sj.get(k) for k in ('by_trigger', 'by_policy')})
        # A mixed log: the stamped line, a line from before the stamps, a stamped line with no
        # policy set, and a note delivery (not a judge row, so in neither split).
        mixed = td / 'mixed.jsonl'
        legacy = {k: v for k, v in lg[0].items() if k not in ('trigger', 'policy', 'row_sha')}
        unset = dict(lg[0], policy=None, status='skipped', reason='daily cap', flag=None)
        unset.pop('row_sha', None)
        deliv = {'ts': lg[0]['ts'], 'status': 'note_delivered_agent', 'session': 's', 'agent_id': 'a1'}
        mixed.write_text(''.join(json.dumps(x) + '\n' for x in (lg[0], legacy, unset, deliv)))
        rm = subprocess.run([PY, str(rep_py), '--log', str(mixed), '--json'], capture_output=True, text=True,
                            timeout=60)
        try:
            sm = json.loads(rm.stdout)
        except Exception:
            sm = {}
        bp, bt = sm.get('by_policy') or {}, sm.get('by_trigger') or {}
        check("rows without the stamps count as 'unstamped', a null policy as 'none', and note "
              "deliveries are in neither split",
              sorted(bp) == ['none', 'quiet-2026-11-19', 'unstamped'] and bp['unstamped']['scored'] == 1
              and bp['none']['skipped'] == 1 and bp['none']['with_row_sha'] == 0
              and sorted(bt) == ['check_state', 'unstamped'] and bt['check_state']['lines'] == 2
              and sum(g['lines'] for g in bp.values()) == 3 and sm.get('lines') == 4,
              {'by_policy': bp, 'by_trigger': bt, 'err': rm.stderr[-300:]})

    # Detached for real: the worker sleeps 3 s, the hook returns long before the line lands.
    state, home = td / 'state-d', td / 'home-d'
    state.mkdir()
    home.mkdir()
    main, ap = make_world(td / 'world-d')
    t0 = time.time()
    r, ms = run_hook(event(main), state, home, {W.ENV_MOCK: str(mock), W.ENV_DELAY: '3',
                                                W.ENV_FROZEN: str(frz)})
    t_hook = time.time() - t0
    early = read_log(state)
    lg = seen_rows(wait_log(state, 1, 20))
    t_line = time.time() - t0
    check('the hook returns before the worker finishes (detached)',
          r.returncode == 0 and t_hook < 2.5 and not early and lg and t_line >= 3.0,
          f'hook {t_hook:.2f}s line {t_line:.2f}s')

print('off during the wait, and the concurrency cap')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    os.environ[W.ENV_FROZEN] = str(frozen_ok(td))
    main, ap = make_world(td)
    job = {'session': 'lbtest-watch-1', 'agent_id': 'a1', 'agent_type': 'workflow-subagent',
           'lane': 'build:x', 'tool_use_id': 'tu1', 'transcript_path': str(main),
           'goal': 'Build the calendar week bar', 'hook_ts': '2026-11-16T03:02:11+00:00',
           'state_dir': str(state), 'hook_ms': 1.0}

    def off_during(s):                  # the watch is switched off while the worker waits
        state.mkdir(parents=True, exist_ok=True)
        (state / W.OFF_NAME).write_text('')
    mk = Mock(REPLY_DRIFT)
    rec = W.run_job(job, backend=mk, delay=5, sleep=off_during, now=NOW)
    check('a worker already waiting stops when the off file appears, and calls nothing',
          rec['status'] == 'skipped' and 'switched off during wait' in rec['reason'] and mk.calls == 0,
          rec.get('reason'))
    (state / W.OFF_NAME).unlink()

    held = [W.acquire_slot(state, sleep=lambda s: None, wait_s=0) for _ in range(W.MAX_CONCURRENT)]
    check(f'{W.MAX_CONCURRENT} slots can be held at once', all(held))
    check('a further slot is refused while they are held',
          W.acquire_slot(state, sleep=lambda s: None, wait_s=0) is None)
    mk = Mock(REPLY_DRIFT)
    rec = W.run_job(dict(job, agent_id='a1'), backend=mk, delay=0, sleep=lambda s: None, now=NOW)
    check('with every slot busy the worker skips as busy and calls nothing',
          rec['status'] == 'skipped' and rec['reason'].startswith('busy') and mk.calls == 0,
          rec.get('reason'))
    for fh in held:
        fh.close()
    rec = W.run_job(job, backend=Mock(REPLY_DRIFT), delay=0, sleep=lambda s: None, now=NOW)
    check('once a slot frees, the next worker scores', rec['status'] == 'scored', rec.get('reason'))
    check('the slot is released when run_job returns',
          W.acquire_slot(state, sleep=lambda s: None, wait_s=0) is not None)

real_fz = REPO / 'eval' / 'day2-llm-results.json'
if real_fz.exists():
    print('the real frozen block')
    os.environ.pop(W.ENV_FROZEN, None)
    m, why, info = W.load_frozen()
    check('research/eval/ask_match_llm.py still matches eval/day2-llm-results.json', m is not None,
          f'{why} {info.get("bad")}')

print('row stamps over every row this test wrote')
n_rows = len(ROWS)
n_stamped = sum(1 for r in ROWS if r.get('trigger') and 'policy' in r)
scored_rows = [r for r in ROWS if r.get('status') == 'scored']
n_sha = sum(1 for r in scored_rows if is_row_sha(r.get('row_sha')))
by_status = sorted({str(r.get('status')) for r in ROWS})
print(f'    rows written {n_rows} ({", ".join(by_status)}); with trigger and policy {n_stamped}; '
      f'scored {len(scored_rows)}, with row_sha {n_sha}')
check('every row written carries trigger and policy', n_rows > 0 and n_stamped == n_rows,
      [r for r in ROWS if not (r.get('trigger') and 'policy' in r)][:2])
check('every scored row carries a 16-hex row_sha', scored_rows and n_sha == len(scored_rows))
check('the rows include scored, skipped and error lines',
      {'scored', 'skipped', 'error'} <= set(by_status), by_status)

print('  PASS' if ok_all else '  FAIL')
raise SystemExit(0 if ok_all else 1)
