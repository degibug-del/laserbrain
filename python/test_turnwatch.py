"""turnwatch (lb_turnwatch.py + research/eval/turn_match_llm.py), WATCH-ONLY: once per user turn of
the MAIN session, at the first check_state after the user's message reached the model, the frozen
misread judge grades whether the assistant set out to do what the user asked. Nothing reaches the
model or the user.

Checked here, synthetic transcripts only, a mock backend, no network: the trigger fires once per
delivered user message (a prompt or a mid-turn queued_command) and never for a helper agent, a
queued message not yet delivered does not count, the hook side's message rule matches the judge's,
a bare approval's row carries the assistant's previous proposal, the frozen-hash checks skip on any
change (every research/eval file the judge loads is pinned, an unpinned import and a redaction that
no longer redacts are refused, in a fresh interpreter on a scratch copy), secrets are redacted,
lb_coverage's output is byte-identical with turnwatch on and off, a failed first check_state is
judged, the worker reads the transcript backwards in bounded memory and builds the same row, the
bookkeeping files are replaced atomically and a lost seen file cannot reset the cap, a busy lock
never hangs the hook, hook-side errors never load the redactor, the worker's environment allowlist,
the worker is detached, the switches and the daily cap, the dev evaluation's second run and
threshold rule, the report reads the log, and the row stamps: every row carries trigger and
policy (null when LASERBRAIN_POLICY is unset), every row whose prompt was rendered carries row_sha
(the same rule as lb_askllm_watch.row_sha), and the report splits its counts by trigger and policy.

usage: python3 test_turnwatch.py [dir holding the laserbrain package]"""
import datetime
import hashlib
import importlib.util
import shutil
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

for k in [k for k in os.environ if k.startswith('LASERBRAIN_')]:
    os.environ.pop(k)

spec = importlib.util.spec_from_file_location('lb_turnwatch', str(HOOKS / 'lb_turnwatch.py'))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
sys.path.insert(0, str(EVAL))
import turn_match_llm as TM                              # noqa: E402
import extract_starts as ES                              # noqa: E402

ok_all = True


def check(name, cond, detail=''):
    global ok_all
    ok_all &= bool(cond)
    print(f"  {'✓' if cond else '✗'} {name}" + (f'  — {detail}' if detail and not cond else ''))


# Every row this test writes: in process through T._append_log, and the detached workers' rows
# as they are read back (seen_rows). The stamp checks at the end run over all of them.
ROWS = []
_real_append_log = T._append_log


def _recording_append_log(state_dir, rec):
    ROWS.append(json.loads(json.dumps(rec, default=str)))
    return _real_append_log(state_dir, rec)


T._append_log = _recording_append_log


def seen_rows(rows):
    ROWS.extend(rows)
    return rows


def is_row_sha(v):
    return isinstance(v, str) and re.fullmatch(r'[0-9a-f]{16}', v) is not None


def stamped(r, policy=None):
    return r.get('trigger') == 'check_state' and 'policy' in r and r['policy'] == policy


FAKE_GH = 'ghp_' + 'Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2Rr1'                 # an lb_secrets match
SID = 'lbtest-turnwatch-1'
PROPOSAL = ('Three ways to go: (1) add the dark mode toggle, (2) save the choice between visits, '
            'or (3) restyle the header. Which one?')
REPLY_AMBIG = json.dumps({'asks': ['do the approved item'], 'covered': [], 'missing': ['which item'],
                          'substituted': False, 'verdict': 'ambiguous_approval', 'drift_score': 35,
                          'reason': 'A bare ok after three options; the start picked item 3.'})
REPLY_OK = json.dumps({'asks': ['fix the footer typo'], 'covered': ['fix the footer typo'], 'missing': [],
                       'substituted': False, 'verdict': 'aligned', 'drift_score': 5, 'reason': 'Takes it on.'})


def L(**r):
    return json.dumps(r) + '\n'


def u_prompt(ts, text):
    return L(type='user', timestamp=ts, sessionId=SID, message={'role': 'user', 'content': text})


def a_text(ts, text):
    return L(type='assistant', timestamp=ts, sessionId=SID,
             message={'role': 'assistant', 'content': [{'type': 'text', 'text': text}]})


def a_check(ts, tid, goal, doing, text=None):
    c = ([{'type': 'text', 'text': text}] if text else []) + [
        {'type': 'tool_use', 'id': tid, 'name': 'mcp__laserbrain__check_state',
         'input': {'goal': goal, 'progress': 'advancing', 'distance': 6, 'doing': doing}}]
    return L(type='assistant', timestamp=ts, sessionId=SID, message={'role': 'assistant', 'content': c})


def tool_result(ts, tid):
    return L(type='user', timestamp=ts, sessionId=SID, toolUseResult={'ok': True},
             message={'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': tid,
                                                    'content': '{"drifting": false}'}]})


def queued(ts, text):
    return L(type='attachment', timestamp=ts, sessionId=SID,
             attachment={'type': 'queued_command', 'prompt': text, 'commandMode': 'prompt'})


def enqueue(ts, text):
    return L(type='queue-operation', operation='enqueue', timestamp=ts, sessionId=SID, content=text)


def ev_check(main, tid, agent=None, goal='Restyle the header'):
    ev = {'hook_event_name': 'PostToolUse', 'session_id': SID, 'transcript_path': str(main),
          'cwd': '/tmp', 'tool_name': 'mcp__laserbrain__check_state', 'tool_use_id': tid,
          'tool_input': {'goal': goal, 'progress': 'advancing', 'distance': 6},
          'tool_response': json.dumps({'arm': 'sighted', 'drifting': False})}
    if agent:
        ev['agent_id'] = agent
    return ev


PART1 = [u_prompt('2026-11-20T10:00:00.000Z', 'can u add a dark mode to the settings page'),
         a_text('2026-11-20T10:00:30.000Z', PROPOSAL)]
PART2 = [u_prompt('2026-11-20T10:01:00.000Z', 'ok'),
         a_check('2026-11-20T10:01:05.000Z', 'tc1', 'Restyle the header (the user said ok)',
                 f'starting on item 3; key {FAKE_GH}', text='Taking your ok as item 3.'),
         tool_result('2026-11-20T10:01:05.500Z', 'tc1'),
         a_text('2026-11-20T10:01:20.000Z', 'Header restyle is under way.'),
         L(type='user', timestamp='2026-11-20T10:01:21.000Z', sessionId=SID,
           message={'role': 'user', 'content': '<task-notification>a job finished</task-notification>'}),
         a_check('2026-11-20T10:01:30.000Z', 'tc2', 'Restyle the header', 'colours picked'),
         tool_result('2026-11-20T10:01:30.500Z', 'tc2')]
