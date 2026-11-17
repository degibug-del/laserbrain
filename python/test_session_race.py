"""Parallel hook calls on one session keep every step, and nobody reads half a file.

Each hook call is its own process, and parallel tool calls (and parallel subagents, which
share the parent's session_id) run them at the same moment. <sid>.json was read whole,
edited and written back with write_text, unlocked. Measured 2026-11-16 on this hook under a
throwaway HOME, before the fix:

    parallel calls   steps kept (3-6 runs each)          runs that lost goal + checks
         12          12, 11, 11                           0 of 3
         24          23, 23, 22                           0 of 3
         48          43, 30, 39, 45, 44, 36, 38, 2, 35    4 of 6
         96          5, 24, 70                            3 of 3

The second column is the lost update: two processes load the same version and the later
save drops the other's step. The third is the torn read: write_text truncates and then
writes, a process that reads in between gets an empty file, starts a FRESH session, and its
save wipes the goal, every check and every catch. A reader thread saw a non-JSON file 9 to
344 times per run.

Now every read-modify-write runs under one flock per session (<sid>.json.lock, bounded
wait, then proceed) and every write is a temp file renamed over the old one. This drives
the real hook under a throwaway HOME, on the runtime path and on the fallback path the hook
takes when laserbrain.runtime cannot be imported, and checks the lock in one process too.

Run:  python3 test_session_race.py [package_root]
      (package_root defaults to this directory; point it at a copy of the old package to
       watch these checks fail)
"""
import importlib.util, json, os, pathlib, shutil, signal, subprocess, sys, tempfile, threading, time

try:
    import fcntl
except ImportError:                   # no flock on this platform: nothing to test here
    print('no fcntl on this platform; skipped')
    raise SystemExit(77)

PKG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else __file__).resolve()
PKG = PKG if PKG.is_dir() else PKG.parent
HOOK = PKG / 'laserbrain' / 'hooks' / 'lb_coverage.py'
H = pathlib.Path(tempfile.mkdtemp(prefix='lbrace-'))
STATE = H / 'lb' / 'sessions'
ENV = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN')}
ENV.update(HOME=str(H), LASERBRAIN_HOME=str(H / 'lb'), PYTHONPATH=str(PKG),
           PYTHONDONTWRITEBYTECODE='1', LASERBRAIN_AGENT='claude',
           LASERBRAIN_API='http://127.0.0.1:9', LASERBRAIN_HUB='http://127.0.0.1:9')
# A laserbrain package that refuses to import, first on the path: the hook then takes its
# embedded fallback, which writes the same file with its own copy of the lock.
FAKE = H / 'fake'
(FAKE / 'laserbrain').mkdir(parents=True)
(FAKE / 'laserbrain' / '__init__.py').write_text("raise ImportError('forced: test the fallback')\n")
FALLBACK_ENV = dict(ENV, PYTHONPATH=str(FAKE))
res = {}


def hook_cmd(fallback):
    return ([sys.executable, '-P', str(HOOK)] if fallback
            else [sys.executable, '-P', '-m', 'laserbrain.hooks.lb_coverage'])


def spawn(payload, fallback=False, extra=None):
    f = H / f'p-{time.monotonic_ns()}-{threading.get_ident()}.json'
    f.write_text(json.dumps(payload))
    env = dict(FALLBACK_ENV if fallback else ENV, **(extra or {}))
    with open(f) as fh:
        return subprocess.Popen(hook_cmd(fallback), stdin=fh, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=env, cwd=str(H))


def run(payload, fallback=False, extra=None):
    t0 = time.monotonic()
    spawn(payload, fallback, extra).wait(60)
    return time.monotonic() - t0