PART3 = [enqueue('2026-11-20T10:02:00.000Z', 'also can u fix the typo in the footer'),
         a_check('2026-11-20T10:02:10.000Z', 'tc3', 'Restyle the header', 'still on the header'),
         tool_result('2026-11-20T10:02:10.500Z', 'tc3')]
PART4 = [queued('2026-11-20T10:02:20.000Z', 'also can u fix the typo in the footer'),
         a_check('2026-11-20T10:02:30.000Z', 'tc4', 'Restyle the header and fix the footer typo',
                 'footer typo next'),
         tool_result('2026-11-20T10:02:30.500Z', 'tc4')]


def write(main, parts):
    with open(main, 'a') as fh:
        for p in parts:
            fh.write(p)


# turn_dev_eval, loaded WITHOUT a sys.modules entry: load_frozen refuses any research/eval module
# in sys.modules that the frozen block does not pin, and the dev script is not part of the judge.
_sd = importlib.util.spec_from_file_location('turn_dev_eval_probe', str(EVAL / 'turn_dev_eval.py'))
DEV = importlib.util.module_from_spec(_sd)
_sd.loader.exec_module(DEV)
JUDGE_FILES = DEV.judge_files()


def frozen_ok(root, eval_dir=EVAL, **over):
    """A frozen block holding the CURRENT judge's values: the mechanics are tested in a checkout
    whatever the real block says. The real block is checked separately below."""
    ed = pathlib.Path(eval_dir)
    files = {n: hashlib.sha256((ed / n).read_bytes()).hexdigest() for n in JUDGE_FILES}
    p = pathlib.Path(root) / 'turn-frozen.json'
    fz = {'model': TM.MODEL, 'prompt_hash': TM.prompt_hash(), 'thresholds': TM.THRESHOLDS,
          'first_words_window_s': TM.FIRST_WORDS_WINDOW_S, 'turn_match_llm_sha256': files['turn_match_llm.py'],
          'ask_match_llm_sha256': files['ask_match_llm.py'], 'eval_files_sha256': files}
    fz.update(over)
    p.write_text(json.dumps({'frozen': fz}))
    return p


def read_log(state):
    p = pathlib.Path(state) / T.LOG_NAME
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


class Mock:
    def __init__(self, text):
        self.text, self.calls, self.prompts, self.systems = text, 0, [], []
        self.name, self.model, self.credential = 'mock', 'mock', None

    def call(self, system, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        self.systems.append(system)
        return {'text': self.text, 'usage': None, 'meta': {'cost_usd': 0.0}}


spawned = []


class _FakeProc:
    class _In:
        def write(self, b):
            self.data = b

        def close(self):
            pass
    stdin = _In()


real_spawn = T._spawn
T._spawn = lambda job: spawned.append(job) or _FakeProc()
NOOP = lambda s: None  # noqa: E731

print('trigger: once per delivered user message, main session only')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    main = pathlib.Path(td) / f'{SID}.jsonl'
    write(main, PART1 + PART2[:3])
    r1 = T.on_post_tool_use(ev_check(main, 'tc1'), 'mcp__laserbrain__check_state', {}, state)
    check('the first check_state after a user message spawns the worker', r1 == 'spawned' and len(spawned) == 1, r1)
    write(main, PART2[3:])
    r2 = T.on_post_tool_use(ev_check(main, 'tc2'), 'mcp__laserbrain__check_state', {}, state)
    check('a second check_state in the same turn does not (a task notification is not the user)',
          r2 == 'same-turn' and len(spawned) == 1, r2)
    write(main, PART3)
    r3 = T.on_post_tool_use(ev_check(main, 'tc3'), 'mcp__laserbrain__check_state', {}, state)
    check('a queued message not yet delivered to the model does not start a turn', r3 == 'same-turn', r3)
    write(main, PART4)
    r4 = T.on_post_tool_use(ev_check(main, 'tc4'), 'mcp__laserbrain__check_state', {}, state)
    check('once it is delivered (queued_command), the next check_state is a new turn',
          r4 == 'spawned' and len(spawned) == 2, r4)
    job = spawned[0]
    check('the job carries session, transcript, tool_use_id, message key and time, state dir',
          job['session'] == SID and job['tool_use_id'] == 'tc1' and job['msg_ts'] == '2026-11-20T10:01:00.000Z'
          and job['msg_key'] == TM.msg_key('ok', '2026-11-20T10:01:00.000Z') and job['state_dir'] == str(state))
    check('the job carries trigger check_state and policy null while LASERBRAIN_POLICY is unset',
          job.get('trigger') == 'check_state' and 'policy' in job and job['policy'] is None, job)
    os.environ[T.ENV_POLICY] = 'quiet-2026-11-19' + 'x' * 40
    rp_ = T.on_post_tool_use(dict(ev_check(main, 'tc4'), session_id='policy-session'),
                             'mcp__laserbrain__check_state', {}, state)
    os.environ.pop(T.ENV_POLICY)
    check('with LASERBRAIN_POLICY set the job carries it, cut to 40 characters',
          rp_ == 'spawned' and spawned[-1].get('policy') == ('quiet-2026-11-19' + 'x' * 40)[:40]
          and spawned[-1].get('trigger') == 'check_state', spawned[-1])
    n0 = len(spawned)
    rh = T.on_post_tool_use(ev_check(main, 'tc9', agent='a1'), 'mcp__laserbrain__check_state', {}, state)
    check('a helper agent (payload names an agent_id) is never judged', rh == 'helper' and len(spawned) == n0, rh)
    rb = T.on_post_tool_use(dict(ev_check(main, 'tc9'), tool_name='Bash'), 'Bash', {}, state)
    check('a call that is not check_state does nothing', rb == 'not-check')
    rn = T.on_post_tool_use(dict(ev_check(main, 'tc9'), transcript_path='/nonexistent/x.jsonl'),
                            'mcp__laserbrain__check_state', {}, state)
    check('no transcript on disk: nothing spawned', rn == 'no-transcript')
    empty = pathlib.Path(td) / 'empty.jsonl'
    empty.write_text(a_text('2026-11-20T10:00:00.000Z', 'hello'))
    check('no user message in the transcript: nothing spawned',
          T.on_post_tool_use(dict(ev_check(empty, 'x'), session_id='other'), 'mcp__laserbrain__check_state',
                             {}, state) == 'no-user-message')
    os.environ[T.ENV_EVAL] = str(pathlib.Path(td) / 'no-research-here')
    n0 = len(spawned)
    rj = T.on_post_tool_use(dict(ev_check(main, 'tc9'), session_id='wheel'), 'mcp__laserbrain__check_state',
                            {}, state)
    os.environ.pop(T.ENV_EVAL)
    check('an installed package (no research/eval) spawns nothing at all', rj == 'no-judge'
          and len(spawned) == n0, rj)

    print('the hook side reads messages the way the judge does')
    lines = main.read_text().splitlines()
    ev = TM.parse_records(lines)
    users = [e for e in ev if e['k'] == 'user']
    found = T.latest_user_message(str(main))
    check('latest delivered message: the same for the hook scan and parse_records',
          found == (users[-1]['ts'], users[-1]['text']) and users[-1]['via'] == 'queued', f'{found} {users[-1:]}')
    check('the same message key', T.msg_key(found[1], found[0]) == TM.msg_key(users[-1]['text'], users[-1]['ts']))
    check("the hook's skip list is extract_starts._SKIP_PREFIX", T._SKIP_PREFIX == ES._SKIP_PREFIX)
    check('a tool result, a task notification and an enqueue are never user messages',
          [u['text'] for u in users] == ['can u add a dark mode to the settings page', 'ok',
                                         'also can u fix the typo in the footer'], [u['text'] for u in users])
    big = pathlib.Path(td) / 'big.jsonl'
    write(big, PART1 + PART2[:1])
    with open(big, 'a') as fh:
        for i in range(300):
            fh.write(tool_result(f'2026-11-20T10:05:{i % 60:02d}.000Z', f'x{i}').replace(
                '"{\\"drifting\\": false}"', json.dumps('y' * 3000)))
    t0 = time.perf_counter()
    for _ in range(20):
        fb = T.latest_user_message(str(big))
    ms = (time.perf_counter() - t0) * 1000 / 20
    check('a message 1 MB back is found (the scan widens to 4 MB)',
          fb and fb[1] == 'ok' and big.stat().st_size > 900_000, f'{fb} {big.stat().st_size}')
    print(f'    hook-side scan over a ~1 MB tail: {ms:.1f} ms')
    check('...and the scan stays cheap (< 50 ms)', ms < 50, f'{ms:.1f} ms')

print('switches and the daily cap')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    main = pathlib.Path(td) / f'{SID}.jsonl'
    write(main, PART1 + PART2[:3])
    os.environ[T.ENV_SWITCH] = 'off'
    n0 = len(spawned)
    r = T.on_post_tool_use(ev_check(main, 'tc1'), 'mcp__laserbrain__check_state', {}, state)
    check('LASERBRAIN_TURNWATCH=off: nothing spawned, nothing written',
          r == 'off' and len(spawned) == n0 and not (state / T.SEEN_NAME).exists(), r)
    os.environ.pop(T.ENV_SWITCH)
    state.mkdir(parents=True, exist_ok=True)
    (state / T.OFF_NAME).write_text('')
    check('the turnwatch.off file switches it off', T.on_post_tool_use(
        ev_check(main, 'tc1'), 'mcp__laserbrain__check_state', {}, state) == 'off')
    check('the worker stands down under the file switch too',
          T.run_job({'state_dir': str(state), 'session': SID}, backend=Mock(REPLY_OK), delay=0) is None)
    (state / T.OFF_NAME).unlink()
    day = datetime.date.today().isoformat()
    (state / T.CALLS_NAME).write_text(json.dumps({'calls': {day: T.DAILY_CAP}}))
    r = T.on_post_tool_use(ev_check(main, 'tc1'), 'mcp__laserbrain__check_state', {}, state)
    lg = read_log(state)
    check('at the daily cap: nothing spawned, one skip line', r == 'cap' and len(spawned) == n0
          and len(lg) == 1 and lg[0]['reason'] == 'daily cap', r)
    check('the hook-side cap skip row carries trigger and policy (null: unset)',
          lg and stamped(lg[0]) and 'row_sha' not in lg[0], lg[:1])
    check('the cap is 80 calls a day, counted apart from askllm', T.DAILY_CAP == 80
          and T.SEEN_NAME != 'askllm-watch.seen.json' and T.reserve_call(state) is False)
    (state / T.SEEN_NAME).write_text('{"last": {"half a fi')          # a writer killed mid-write
    check('a lost or corrupt seen file cannot reset the daily count (its own file)',
          T.calls_today(state) == T.DAILY_CAP and T.reserve_call(state) is False)

print('bookkeeping: atomic, bounded, never a hang')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    def _mark(i):
        def fn(d):
            d['last'][f's{i}'] = {'key': 'k', 'ts': f'2026-11-20T{i:06d}'}
            return None, ('last',)
        return fn
    for i in range(T.KEEP_SESSIONS + 50):
        T._with_seen(state, _mark(i))
    d = json.loads((state / T.SEEN_NAME).read_text())
    check(f'the seen file keeps the latest {T.KEEP_SESSIONS} sessions', len(d['last']) == T.KEEP_SESSIONS
          and f's{T.KEEP_SESSIONS + 49}' in d['last'] and 's0' not in d['last'], len(d['last']))
    check('the seen file holds no daily count any more', 'calls' not in d)
    check('no temp file is left behind', not [n for n in os.listdir(state) if n.endswith('.tmp')])
    m0 = (state / T.SEEN_NAME).stat().st_mtime_ns
    time.sleep(0.01)
    T._with_seen(state, lambda d: (None, ()))
    check('a pass that changes nothing writes nothing', (state / T.SEEN_NAME).stat().st_mtime_ns == m0)
    import fcntl
    hold = open(state / T.LOCK_NAME, 'a')
    fcntl.flock(hold, fcntl.LOCK_EX)
    old_wait, T.LOCK_WAIT_S = T.LOCK_WAIT_S, 0.2
    main = pathlib.Path(td) / f'{SID}.jsonl'
    write(main, PART1 + PART2[:3])
    t0 = time.perf_counter()
    rr = T.on_post_tool_use(ev_check(main, 'tc1'), 'mcp__laserbrain__check_state', {}, state)
    waited = time.perf_counter() - t0
    T.LOCK_WAIT_S = old_wait
    hold.close()
    check('a held lock costs the hook a bounded wait and one error line, never a hang',
          rr == 'error' and waited < 1.5 and read_log(state)[-1]['reason'] == 'hook: TimeoutError', f'{rr} {waited:.2f}s')

print('worker (mock backend, in process)')
with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / 'state'
    os.environ[T.ENV_FROZEN] = str(frozen_ok(td))
    main = pathlib.Path(td) / f'{SID}.jsonl'
    write(main, PART1 + PART2)
    job = {'session': SID, 'transcript_path': str(main), 'tool_use_id': 'tc1', 'lane': None,
           'msg_key': TM.msg_key('ok', '2026-11-20T10:01:00.000Z'), 'msg_ts': '2026-11-20T10:01:00.000Z',
           'hook_ts': '2026-11-20T10:01:06+00:00', 'hook_epoch': time.time(), 'state_dir': str(state),
           'hook_ms': 2.0}
    mk = Mock(REPLY_AMBIG)
    rec = T.run_job(job, backend=mk, delay=0, sleep=NOOP)
    check('scored once with the frozen judge', rec['status'] == 'scored' and mk.calls == 1, rec.get('reason') or rec)
    check('a bare "ok" is a bare approval, and ambiguous_approval on it is a flag',
          rec['bare_approval'] is True and rec['flag'] is True and rec['verdict'] == 'ambiguous_approval'
          and rec['by'] == ['ambiguous_approval'], rec)
    pr = mk.prompts[0] if mk.prompts else ''
    check("the bare approval's prompt carries the assistant's previous proposal and the approval note",
          PROPOSAL in pr and TM.APPROVAL_NOTE in pr and 'NEW MESSAGE' in pr, pr[:600])
    check('the prompt carries the earlier message, the goal, the doing note and the first words',
          'can u add a dark mode to the settings page' in pr and 'GOAL: Restyle the header (the user said ok)' in pr
          and 'NOTE: starting on item 3' in pr and 'Taking your ok as item 3.' in pr)
    check('the first words stop at the next user message', 'a job finished' not in pr)
    check('secrets never reach the model', FAKE_GH not in pr and '[redacted:' in pr)
    raw = (state / T.LOG_NAME).read_text()
    check('secrets never reach the log', FAKE_GH not in raw)
    check('the log line has inputs, model, frozen sha, prompt hash, latency, cost',
          rec['inputs'] == {'user_recent': 1, 'proposal': True, 'goal': True, 'doing': True, 'first_text': True}
          and rec['model'] == TM.MODEL and rec['frozen_sha'] == TM.file_sha()
          and rec['prompt_hash'] == TM.prompt_hash() and 'call_s' in rec and rec['cost_usd'] == 0.0
          and rec['key_matches_hook'] is True, rec)
    sys_ = mk.systems[0] if mk.systems else ''
    want_sha = hashlib.sha256(f'{sys_}\n{pr}'.encode('utf-8')).hexdigest()[:16]
    check('the scored row carries trigger check_state, policy null (unset) and row_sha',
          stamped(rec) and is_row_sha(rec.get('row_sha')), {k: rec.get(k) for k in ('trigger', 'policy', 'row_sha')})
    check('row_sha is sha256(system + newline + prompt) of exactly what the model was sent, 16 hex',
          rec.get('row_sha') == want_sha == T.row_sha(sys_, pr), f"{rec.get('row_sha')} vs {want_sha}")
    W_ = T._askllm_module()
    check("turnwatch's row_sha rule is askllm's (one rule for both judges' rows)",
          all(T.row_sha(a, b) == W_.row_sha(a, b) for a, b in (('', ''), ('sys', 'prompt'), ('s\nt', 'é ✓'),
                                                                ('s', 'a\ud800b'))))
    rec_same = T.run_job(dict(job), state_dir=pathlib.Path(td) / 'state-same', backend=Mock(REPLY_OK), delay=0,
                         sleep=NOOP)
    check('the same row rendered again gives the same row_sha (a different reply does not matter)',
          rec_same['status'] == 'scored' and rec_same.get('row_sha') == rec.get('row_sha'), rec_same.get('reason'))
    rec_pol = T.run_job(dict(job, policy='quiet-2026-11-19', trigger='check_state'),
                        state_dir=pathlib.Path(td) / 'state-pol', backend=Mock(REPLY_OK), delay=0, sleep=NOOP)
    check("a job's policy reaches its row", rec_pol['status'] == 'scored'
          and stamped(rec_pol, 'quiet-2026-11-19') and is_row_sha(rec_pol.get('row_sha')), rec_pol.get('policy'))
    check('the call counted against the cap', T.calls_today(state) == 1)
    mk2 = Mock(REPLY_OK)
    rec2 = T.run_job(dict(job, tool_use_id='tc1'), backend=mk2, delay=0, sleep=NOOP)
    check('the same user message is never judged twice (worker side too)',
          rec2['status'] == 'skipped' and 'already judged' in rec2['reason'] and mk2.calls == 0, rec2.get('reason'))
    mk2b = Mock(REPLY_OK)
    rec2b = T.run_job(dict(job, tool_use_id='tc2', session='fresh-second-check'), backend=mk2b, delay=0,
                      sleep=NOOP)
    check('a later check_state in the turn is never the one judged (only the first after the message)',
          rec2b['status'] == 'skipped' and rec2b['reason'] == 'not the first check_state after the message'
          and mk2b.calls == 0, rec2b.get('reason'))
    rec3 = T.run_job(dict(job, tool_use_id='nope'), backend=Mock(REPLY_OK), delay=0, sleep=NOOP)
    check('a check_state missing from the transcript: skipped, logged',
          rec3['reason'] == 'check_state not in transcript')
    check('skipped rows (already judged, not first, not found) carry trigger and policy, no row_sha',
          all(stamped(x) and 'row_sha' not in x for x in (rec2, rec2b, rec3)),
          [{k: x.get(k) for k in ('trigger', 'policy', 'row_sha')} for x in (rec2, rec2b, rec3)])
    write(main, PART3 + PART4)
    mk4 = Mock(REPLY_OK)
    rec4 = T.run_job(dict(job, tool_use_id='tc4'), backend=mk4, delay=0, sleep=NOOP)
    check('the delivered queued message is its own turn: not a bare approval, not flagged',
          rec4['status'] == 'scored' and rec4['bare_approval'] is False and rec4['flag'] is False
          and rec4['msg_via'] == 'queued' and 'also can u fix the typo in the footer' in mk4.prompts[0])
    check("its prompt carries the assistant's last text before it as the proposal",
          'Header restyle is under way.' in mk4.prompts[0])
    check('watch-only: the worker writes nothing but its log and its bookkeeping',
          set(p.name for p in state.iterdir()) <= {T.LOG_NAME, T.SEEN_NAME, T.CALLS_NAME, T.LOCK_NAME} | {
              f'askllm-watch.slot{i}.lock' for i in range(4)}, sorted(p.name for p in state.iterdir()))

    print('bare approvals')
    for msg, want in (('ok', True), ('yes', True), ('Go ahead!', True), ('sure, do it', True),
                      ('continue', True), ('ok do the first one', False), ('yes but only the header', False),
                      ('make it blue', False), ('', False)):
        check(f'is_bare_approval({msg!r}) is {want}', TM.is_bare_approval(msg) is want)

    print('frozen mismatch')
    bad = pathlib.Path(td) / 'bad.json'
    good = json.loads(pathlib.Path(os.environ[T.ENV_FROZEN]).read_text())
    for field, val, want in (('turn_match_llm_sha256', '0' * 64, ['turn_match_llm_sha256']),
                             ('ask_match_llm_sha256', '0' * 64, ['ask_match_llm_sha256']),
                             ('prompt_hash', 'x', ['prompt_hash']),
                             ('thresholds', {'min_drift_score': 1}, ['thresholds']),
                             ('model', 'some-other-model', ['model'])):
        fz = json.loads(json.dumps(good))
        fz['frozen'][field] = val
        bad.write_text(json.dumps(fz))
        os.environ[T.ENV_FROZEN] = str(bad)
        mkb = Mock(REPLY_AMBIG)
        rb = T.run_job(dict(job, session='fresh-' + field), backend=mkb, delay=0, sleep=NOOP)
        check(f'{field} changed: "skipped: frozen changed", no call',
              rb['status'] == 'skipped' and rb['reason'] == 'frozen changed' and mkb.calls == 0
              and rb.get('frozen_bad', [None])[0] == want[0] and 'inputs' not in rb
              and stamped(rb) and 'row_sha' not in rb, rb)
    for name in ('_common.py', 'extract_starts.py', 'ask_match.py'):
        fz = json.loads(json.dumps(good))
        fz['frozen']['eval_files_sha256'][name] = '0' * 64
        bad.write_text(json.dumps(fz))
        os.environ[T.ENV_FROZEN] = str(bad)
        mkb = Mock(REPLY_AMBIG)
        rb = T.run_job(dict(job, session='fresh-dep-' + name), backend=mkb, delay=0, sleep=NOOP)
        check(f'{name} (a helper the judge imports) changed: skipped, no call',
              rb['reason'] == 'frozen changed' and mkb.calls == 0
              and rb.get('frozen_bad') == [f'eval_files_sha256:{name}'], rb.get('frozen_bad'))
    fz = json.loads(json.dumps(good))
    fz['frozen'].pop('eval_files_sha256')
    bad.write_text(json.dumps(fz))
    os.environ[T.ENV_FROZEN] = str(bad)
    rb = T.run_job(dict(job, session='fresh-nomap'), backend=Mock(REPLY_OK), delay=0, sleep=NOOP)
    check('a frozen block without the file list: skipped', rb['reason'] == 'frozen changed'
          and rb.get('frozen_bad') == ['eval_files_sha256'], rb.get('frozen_bad'))
    check('the judge loads exactly these research/eval files',
          sorted(JUDGE_FILES) == ['_common.py', 'ask_match.py', 'ask_match_llm.py', 'extract_starts.py',
                                  'turn_match_llm.py'], sorted(JUDGE_FILES))
    os.environ[T.ENV_FROZEN] = str(pathlib.Path(td) / 'missing.json')
    rb = T.run_job(dict(job, session='fresh-x'), backend=Mock(REPLY_OK), delay=0, sleep=NOOP)
    check('no frozen block: skipped', rb['status'] == 'skipped' and rb['reason'] == 'frozen block unreadable')
    os.environ[T.ENV_FROZEN] = str(frozen_ok(td))

    print('exception isolation')
    real_ws = T._with_seen
    T._with_seen = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('disk on fire ' + FAKE_GH))
    try:
        r = T.on_post_tool_use(ev_check(main, 'tc4'), 'mcp__laserbrain__check_state', {}, state)
    except BaseException as e:                               # noqa: BLE001
        r = f'raised {e!r}'
    T._with_seen = real_ws
    check('an exception on the hook side returns "error", never raises', r == 'error', r)
    check('...and is logged by type only, no text', FAKE_GH not in (state / T.LOG_NAME).read_text()
          and read_log(state)[-1]['reason'] == 'hook: RuntimeError' and read_log(state)[-1].get('error') is None)
    check('a hook-side error row (no job built yet) still carries trigger and policy',
          stamped(read_log(state)[-1]), read_log(state)[-1:])
    T._REDACT = None
    path0 = list(sys.path)
    T._with_seen = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('again'))
    T.on_post_tool_use(dict(ev_check(main, 'tc4'), session_id='other-err'), 'mcp__laserbrain__check_state', {}, state)
    T._with_seen = real_ws
    check("...and never loads the redactor or touches lb_coverage's sys.path",
          T._REDACT is None and sys.path == path0)
    real_rb = T.read_events
    T.read_events = lambda m, p, *a, **k: (_ for _ in ()).throw(ValueError('bad layout'))
    try:
        rw = T.run_job(dict(job, session='fresh-y'), backend=Mock(REPLY_OK), delay=0, sleep=NOOP)
    except BaseException as e:                               # noqa: BLE001
        rw = {'status': f'raised {e!r}'}
    T.read_events = real_rb
    check('an exception in the worker is one error line', rw['status'] == 'error'
          and rw['reason'] == 'worker: ValueError', rw)
    check('...with trigger and policy', stamped(rw), rw)

    print('reading the transcript backwards')
    big = pathlib.Path(td) / 'long.jsonl'
    write(big, PART1 + PART2[:1])
    with open(big, 'a') as fh:
        for i in range(120):
            fh.write(tool_result(f'2026-11-20T10:01:0{i % 5}.000Z', f'x{i}').replace(
                '"{\\"drifting\\": false}"', json.dumps('y' * 9000)))
    write(big, PART2[1:])
    full = TM.parse_records(big.read_text().split('\n'))
    fc = T.find_check(full, 'tc1')
    m_tm = T.load_frozen()[0]
    for blk in (4096, 65536, 1 << 20):
        ev_b = T.read_events(m_tm, str(big), 'tc1', block=blk)
        cb = T.find_check(ev_b, 'tc1')
        same = cb is not None and TM.build_row(ev_b, cb, SID) == TM.build_row(full, fc, SID)
        check(f'a {blk}-byte block reader builds the same row as parsing the whole file', same)
    ev_cap = T.read_events(m_tm, str(big), 'tc1', max_bytes=200_000, block=4096)
    check('it stops at max_bytes (the head of a long transcript is never read)',
          not [e for e in ev_cap if e['k'] == 'user' and 'dark mode' in e['text']]
          and T.find_check(ev_cap, 'tc1') is not None)