def prompt(sid):
    return {'hook_event_name': 'UserPromptSubmit', 'session_id': sid,
            'prompt': 'please refactor the parser module and add unit tests for it',
            'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)}


def check(sid):
    v = {'drifting': False, 'reason': 'advancing', 'phi': 0.1, 'run': 'r1', 'step': 1}
    return {'hook_event_name': 'PostToolUse', 'session_id': sid,
            'tool_name': 'mcp__laserbrain__check_state',
            'tool_input': {'goal': 'refactor the parser', 'progress': 'advancing', 'distance': 5},
            'tool_response': {'content': [{'type': 'text', 'text': json.dumps(v)}]},
            'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)}


def bash(sid, i):
    return {'hook_event_name': 'PostToolUse', 'session_id': sid, 'tool_name': 'Bash',
            'tool_input': {'command': f'echo step {i}'},
            'tool_response': {'stdout': 'ok', 'stderr': '', 'exit_code': 0},
            'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)}


def state(sid):
    try:
        return json.loads((STATE / f'{sid}.json').read_text())
    except Exception:
        return {}


def started(sid, fallback=False):
    """A session with a goal and one check on disk, as a real one has by mid-task."""
    run(prompt(sid), fallback)
    run(check(sid), fallback)
    return state(sid)


def race(sid, n, fallback=False):
    before = started(sid, fallback)
    path = STATE / f'{sid}.json'
    seen = {'reads': 0, 'partial': 0}
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                t = path.read_text()
            except FileNotFoundError:
                continue
            seen['reads'] += 1
            try:
                json.loads(t)
            except Exception:
                seen['partial'] += 1
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    procs = [spawn(bash(sid, i), fallback) for i in range(n)]
    for p in procs:
        p.wait(120)
    stop.set()
    th.join()
    after = state(sid)
    return before, after, seen, path


class held_flock:
    """Hold <sid>.json.lock the way any holder would, independent of the package under
    test, so the same check runs against the old code."""

    def __init__(self, sid):
        STATE.mkdir(parents=True, exist_ok=True)
        self.p = STATE / f'{sid}.json.lock'

    def __enter__(self):
        self.fh = open(self.p, 'a+')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


# ── parallel calls on the runtime path keep every step ─────────────────────────────────
N = 48
before, after, seen, path = race('rt', N)
res[f'runtime path: {N} parallel calls keep all {N} steps'] = (
    after.get('steps', 0) - before.get('steps', 0) == N, (before.get('steps'), after.get('steps')))
res['runtime path: the goal survives'] = (
    bool(before.get('goal')) and after.get('goal') == before.get('goal'), after.get('goal'))
res['runtime path: the check survives'] = (
    len(after.get('checks') or []) == len(before.get('checks') or []) == 1,
    len(after.get('checks') or []))
res['runtime path: a reader never sees a partial file'] = (
    seen['partial'] == 0 and seen['reads'] > 0, seen)
_text = path.read_text()
res['the file format is unchanged (indent=2 JSON)'] = (
    _text == json.dumps(json.loads(_text), indent=2), _text[:60])
_left = [p.name for p in STATE.iterdir() if p.name.endswith('.tmp')]
res['no temp file is left behind'] = (not _left, _left)

# ── and on the fallback path, which has its own copy of the lock ───────────────────────
N2 = 48
before, after, seen, _ = race('fb', N2, fallback=True)
res[f'fallback path: {N2} parallel calls keep all {N2} steps'] = (
    after.get('steps', 0) - before.get('steps', 0) == N2, (before.get('steps'), after.get('steps')))
res['fallback path: the goal and the check survive'] = (
    bool(before.get('goal')) and after.get('goal') == before.get('goal')
    and len(after.get('checks') or []) == 1, (after.get('goal'), len(after.get('checks') or [])))
res['fallback path: a reader never sees a partial file'] = (
    seen['partial'] == 0 and seen['reads'] > 0, seen)

# ── a held lock costs at most the bound, and the step is still recorded ────────────────
for label, fb in (('runtime path', False), ('fallback path', True)):
    sid = 'held-fb' if fb else 'held-rt'
    s0 = started(sid, fb).get('steps', 0)
    with held_flock(sid):
        took = run(bash(sid, 0), fb, {'LASERBRAIN_LOCK_WAIT': '1'})
    # One bound, not one per nesting level: _txn holds the lock around save(), which takes
    # it again, and that inner call used to wait a second full bound (4.1 s at the default).
    res[f'{label}: a held lock does not hang the call (bound 1 s)'] = (took < 1 + 0.5, round(took, 2))
    res[f'{label}: the call waited for the lock first'] = (took >= 0.9, round(took, 2))
    res[f'{label}: and then recorded its step anyway'] = (
        state(sid).get('steps', 0) == s0 + 1, (s0, state(sid).get('steps')))
with held_flock('held-rt'):
    took = run(bash('held-rt', 1))
res['the default bound is about 2 s'] = (1.8 <= took < 2 + 0.5, round(took, 2))

# camelCase hosts outside nudge mode run the runtime path and then, on a nudge step, fall
# through to the fallback, which takes the same lock again. One bound per call, not two.
def camel_bash(sid, i):
    return {'hookEventName': 'PostToolUse', 'sessionId': sid, 'toolName': 'Bash',
            'toolInput': {'command': f'echo step {i}'},
            'toolResponse': {'stdout': 'ok', 'stderr': '', 'exit_code': 0}, 'cwd': str(H)}


_hard = {'LASERBRAIN_GATE_MODE': 'hard', 'LASERBRAIN_LOCK_WAIT': '1'}
started('camel')
for i in range(7):                    # the 8th call since the check is a nudge step
    run(camel_bash('camel', i), extra=_hard)
s0 = state('camel').get('steps', 0)
with held_flock('camel'):
    took = run(camel_bash('camel', 7), extra=_hard)
res['camelCase fall-through: a held lock costs one bound, not two'] = (
    0.9 <= took < 1 + 0.5, round(took, 2))
res['  and the step lands (counted twice there, as before)'] = (
    state('camel').get('steps', 0) == s0 + 2, (s0, state('camel').get('steps')))

# A holder that dies: the kernel drops a flock with its process, so nothing is left to wait
# out or steal, unlike an O_EXCL lock file.
started('dead')
_holder = subprocess.Popen([sys.executable, '-c', (
    'import fcntl, sys, time\n'
    f'fh = open({str(STATE / "dead.json.lock")!r}, "a+")\n'
    'fcntl.flock(fh, fcntl.LOCK_EX)\n'
    'print("held", flush=True)\n'
    'time.sleep(60)\n')], stdout=subprocess.PIPE, text=True)
_holder.stdout.readline()
os.kill(_holder.pid, signal.SIGKILL)
_holder.wait(10)
took = run(bash('dead', 0), extra={'LASERBRAIN_LOCK_WAIT': '3'})
res['a lock whose holder was killed costs no wait'] = (took < 1.5, round(took, 2))
res['  and the step lands'] = (state('dead').get('steps') == 2, state('dead').get('steps'))

# ── a damaged session file is kept beside the new one, not silently replaced ──────────
for label, fb in (('runtime path', False), ('fallback path', True)):
    sid = 'bad-fb' if fb else 'bad-rt'
    STATE.mkdir(parents=True, exist_ok=True)
    junk = b'{"goal": "refactor the parser", "steps": 40, "checks": [{"step\xff'
    (STATE / f'{sid}.json').write_bytes(junk)
    run(bash(sid, 0), fb)
    aside = STATE / f'{sid}.json.corrupt'
    res[f'{label}: a damaged file is set aside byte for byte'] = (
        aside.exists() and aside.read_bytes() == junk, aside.exists())
    res[f'{label}:   and a fresh session takes its place'] = (
        state(sid).get('steps') == 1, state(sid).get('steps'))

# ── <sid>.agents.json: bounded lock, never half a file ────────────────────────────────
def agent_bash(sid, i, agent):
    return dict(bash(sid, i), agent_id=agent)


started('ag')
_ap = STATE / 'ag.agents.json'
_seen = {'reads': 0, 'partial': 0}
_stop = threading.Event()


def _agents_reader():
    while not _stop.is_set():
        try:
            t = _ap.read_text()
        except FileNotFoundError:
            continue
        _seen['reads'] += 1
        try:
            json.loads(t)
        except Exception:
            _seen['partial'] += 1


_th = threading.Thread(target=_agents_reader, daemon=True)
_th.start()
_procs = [spawn(agent_bash('ag', i, f'a{i % 4}')) for i in range(48)]
for _p in _procs:
    _p.wait(120)
_stop.set()
_th.join()
try:
    _ag = json.loads(_ap.read_text())
except Exception:
    _ag = {}
res['agents.json: 48 parallel calls by 4 agents keep all 48 steps'] = (
    sum(int((_ag.get(f'a{k}') or {}).get('steps', 0)) for k in range(4)) == 48,
    {k: (v or {}).get('steps') for k, v in _ag.items()})
res['agents.json: a reader never sees a partial file'] = (
    _seen['partial'] == 0 and _seen['reads'] > 0, _seen)
_s0 = (_ag.get('a0') or {}).get('steps', 0)
with open(STATE / 'ag.agents.json.lock', 'a+') as _fh:
    fcntl.flock(_fh, fcntl.LOCK_EX)
    took = run(agent_bash('ag', 99, 'a0'), extra={'LASERBRAIN_LOCK_WAIT': '1'})
    fcntl.flock(_fh, fcntl.LOCK_UN)
res['agents.json: a held lock costs at most the bound'] = (0.9 <= took < 1 + 0.5, round(took, 2))
try:
    _a0 = json.loads(_ap.read_text()).get('a0', {}).get('steps')
except Exception:
    _a0 = None
res['agents.json:   and the step lands'] = (_a0 == _s0 + 1, (_s0, _a0))

# ── in one process: no self-deadlock, threads too ─────────────────────────────────────
os.environ.update(LASERBRAIN_HOME=str(H / 'lb'), LASERBRAIN_HOOK_EVIDENCE='1',
                  LASERBRAIN_API='http://127.0.0.1:9', LASERBRAIN_HUB='http://127.0.0.1:9',
                  LASERBRAIN_LOCK_WAIT='5')
sys.path.insert(0, str(PKG))
from laserbrain.runtime import Session  # noqa: E402
D = str(STATE)
s1 = Session('dup', goal='refactor the parser', directory=D)
s1.check('refactor the parser', 'advancing', 5, drifting=False)
s2 = Session('dup', directory=D)            # a second object for the same id, same process
t0 = time.monotonic()
s1.tool('Bash', {'command': 'a'})
s2.tool('Bash', {'command': 'b'})          # read before s1 saved: must catch up, not overwrite
s1.tool('Bash', {'command': 'c'})
took = time.monotonic() - t0
res['two Sessions for one id in one process: no deadlock'] = (took < 1.0, round(took, 3))
res['  and neither overwrites the other'] = (
    state('dup').get('steps') == 4 and s1.d['steps'] == 4
    and [json.loads(e['sig'].split('|', 1)[1].rsplit('#', 1)[0])['command']
         for e in state('dup')['events']] == ['a', 'b', 'c'],
    (state('dup').get('steps'), [e.get('sig') for e in state('dup').get('events') or []]))
res['  the check and goal survive the catch-up'] = (
    len(state('dup').get('checks') or []) == 1 and state('dup').get('goal') == 'refactor the parser',
    state('dup').get('goal'))

try:
    from laserbrain.runtime import session_lock  # noqa: E402
    t0 = time.monotonic()
    with session_lock(STATE / 'dup.json') as got:
        Session('dup', directory=D).tool('Bash', {'command': 'd'})   # takes the same lock
    took = time.monotonic() - t0
    res['a Session inside a held session_lock re-enters, no wait'] = (got and took < 1.0, (got, round(took, 3)))
except Exception as e:  # noqa: BLE001 — the old package has no session_lock
    res['a Session inside a held session_lock re-enters, no wait'] = (False, repr(e))

# Every mutation waits one bound when another process holds the lock, never two.
started('inb')
os.environ['LASERBRAIN_LOCK_WAIT'] = '0.5'
_ops = {'tool': lambda: Session('inb', directory=D).tool('Bash', {'command': 'x'}),
        'check': lambda: Session('inb', directory=D).check('refactor the parser', 'advancing',
                                                            4, drifting=False),
        'reset': lambda: Session('inb', directory=D).reset(),
        'save': lambda: Session('inb', directory=D).save()}
with held_flock('inb'):
    _took = {}
    for _n, _f in _ops.items():
        _t0 = time.monotonic()
        _f()
        _took[_n] = round(time.monotonic() - _t0, 3)
    try:
        from laserbrain.runtime import session_lock  # noqa: E402
        _t0 = time.monotonic()
        with session_lock(STATE / 'inb.json') as _got:
            Session('inb', directory=D).tool('Bash', {'command': 'y'})
        _took['save inside a lock that gave up'] = round(time.monotonic() - _t0, 3)
    except Exception as e:  # noqa: BLE001
        _took['save inside a lock that gave up'] = repr(e)
res['in process: tool, check, reset, save each wait one bound (0.5 s), not two'] = (
    all(isinstance(v, float) and 0.45 <= v < 0.5 + 0.25 for v in _took.values()), _took)
os.environ['LASERBRAIN_LOCK_WAIT'] = '5'

errs = []


def worker(k):
    try:
        for i in range(25):
            Session('thr', directory=D).tool('Bash', {'command': f't{k}-{i}'})
    except Exception as e:  # noqa: BLE001
        errs.append(repr(e))


ths = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
[t.start() for t in ths]
[t.join(60) for t in ths]
res['4 threads x 25 calls in one process keep all 100 steps'] = (
    not errs and state('thr').get('steps') == 100, (state('thr').get('steps'), errs[:1]))

# ── the two copies of the lock are one lock ───────────────────────────────────────────
try:
    from laserbrain.runtime import lock_path  # noqa: E402
    spec = importlib.util.spec_from_file_location('lb_cov_race', HOOK)
    hk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hk)
    p = STATE / 'x1.json'
    res['both copies name the same lock file'] = (
        str(hk._state_lock_path(p)) == str(lock_path(p)) == str(STATE / 'x1.json.lock'), None)
    started('x1')
    with session_lock(STATE / 'x1.json'):
        took = run(bash('x1', 0), fallback=True, extra={'LASERBRAIN_LOCK_WAIT': '1'})
    res["the fallback hook waits on runtime's lock"] = (took >= 0.9, round(took, 2))
    started('x2')
    with hk._state_lock(STATE / 'x2.json') as got:
        took = run(bash('x2', 0), extra={'LASERBRAIN_LOCK_WAIT': '1'})
    res["the runtime hook waits on the fallback's lock"] = (got and took >= 0.9, round(took, 2))
except Exception as e:  # noqa: BLE001
    res['both copies name the same lock file'] = (False, repr(e))

shutil.rmtree(H, ignore_errors=True)
bad = [k for k, (ok, _) in res.items() if not ok]
for k, (ok, detail) in res.items():
    print(('PASS ' if ok else 'FAIL ') + k + ('' if ok else f'   -> {detail}'))
print(f'\n{len(res) - len(bad)}/{len(res)} pass')
sys.exit(1 if bad else 0)