T._spawn = real_spawn

print('the worker in a fresh interpreter: memory, frozen copies, environment')
PROBE = '''
import importlib.util as u, json, os, pathlib, resource, sys
sp = u.spec_from_file_location("lb_turnwatch", sys.argv[1]); T = u.module_from_spec(sp); sp.loader.exec_module(T)
cmd = sys.argv[2]
if cmd == "frozen":
    m, why, info = T.load_frozen()
    print(json.dumps({"loaded": m is not None, "why": why, "bad": info.get("bad")}))
elif cmd == "tail":
    m = T.load_frozen()[0]
    r0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    ev = T.read_events(m, sys.argv[3], "tcX")
    r1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    k = 1 if sys.platform == "darwin" else 1024
    print(json.dumps({"rss0_mb": r0 * k / 1e6, "rss1_mb": r1 * k / 1e6, "users": sum(e["k"] == "user" for e in ev),
                      "found": T.find_check(ev, "tcX") is not None}))
elif cmd == "env":
    m = T.load_frozen()[0]
    w = T._askllm_module()
    m.aml.keychain = lambda name: None
    b = T.make_backend(m, sys.argv[3], w)
    print(json.dumps({"env": sorted(b.env()), "name": b.name}))
'''


def probe(cmd, *args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env.update(env_extra or {})
    r = subprocess.run([PY, '-P', '-c', PROBE, str(HOOKS / 'lb_turnwatch.py'), cmd, *map(str, args)],
                       capture_output=True, text=True, env=env, timeout=120)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {'error': (r.stdout + r.stderr)[-600:]}


with tempfile.TemporaryDirectory() as td:
    td = pathlib.Path(td)
    huge = td / 'huge.jsonl'
    with open(huge, 'w') as fh:
        for p_ in PART1 + PART2[:1]:
            fh.write(p_)
        filler = tool_result('2026-11-20T10:02:00.000Z', 'f').replace('"{\\"drifting\\": false}"',
                                                                      json.dumps('z' * 100_000))
        for _ in range(400):                                         # ~40 MB of tool results
            fh.write(filler)
        fh.write(a_check('2026-11-20T10:03:00.000Z', 'tcX', 'Restyle the header', 'still going'))
    tp = probe('tail', huge)
    print(f"    read_events on {huge.stat().st_size / 1e6:.0f} MB with the message at the head: "
          f"peak RSS {tp.get('rss0_mb', 0):.0f} -> {tp.get('rss1_mb', 0):.0f} MB")
    check('the worker reads a long tool-heavy tail in bounded memory (< 100 MB over its start)',
          tp.get('found') and tp.get('users') == 2 and tp['rss1_mb'] - tp['rss0_mb'] < 100, tp)

    # A scratch copy of the judge (research/eval + lb_secrets), loaded in a fresh interpreter as
    # the live worker loads it: each edit the review found unpinned must now be refused.
    def judge_copy(name):
        root = td / name
        (root / 'research' / 'eval').mkdir(parents=True)
        (root / 'python' / 'laserbrain' / 'hooks').mkdir(parents=True)
        for n in JUDGE_FILES:
            shutil.copy2(EVAL / n, root / 'research' / 'eval' / n)
        shutil.copy2(HOOKS / 'lb_secrets.py', root / 'python' / 'laserbrain' / 'hooks' / 'lb_secrets.py')
        return root / 'research' / 'eval'
    real_frz = frozen_ok(td)                       # the CURRENT files' hashes, as a real freeze holds
    cases = {}
    ed = judge_copy('same')
    cases['same'] = probe('frozen', env_extra={T.ENV_EVAL: str(ed), T.ENV_FROZEN: str(real_frz)})
    ed = judge_copy('common')
    src = (ed / '_common.py').read_text()
    (ed / '_common.py').write_text(src.replace('def redact(', 'def redact(text, limit=None):\n    return text\n\n\ndef _old_redact(', 1))
    cases['common'] = probe('frozen', env_extra={T.ENV_EVAL: str(ed), T.ENV_FROZEN: str(real_frz)})
    ed = judge_copy('skip')
    src = (ed / 'extract_starts.py').read_text()
    (ed / 'extract_starts.py').write_text(src.replace("_SKIP_PREFIX = (", "_SKIP_PREFIX = ('zz-new', ", 1))
    cases['skip'] = probe('frozen', env_extra={T.ENV_EVAL: str(ed), T.ENV_FROZEN: str(real_frz)})
    ed = judge_copy('unpinned')
    part = json.loads(real_frz.read_text())
    part['frozen']['eval_files_sha256'].pop('extract_starts.py')
    up = td / 'unpinned.json'
    up.write_text(json.dumps(part))
    cases['unpinned'] = probe('frozen', env_extra={T.ENV_EVAL: str(ed), T.ENV_FROZEN: str(up)})
    ed = judge_copy('secrets')
    sec = ed.parent.parent / 'python' / 'laserbrain' / 'hooks' / 'lb_secrets.py'
    sec.write_text(sec.read_text() + '\nCOMPILED = []\n')
    cases['secrets'] = probe('frozen', env_extra={T.ENV_EVAL: str(ed), T.ENV_FROZEN: str(real_frz)})
    check('an unchanged copy of the judge loads', cases['same'].get('loaded') is True, cases['same'])
    check('_common.redact replaced by "return text": refused before it runs',
          cases['common'].get('loaded') is False and 'eval_files_sha256:_common.py' in (cases['common'].get('bad') or []),
          cases['common'])
    check('a new extract_starts._SKIP_PREFIX entry: refused',
          cases['skip'].get('loaded') is False and 'eval_files_sha256:extract_starts.py' in (cases['skip'].get('bad') or []),
          cases['skip'])
    check('a research/eval module the frozen block does not pin: refused after loading',
          cases['unpinned'].get('loaded') is False and 'unpinned:extract_starts.py' in (cases['unpinned'].get('bad') or []),
          cases['unpinned'])
    check('redaction patterns emptied outside research/eval (lb_secrets): the canary refuses it',
          cases['secrets'].get('loaded') is False and 'redaction' in (cases['secrets'].get('bad') or []),
          cases['secrets'])

    fake_bin = td / 'bin'
    fake_bin.mkdir()
    (fake_bin / 'claude').write_text('#!/bin/sh\nexit 1\n')
    (fake_bin / 'claude').chmod(0o755)
    host = {T.ENV_FROZEN: str(real_frz), 'PATH': f"{fake_bin}:/usr/bin:/bin", 'CLAUDE_EFFORT': 'high',
            'CLAUDE_CODE_SIMPLE': '1', 'ANTHROPIC_BASE_URL': 'https://example.invalid',
            'CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH': '1', 'CLAUDE_CODE_SESSION_ID': 'host-session',
            'CLAUDE_AGENT_SDK_VERSION': '1'}
    pe = probe('env', td / 'state', env_extra=host)
    w_keep = set(T._askllm_module().CHILD_ENV_KEEP)
    envk = pe.get('env') or []
    check("the `claude -p` child gets only the allowlist: no host effort, simple-mode, SDK, base-URL "
          "or session variables", pe.get('name') == 'claude' and envk and 'PATH' in envk
          and all(k in w_keep or k.startswith(('LC_', 'LASERBRAIN_')) for k in envk), pe)

print('detached launch')
calls = {}


class _P:
    def __init__(self, argv, **kw):
        calls['argv'], calls['kw'] = argv, kw
        self.stdin = _FakeProc._In()

    def wait(self, *a):
        calls['waited'] = True


_real_popen = subprocess.Popen
subprocess.Popen = _P
try:
    T._spawn({'state_dir': '/tmp'})
finally:
    subprocess.Popen = _real_popen
kw = calls.get('kw') or {}
check('worker starts in its own session with stdout and stderr to /dev/null',
      kw.get('start_new_session') is True and kw.get('stdout') == subprocess.DEVNULL
      and kw.get('stderr') == subprocess.DEVNULL and kw.get('stdin') == subprocess.PIPE, kw)
check('the hook never waits on it; the worker runs isolated (-P)', not calls.get('waited')
      and '-P' in calls['argv'] and calls['argv'][-1] == '--worker')


def run_hook(ev, state, home, extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env.update(PYTHONPATH=str(PKG), LASERBRAIN_STATE_DIR=str(state), LASERBRAIN_AGENT='claude',
               HOME=str(home), PATH='/usr/bin:/bin', LASERBRAIN_TURNS_HARVEST='0')
    env.pop('CLAUDE_CODE_EXECPATH', None)
    env.update(extra)
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


print('through lb_coverage, as the harness runs it: watch-only')
with tempfile.TemporaryDirectory() as td:
    td = pathlib.Path(td)
    mock = td / 'reply.json'
    mock.write_text(REPLY_AMBIG)
    frz = frozen_ok(td)
    outs = {}
    for mode in ('off', 'on'):
        state, home = td / f'state-{mode}', td / f'home-{mode}'
        state.mkdir()
        home.mkdir()
        main = td / f'world-{mode}' / f'{SID}.jsonl'
        main.parent.mkdir()
        write(main, PART1 + PART2)
        envx = {T.ENV_MOCK: str(mock), T.ENV_DELAY: '0', T.ENV_FROZEN: str(frz),
                T.ENV_POLICY: 'quiet-2026-11-19'}
        if mode == 'off':
            envx[T.ENV_SWITCH] = 'off'
        seq = [ev_check(main, 'tc1'),
               dict(ev_check(main, 'r1'), tool_name='Read', tool_input={'file_path': '/x'}, tool_response={}),
               ev_check(main, 'tc2')]
        res = [run_hook(e, state, home, envx) for e in seq]
        outs[mode] = [(r.returncode, r.stdout, r.stderr) for r, _ in res]
        outs[mode + '_ms'] = res[0][1]
        outs[mode + '_state'] = state
    check('lb_coverage stdout, stderr and exit codes are identical with turnwatch on and off',
          outs['on'] == outs['off'], f"{outs['on']} vs {outs['off']}")
    check('and every call exits 0', all(c == 0 for c, _, _ in outs['on']))
    lg = seen_rows(wait_log(outs['on_state']))
    check('the detached worker wrote exactly one scored line for the turn',
          len(lg) == 1 and lg[0]['status'] == 'scored' and lg[0]['flag'] is True, lg)
    check("LASERBRAIN_POLICY in lb_coverage's environment reaches the detached worker's row, "
          "with trigger and row_sha", lg and stamped(lg[0], 'quiet-2026-11-19') and is_row_sha(lg[0].get('row_sha')),
          lg[:1])
    check('nothing at all was written with turnwatch off', not read_log(outs['off_state'])
          and not (outs['off_state'] / T.SEEN_NAME).exists())
    print(f"    hook wall time, first check: on {outs['on_ms']:.0f} ms, off {outs['off_ms']:.0f} ms")
    check('turnwatch adds little to the hook (< 150 ms)', outs['on_ms'] - outs['off_ms'] < 150,
          f"{outs['on_ms']:.0f} vs {outs['off_ms']:.0f}")
    state_f, home_f = td / 'state-fail', td / 'home-fail'
    state_f.mkdir()
    home_f.mkdir()
    main_f = td / 'world-fail' / f'{SID}.jsonl'
    main_f.parent.mkdir()
    write(main_f, PART1 + PART2[:2])
    envf = {T.ENV_MOCK: str(mock), T.ENV_DELAY: '0', T.ENV_FROZEN: str(frz)}
    evf = dict(ev_check(main_f, 'tc1'), hook_event_name='PostToolUseFailure', error='MCP error: timed out')
    evf.pop('tool_response')
    rf, _ = run_hook(evf, state_f, home_f, envf)
    write(main_f, PART2[2:])
    rf2, _ = run_hook(ev_check(main_f, 'tc2'), state_f, home_f, envf)
    lgf = seen_rows(wait_log(state_f))
    check('a FAILED first check_state (PostToolUseFailure) is judged, as the dev set counts it; the next '
          'check of that turn is not', rf.returncode == 0 and len(lgf) == 1 and lgf[0]['status'] == 'scored'
          and lgf[0]['tool_use_id'] == 'tc1', lgf)
    evh = dict(evf, agent_id='helper-1', session_id='helper-fail')
    rh, _ = run_hook(evh, state_f, home_f, envf)
    time.sleep(0.5)
    check("a helper's failed check_state starts nothing (turnwatch is main-only, askllm stays on success)",
          rh.returncode == 0 and len(read_log(state_f)) == 1)
    rep = EVAL / 'turnwatch_report.py'
    if rep.exists():
        rp = subprocess.run([PY, str(rep), '--log', str(outs['on_state'] / T.LOG_NAME)],
                            capture_output=True, text=True, timeout=60)
        rj = subprocess.run([PY, str(rep), '--log', str(outs['on_state'] / T.LOG_NAME), '--json'],
                            capture_output=True, text=True, timeout=60)
        try:
            sj = json.loads(rj.stdout)
        except Exception:
            sj = {}
        check('the report reads the log: counts, flags, the per-day table',
              rp.returncode == 0 and 'flagged 1' in rp.stdout and 'per day' in rp.stdout
              and sj.get('scored') == 1 and sj.get('flagged') == 1 and len(sj.get('per_day') or {}) == 1,
              rp.stdout[-600:] + rp.stderr[-300:])
        g1 = {'lines': 1, 'scored': 1, 'flagged': 1, 'skipped': 0, 'errors': 0, 'with_row_sha': 1}
        check('the report splits the counts by trigger and by policy',
              sj.get('by_trigger') == {'check_state': g1} and sj.get('by_policy') == {'quiet-2026-11-19': g1}
              and 'by trigger:' in rp.stdout and 'by policy:' in rp.stdout,
              {k: sj.get(k) for k in ('by_trigger', 'by_policy')})
        # A mixed log: the stamped line, a line from before the stamps, a stamped line with no
        # policy set.
        mixed = td / 'mixed.jsonl'
        legacy = {k: v for k, v in lg[0].items() if k not in ('trigger', 'policy', 'row_sha')}
        unset = dict(lg[0], policy=None, status='skipped', reason='daily cap', flag=None)
        unset.pop('row_sha', None)
        mixed.write_text(''.join(json.dumps(x) + '\n' for x in (lg[0], legacy, unset)))
        rm = subprocess.run([PY, str(rep), '--log', str(mixed), '--json'], capture_output=True, text=True,
                            timeout=60)
        try:
            sm = json.loads(rm.stdout)
        except Exception:
            sm = {}
        bp, bt = sm.get('by_policy') or {}, sm.get('by_trigger') or {}
        check("rows without the stamps count as 'unstamped' and a null policy as 'none'",
              sorted(bp) == ['none', 'quiet-2026-11-19', 'unstamped'] and bp['unstamped']['scored'] == 1
              and bp['none']['skipped'] == 1 and bp['none']['with_row_sha'] == 0
              and sorted(bt) == ['check_state', 'unstamped'] and bt['check_state']['lines'] == 2
              and sum(g['lines'] for g in bp.values()) == 3,
              {'by_policy': bp, 'by_trigger': bt, 'err': rm.stderr[-300:]})
    else:
        check('research/eval/turnwatch_report.py exists', False)

real_fz = REPO / 'eval' / 'turnwatch-frozen.json'
if real_fz.exists():
    print('the real frozen block')
    os.environ.pop(T.ENV_FROZEN, None)
    m, why, info = T.load_frozen()
    check('research/eval/turn_match_llm.py and ask_match_llm.py still match eval/turnwatch-frozen.json',
          m is not None, f'{why} {info.get("bad")}')
    fz = json.loads(real_fz.read_text())
    check('the frozen block says its numbers are DEV numbers',
          fz.get('dev', {}).get('DEV_NOT_HELD_OUT') is True and 'DEV' in fz['frozen'].get('note', ''))
    rp_ = fz['dev'].get('repeat') or {}
    check('the freeze rests on a second run of EVERY reached row, not a partial re-score',
          rp_.get('complete') is True and rp_.get('n') == rp_.get('of_reached') == fz['dev']['reached_turns'])
    check('the frozen threshold is the one the stated rule picks from that two-run table',
          DEV.select_threshold(rp_.get('two_run')) == fz['frozen']['thresholds']['min_drift_score']
          == rp_.get('selected_min_drift_score'))
    check('the frozen block pins every file the judge loads',
          sorted(fz['frozen'].get('eval_files_sha256') or {}) == sorted(JUDGE_FILES))

print('the dev evaluation: a second run is a second run')
judged = {'D1': True, 'D2': True, 'C1': False, 'C2': False, 'C3': False, 'C4': False}
mk_row = lambda t: {'id': t, 'bare_approval': False}  # noqa: E731
reached = {t: mk_row(t) for t in judged}
resp = lambda v, s: {'verdict': v, 'drift_score': s, 'substituted': False, 'missing': [], 'asks': ['a'],  # noqa: E731
                     'covered': [], 'reason': 'r'}
run1 = {'D1': resp('misread', 90), 'D2': resp('misread', 50), 'C1': resp('misread', 60), 'C2': resp('aligned', 5),
        'C3': resp('aligned', 5), 'C4': resp('aligned', 5)}
run2 = {'D1': resp('misread', 90), 'D2': resp('narrowing', 40), 'C1': resp('aligned', 10),
        'C2': resp('misread', 70), 'C3': resp('aligned', 5), 'C4': resp('aligned', 5)}


class _Seq:
    name, credential = 'mock', None

    def __init__(self):
        self.calls = 0

    def call(self, system, prompt, schema):
        self.calls += 1
        t = next(t for t in run2 if f'MSG {t} ' in prompt)
        return {'text': json.dumps({**run2[t], 'reason': 'r'}), 'meta': {'cost_usd': 0.0}}


with tempfile.TemporaryDirectory() as td:
    for t in reached:
        reached[t].update(msg=f'MSG {t} end', user_recent=[], proposal=None, goal='g', doing=None,
                          first_text=None, msg_ts='2026-11-20T10:00:00Z')
    results = {t: {'response': run1[t]} for t in reached}
    seq = _Seq()

    class A:
        repeat, cache_only, freeze, concurrency, retries, max_calls, timeout = 'all', False, None, 1, 0, 50, 5
        cache = td
    rp2 = DEV.repeat_check(A, pathlib.Path(td), judged, reached, results, lambda m: None, backend=seq)
    row40 = next(r for r in rp2['two_run'] if r['min_drift_score'] == 40)
    check('--repeat all scores every reached row again (no run-1 reply stands in for run 2)',
          seq.calls == len(reached) and rp2['complete'] and rp2['n'] == len(reached), rp2.get('n'))
    check('a run-2 flag on a row run 1 left alone counts (the old table missed these)',
          row40['fp_run1'] == 1 and row40['fp_run2'] == 1, row40)
    A.repeat = '2'
    rp3 = DEV.repeat_check(A, pathlib.Path(td) / 'part', judged, reached, results, lambda m: None, backend=_Seq())
    check('a partial re-score gives no two-run table and no threshold choice',
          rp3['complete'] is False and rp3['two_run'] is None and rp3['selected_min_drift_score'] is None
          and 'not a second run' in rp3['what'], rp3.get('what'))
    tr = [{'min_drift_score': 40, 'tp_both_runs': 2, 'fp_run1': 8, 'fp_run2': 11, 'false_flag_rate_worse_run': 0.061},
          {'min_drift_score': 50, 'tp_both_runs': 1, 'fp_run1': 8, 'fp_run2': 9, 'false_flag_rate_worse_run': 0.0497},
          {'min_drift_score': 90, 'tp_both_runs': 1, 'fp_run1': 1, 'fp_run2': 1, 'false_flag_rate_worse_run': 0.0055}]
    check('the rule: most catches in both runs within 5% in the worse run, then fewest false flags',
          DEV.select_threshold(tr) == 90 and DEV.select_threshold(tr[:1]) is None)

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
