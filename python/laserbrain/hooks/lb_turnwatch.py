#!/usr/bin/env python3
"""lb_turnwatch.py — turnwatch, live and WATCH-ONLY: did the MAIN session misread the user?

WHAT. Once per user turn of the main session (never for a helper agent), at the first
check_state after the user's message reached the model, the frozen judge in
research/eval/turn_match_llm.py grades whether the assistant set out to do what the user
asked: the user's latest message, up to 5 earlier ones, the assistant's last message before
it (so a bare "ok" is judged against the proposal it approved), the goal and `doing` just
spelled, and the assistant's first words of the turn. research/DAY-FIVE-REAL-SESSIONS.md §4-5
(step D): the main session misreading the user is the largest drift nothing caught.

WATCH-ONLY. Nothing here reaches the model or the user: no additionalContext, nothing on
stdout or stderr, never a block, never an exception into lb_coverage. lb_coverage calls
on_post_tool_use() on a main-session check_state; it reads the last 512 KB (at most 4 MB) of
the transcript to find the latest delivered user message and, when that message has not been
judged yet, starts a DETACHED worker (its own session, stdout and stderr to /dev/null, the job
handed over on a pipe that is closed at once). The worker waits for the first-words window,
builds the row with turn_match_llm.build_row(), makes the one Haiku call and appends one line
to <STATE_DIR>/turnwatch.jsonl.

THE JUDGE IS FROZEN. Before anything runs, the sha256 of EVERY research/eval file the judge
loads (eval_files_sha256 in eval/turnwatch-frozen.json: turn_match_llm.py, ask_match_llm.py
and the helpers they import, _common.py with the redaction among them) is compared with the
frozen block. Once loaded: any research/eval module in sys.modules that the block does not
pin, prompt_hash(), MODEL, THRESHOLDS and FIRST_WORDS_WINDOW_S are checked too, and a
synthetic secret must come back redacted (the redaction patterns live outside research/eval,
in lb_secrets). Any difference: one log line, 'skipped: frozen changed', and no call. The
frozen numbers are DEV numbers (labels known in advance); this watch is the prospective test.

THE BACKEND is ask_match_llm.ClaudeCLIBackend, as askllm uses it: `claude -p` with no settings
sources, disableAllHooks, no tools, no MCP servers, no session persistence and an empty working
directory, so the call cannot re-enter laserbrain's hooks. Every text passes
research/eval/_common.redact before it is sent or logged.

LIMITS. 80 model calls per local day (its own count, in its own small file, retries
included). At most 2 `claude -p` at once, shared with askllm (the same slot files). 60 s per
call, one retry, a 300 s watchdog. The worker reads the transcript BACKWARDS a block at a time
and stops once it has the check and enough user messages, so its memory holds one block and
the small events, whatever the transcript's size. Its environment is cut to an allowlist
(lb_askllm_watch.restrict_child_env) before `claude -p` starts. Off with LASERBRAIN_TURNWATCH=off
or the file <STATE_DIR>/turnwatch.off. Errors are logged, never raised; a hook-side error logs
only its type.

BOOKKEEPING. <STATE_DIR>/turnwatch.seen.json ('last' and 'judged' message keys, the latest
KEEP_SESSIONS sessions) and turnwatch.calls.json (the daily count) are each replaced through a
temp file and os.replace, only when they changed, while turnwatch.lock is held (a bounded
wait, never a hang). A hook killed mid-write cannot leave half a file, and losing the seen file
cannot reset the count.

TRIGGER. lb_coverage calls on_post_tool_use() on a main-session check_state's PostToolUse AND
its PostToolUseFailure: the dev set counts every check_state the assistant spelled, a failed
one included, so the live trigger must too.

FIRST-TOOL TRIGGER (phase 2a, since 2026-11-19; off unless LASERBRAIN_TURNWATCH_TRIGGER=first_tool
in quiet mode). Then lb_coverage does not call on_post_tool_use() for the main session at all.
It writes a pending marker when the user's message arrives (a real prompt, or a queued user
message it finds in the transcript) and, while the marker exists, calls on_first_tool() on the
main session's next PostToolUse or PostToolUseFailure of ANY tool. That starts the same detached
worker with arm 'anchor': research/eval/turn_anchor.py (pinned, with every file of the check
arm, in its own eval/turnwatch-anchor-frozen.json) anchors the frozen turn_match_llm.build_row at
the first tool call after the message, so the row no longer waits for a check_state the agent
may never make. When that first tool call is check_state the row is the check arm's row byte for
byte. Rows say trigger 'first_tool' and variant 'first-tool'. On the DEV set this reaches 10 of
the 10 drift turns instead of 6 (reach, not catches: the anchor arm is unscored).

STAMPS (since 2026-11-19), so rows from different policies and triggers can be told apart:
every row carries `trigger` ('check_state': the first check after the message; 'first_tool':
the first tool call after it, phase 2a) and `policy`
(LASERBRAIN_POLICY as the hook saw it, cut to 40 characters, or null when unset). A row whose
prompt was rendered also carries `row_sha`, the first 16 hex digits of sha256 over
system + '\\n' + prompt (UTF-8), the same rule as lb_askllm_watch.row_sha. Rows written before
2026-11-19 have none of the three.

Review: python3 research/eval/turnwatch_report.py
"""
import datetime
import hashlib
import importlib.util as _ilu
import json
import os
import pathlib
import sys
import time

DAILY_CAP = 80                    # model calls per local day, retries included (own count)
CALL_TIMEOUT_S = 60
RETRIES = 1
WATCHDOG_S = 300
SLOT_WAIT_S = 60                  # 60 window + 60 slot + 2x60 calls + parsing < 300
MAX_JOB_BYTES = 64_000
HOOK_TAIL = (512 * 1024, 4 * 1024 * 1024)          # bytes the hook side reads, then at most
WORKER_MAX_BYTES = 64 * 1024 * 1024   # the worker reads at most this far back...
WORKER_BLOCK = 1024 * 1024            # ...one block at a time, parsing as it goes
KEEP_SESSIONS = 200                   # sessions kept in 'last' and 'judged' (latest by time)
LOCK_WAIT_S = 2.0                     # the bookkeeping lock: give up (an error line) after this

ENV_SWITCH = 'LASERBRAIN_TURNWATCH'             # off | 0 | false | no
ENV_DELAY = 'LASERBRAIN_TURNWATCH_DELAY'        # seconds before reading (tests use 0)
ENV_MOCK = 'LASERBRAIN_TURNWATCH_MOCK_REPLY'    # path to a canned reply: tests, no network
ENV_FROZEN = 'LASERBRAIN_TURNWATCH_FROZEN'      # frozen block json (tests)
ENV_ANCHOR_FROZEN = 'LASERBRAIN_TURNWATCH_ANCHOR_FROZEN'   # the anchor arm's frozen block (tests)
ENV_EVAL = 'LASERBRAIN_TURNWATCH_EVAL_DIR'      # research/eval (tests)
ENV_POLICY = 'LASERBRAIN_POLICY'                # the policy stamp on every row
POLICY_CHARS = 40                               # lb_coverage cuts its check-row stamp the same
TRIGGER = 'check_state'                         # the first main-session check after a message
TRIGGER_FIRST_TOOL = 'first_tool'               # the first main-session tool call after it (2a)
ARM_CHECK, ARM_ANCHOR = 'check', 'anchor'       # which frozen block and row builder a job uses
ANCHOR_FILE = 'turn_anchor.py'                  # research/eval: the anchor arm's row builder

LOG_NAME = 'turnwatch.jsonl'
SEEN_NAME = 'turnwatch.seen.json'
CALLS_NAME = 'turnwatch.calls.json'
LOCK_NAME = 'turnwatch.lock'
OFF_NAME = 'turnwatch.off'
CLI_DIR_NAME = 'turnwatch-cli'

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]

# The delivered-user-message rule of turn_match_llm.parse_records(), copied so the hook side
# never loads the judge (test_turnwatch.py pins the two): these are extract_starts._SKIP_PREFIX.
_SKIP_PREFIX = ('<task-notification', '<command-', '<local-command', '<system-reminder',
                '[Request interrupted', 'Caveat:', '<bash-', '<user-memory')


def eval_dir():
    return pathlib.Path(os.environ.get(ENV_EVAL) or (REPO / 'research' / 'eval'))


def frozen_path(arm=ARM_CHECK):
    if arm == ARM_ANCHOR:
        return pathlib.Path(os.environ.get(ENV_ANCHOR_FROZEN)
                            or (REPO / 'eval' / 'turnwatch-anchor-frozen.json'))
    return pathlib.Path(os.environ.get(ENV_FROZEN) or (REPO / 'eval' / 'turnwatch-frozen.json'))


def _now():
    return datetime.datetime.now()


def _ts():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def _today(now=None):
    return (now or _now()).date().isoformat()


def switch_reason(state_dir):
    """None when turnwatch runs, else why it is off ('env', 'file')."""
    v = (os.environ.get(ENV_SWITCH) or '').strip().lower()
    if v in ('off', '0', 'false', 'no', 'disable', 'disabled'):
        return 'env'
    try:
        if (pathlib.Path(state_dir) / OFF_NAME).exists():
            return 'file'
    except Exception:
        return 'file'
    return None


# ── bookkeeping: two small JSON files under one lock ───────────────────────────────

def _read_json(p):
    try:
        d = json.loads(pathlib.Path(p).read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_json_atomic(p, obj):
    p = pathlib.Path(p)
    tmp = p.with_name(f'.{p.name}.{os.getpid()}.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(obj))
    os.replace(tmp, p)


def _locked(state_dir):
    """An open, exclusively flock'd <STATE_DIR>/turnwatch.lock (close it to release). Waits at
    most LOCK_WAIT_S, then raises TimeoutError: a stuck lock costs one turn, never a hang."""
    import fcntl
    pathlib.Path(state_dir).mkdir(parents=True, exist_ok=True)
    fh = open(pathlib.Path(state_dir) / LOCK_NAME, 'a')
    t_end = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            if time.monotonic() >= t_end:
                fh.close()
                raise TimeoutError('turnwatch.lock busy') from None
            time.sleep(0.005)


def _with_seen(state_dir, fn):
    """fn(d) under the lock. d holds 'last' {session: the message the hook last spawned for},
    'judged' {session: the message the worker last scored} (turnwatch.seen.json) and 'calls'
    {day: model calls} (turnwatch.calls.json, its own file so a lost seen file cannot reset the
    cap). fn returns (result, dirty): dirty names the parts it changed, which alone are written."""
    fh = _locked(state_dir)
    try:
        sp, cp = pathlib.Path(state_dir) / SEEN_NAME, pathlib.Path(state_dir) / CALLS_NAME
        seen, calls = _read_json(sp), _read_json(cp)
        d = {'last': seen.get('last') if isinstance(seen.get('last'), dict) else {},
             'judged': seen.get('judged') if isinstance(seen.get('judged'), dict) else {},
             'calls': calls.get('calls') if isinstance(calls.get('calls'), dict) else {}}
        out, dirty = fn(d)
        dirty = set(dirty or ())
        if dirty & {'last', 'judged'}:
            for k in ('last', 'judged'):
                if len(d[k]) > KEEP_SESSIONS:
                    d[k] = dict(sorted(d[k].items(), key=lambda kv: str((kv[1] or {}).get('ts', '')))
                                [-KEEP_SESSIONS:])
            _write_json_atomic(sp, {'last': d['last'], 'judged': d['judged']})
        if 'calls' in dirty:
            if len(d['calls']) > 30:
                d['calls'] = dict(sorted(d['calls'].items())[-30:])
            _write_json_atomic(cp, {'calls': d['calls']})
        return out
    finally:
        fh.close()


def calls_today(state_dir, now=None):
    try:
        return int((_read_json(pathlib.Path(state_dir) / CALLS_NAME).get('calls') or {}).get(_today(now), 0))
    except Exception:
        return 0


def reserve_call(state_dir, cap=DAILY_CAP, now=None):
    day = _today(now)

    def fn(d):
        n = int(d['calls'].get(day, 0))
        if n >= cap:
            return False, ()
        d['calls'][day] = n + 1
        return True, ('calls',)
    return _with_seen(state_dir, fn)


def _append_log(state_dir, rec):
    p = pathlib.Path(state_dir) / LOG_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(rec, ensure_ascii=False, default=str) + '\n').encode('utf-8', 'replace')
    fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


_REDACT = None


def _redactor():
    global _REDACT
    if _REDACT is None:
        try:
            ed = str(eval_dir())
            if ed not in sys.path:
                sys.path.insert(0, ed)
            from _common import redact
            _REDACT = redact
        except Exception:
            _REDACT = lambda text, limit=None: None   # noqa: E731
    return _REDACT


def snip(text, n):
    if text is None:
        return None
    r = _redactor()(' '.join(str(text).split()), None)
    if r is None:
        return None
    return r if len(r) <= n else r[:n] + '...'


def policy_now():
    """LASERBRAIN_POLICY as this process sees it, cut to POLICY_CHARS, or None when unset."""
    v = os.environ.get(ENV_POLICY)
    return v[:POLICY_CHARS] if v else None


def row_sha(system, prompt):
    """lb_askllm_watch.row_sha's rule (test_turnwatch.py pins the two): 16 hex digits of
    sha256(system + '\\n' + prompt), UTF-8 with surrogatepass so it never raises."""
    data = f'{system}\n{prompt}'.encode('utf-8', 'surrogatepass')
    return hashlib.sha256(data).hexdigest()[:16]


def _base(job):
    """The fields every row starts with. trigger and policy come from the job; a job without a
    policy key (an error before the job was built, a job from an older hook) takes this
    process's LASERBRAIN_POLICY. A first-tool job (arm 'anchor') is variant 'first-tool'."""
    return {'ts': _ts(), 'session': job.get('session'), 'lane': job.get('lane'),
            'tool_use_id': job.get('tool_use_id'),
            'variant': 'first-tool' if job.get('arm') == ARM_ANCHOR else 'first-check',
            'trigger': job.get('trigger') or TRIGGER,
            'policy': job['policy'] if 'policy' in job else policy_now()}


def _log_error(state_dir, job, where, exc, hook=False):
    """One error line. On the HOOK side (hook=True) only the exception's type is logged: the
    redactor would put research/eval on lb_coverage's sys.path and load _common there."""
    try:
        rec = _base(job or {})
        rec.update(status='error', reason=f'{where}: {type(exc).__name__}',
                   error=None if hook else snip(str(exc), 300))
        _append_log(state_dir, rec)
    except Exception:
        pass


# ── hook side: cheap, never raises, never prints ────────────────────────────────────

def _text_of(content):
    """extract_starts._text_of: a string, or the text blocks of a list without tool results."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
            return None
        return '\n'.join(b.get('text', '') for b in content
                         if isinstance(b, dict) and b.get('type') == 'text')
    return None


def user_text(r):
    """The text of a delivered user message record (a prompt, or a mid-turn queued_command
    attachment) in the main session, else None. turn_match_llm.parse_records' rule."""
    if not isinstance(r, dict) or r.get('isSidechain') or not isinstance(r.get('timestamp'), str):
        return None
    t = r.get('type')
    if t == 'user':
        if r.get('isMeta') or r.get('toolUseResult') is not None or r.get('isCompactSummary'):
            return None
        txt = _text_of((r.get('message') or {}).get('content'))
    elif t == 'attachment':
        a = r.get('attachment') or {}
        if a.get('type') != 'queued_command' or a.get('commandMode') not in (None, 'prompt'):
            return None
        p = a.get('prompt')
        txt = p if isinstance(p, str) else _text_of(p)
    else:
        return None
    if not txt or not txt.strip() or txt.lstrip().startswith(_SKIP_PREFIX):
        return None
    return txt.strip()


def msg_key(text, ts):
    """turn_match_llm.msg_key: identity of one delivered message."""
    return hashlib.sha256(f'{ts}|{str(text or "").strip()[:400]}'.encode('utf-8')).hexdigest()[:24]


def latest_user_message(path, sizes=HOOK_TAIL):
    """(ts, text) of the latest delivered user message in the transcript's tail, or None.
    Reads the last sizes[0] bytes, then sizes[1] when that held none."""
    for n in sizes:
        with open(path, 'rb') as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = max(0, size - n)
            fh.seek(start)
            data = fh.read()
        lines = data.decode('utf-8', 'replace').split('\n')
        if start > 0:
            lines = lines[1:]
        for line in reversed(lines):
            if ('"user"' not in line and '"queued_command"' not in line) or '"toolUseResult":' in line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            txt = user_text(r)
            if txt:
                return r['timestamp'], txt
        if start == 0:
            break
    return None


def _spawn(job):
    import subprocess
    argv = [sys.executable] + (['-P'] if sys.version_info >= (3, 11) else []) + \
        [str(pathlib.Path(__file__).resolve()), '--worker']
    return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
                            cwd=str(job['state_dir']))


def on_post_tool_use(ev, tool, args, state_dir, now=None):
    """lb_coverage calls this on a main-session check_state's PostToolUse or PostToolUseFailure.
    Returns a short status (for tests). Spawns the worker for the first check_state after each new delivered
    user message: never for a helper agent (the payload names an agent_id), never twice for one
    message, nothing at all when switched off or when no transcript is on disk."""
    t0 = time.perf_counter()
    try:
        if ev.get('agent_id') or ev.get('agentId'):
            return 'helper'
        if not str(tool or '').lower().endswith('check_state'):
            return 'not-check'
    except BaseException as e:                          # noqa: BLE001 — never into lb_coverage
        _log_error(state_dir, {'session': (ev or {}).get('session_id')}, 'hook', e, hook=True)
        return 'error'
    return _start(ev, args, state_dir, now, t0, ARM_CHECK)


def on_first_tool(ev, state_dir, now=None):
    """Phase 2a (LASERBRAIN_TURNWATCH_TRIGGER=first_tool). lb_coverage calls this on a MAIN-session
    PostToolUse or PostToolUseFailure of ANY tool while its turnwatch-pending marker for the
    session exists. The same statuses as on_post_tool_use() ('same-turn' and 'no-user-message'
    mean the message is not delivered yet, so lb_coverage keeps its marker), and the same worker,
    started with arm 'anchor': it anchors the frozen row at the first tool call after the latest
    delivered user message (research/eval/turn_anchor.py), never at this call's own tool."""
    t0 = time.perf_counter()
    try:
        if ev.get('agent_id') or ev.get('agentId'):
            return 'helper'
    except BaseException as e:                          # noqa: BLE001 — never into lb_coverage
        _log_error(state_dir, {'session': (ev or {}).get('session_id'), 'arm': ARM_ANCHOR,
                               'trigger': TRIGGER_FIRST_TOOL}, 'hook', e, hook=True)
        return 'error'
    return _start(ev, {}, state_dir, now, t0, ARM_ANCHOR)


def _start(ev, args, state_dir, now, t0, arm):
    """The part both triggers share: switches, the latest delivered message, the seen file and the
    daily cap under the lock, then the detached worker. Never raises."""
    job = None
    try:
        if switch_reason(state_dir):
            return 'off'
        if not (eval_dir() / 'turn_match_llm.py').exists() or (
                arm == ARM_ANCHOR and not (eval_dir() / ANCHOR_FILE).exists()):
            return 'no-judge'                # an installed wheel has no research/eval: nothing runs
        tp = ev.get('transcript_path') or ev.get('transcriptPath')
        if not tp or not os.path.exists(str(tp)):
            return 'no-transcript'
        found = latest_user_message(str(tp))
        if not found:
            return 'no-user-message'
        mts, mtext = found
        key = msg_key(mtext, mts)
        args = args if isinstance(args, dict) else {}
        sid = str(ev.get('session_id') or ev.get('sessionId') or 'unknown')
        day = _today(now)
        stamp = _ts()

        def fn(d):
            last = d['last'].get(sid) or {}
            if last.get('key') == key:
                return 'same-turn', ()
            d['last'][sid] = {'key': key, 'ts': stamp}
            if int(d['calls'].get(day, 0)) >= DAILY_CAP:
                return 'cap', ('last',)
            return 'spawn', ('last',)
        st = _with_seen(state_dir, fn)
        job = {'session': sid, 'transcript_path': str(tp),
               'tool_use_id': ev.get('tool_use_id') or ev.get('toolUseId'),
               'lane': str(args.get('session'))[:80] if args.get('session') else None,
               'msg_key': key, 'msg_ts': mts, 'hook_ts': stamp, 'hook_epoch': time.time(),
               'state_dir': str(state_dir), 'trigger': TRIGGER, 'policy': policy_now()}
        if arm == ARM_ANCHOR:                # no tool_use_id: the worker finds the anchor itself
            job.update(tool_use_id=None, lane=None, trigger=TRIGGER_FIRST_TOOL, arm=ARM_ANCHOR)
        if st == 'cap':
            rec = _base(job)
            rec.update(status='skipped', reason='daily cap', cap=DAILY_CAP, msg_ts=mts)
            _append_log(state_dir, rec)
            return 'cap'
        if st != 'spawn':
            return st
        p = _spawn(job)
        job['hook_ms'] = round((time.perf_counter() - t0) * 1000, 1)
        try:
            p.stdin.write(json.dumps(job).encode('utf-8', 'replace')[:MAX_JOB_BYTES])
            p.stdin.close()
        except Exception:
            pass
        return 'spawned'
    except BaseException as e:                          # noqa: BLE001 — never into lb_coverage
        fb = {'session': (ev or {}).get('session_id')}
        if arm == ARM_ANCHOR:
            fb.update(arm=ARM_ANCHOR, trigger=TRIGGER_FIRST_TOOL)
        _log_error(state_dir, job or fb, 'hook', e, hook=True)
        return 'error'


# ── worker side ─────────────────────────────────────────────────────────────────────

def _sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _canary():
    """A synthetic GitHub-token-shaped string (built here, never a real secret) that lb_secrets
    must redact."""
    return 'ghp_' + ''.join('Q7mK2pX9'[i % 8] for i in range(36))


def load_frozen(arm=ARM_CHECK):
    """(turn_match_llm module, None, info) when nothing frozen changed, else (None, reason, info).

    BEFORE anything executes: the sha256 of every file in the block's eval_files_sha256 (which
    must name turn_match_llm.py and ask_match_llm.py, and match the two legacy fields). AFTER
    loading: every research/eval module now in sys.modules must be one of those files with the
    same sha (a new import cannot slip past), and prompt_hash, MODEL, THRESHOLDS,
    FIRST_WORDS_WINDOW_S and the redaction canary must hold.

    arm 'anchor' reads eval/turnwatch-anchor-frozen.json instead, which must also pin
    turn_anchor.py and say anchor 'first_tool'; turn_anchor.py is loaded (as sys.modules
    'turn_anchor') BEFORE the sys.modules scan, so the scan covers it, and it must use this very
    turn_match_llm. On success info['anchor_module'] holds it."""
    info = {}
    try:
        fz = json.loads(frozen_path(arm).read_text()).get('frozen') or {}
    except Exception as e:
        return None, 'frozen block unreadable', {'error': type(e).__name__}
    ed = eval_dir()
    src, dep = ed / 'turn_match_llm.py', ed / 'ask_match_llm.py'
    files = fz.get('eval_files_sha256')
    try:
        sha, dsha = _sha(src), _sha(dep)
    except Exception as e:
        return None, 'frozen judge not found', {'error': type(e).__name__}
    info.update(file_sha=sha, ask_match_sha=dsha)
    bad = [k for k, v in (('turn_match_llm_sha256', sha), ('ask_match_llm_sha256', dsha))
           if v != fz.get(k)]
    if not isinstance(files, dict) or files.get('turn_match_llm.py') != fz.get('turn_match_llm_sha256') \
            or files.get('ask_match_llm.py') != fz.get('ask_match_llm_sha256'):
        bad.append('eval_files_sha256')
        files = {}
    for name, want in sorted(files.items()):
        try:
            got = _sha(ed / pathlib.Path(str(name)).name)
        except Exception:
            got = None
        if got != want:
            bad.append(f'eval_files_sha256:{name}')
    if arm == ARM_ANCHOR and (ANCHOR_FILE not in files or fz.get('anchor') != TRIGGER_FIRST_TOOL):
        bad.append('anchor')
    if bad:
        return None, 'frozen changed', {**info, 'bad': bad}
    eds = str(ed)
    if eds in sys.path:
        sys.path.remove(eds)
    sys.path.insert(0, eds)
    spec = _ilu.spec_from_file_location('turn_match_llm', str(src))
    m = _ilu.module_from_spec(spec)
    sys.modules['turn_match_llm'] = m
    spec.loader.exec_module(m)
    ph = m.prompt_hash()
    info.update(prompt_hash=ph, model=m.MODEL)
    anchor = None
    if arm == ARM_ANCHOR:
        aspec = _ilu.spec_from_file_location('turn_anchor', str(ed / ANCHOR_FILE))
        anchor = _ilu.module_from_spec(aspec)
        sys.modules['turn_anchor'] = anchor
        aspec.loader.exec_module(anchor)
        info['anchor_sha'] = files.get(ANCHOR_FILE)
    root = ed.resolve()
    for mod in list(sys.modules.values()):
        f = getattr(mod, '__file__', None)
        if not f:
            continue
        try:
            fp = pathlib.Path(f).resolve()
        except Exception:
            continue
        if fp.parent != root:
            continue
        if fp.name not in files:
            bad.append(f'unpinned:{fp.name}')
        elif _sha(fp) != files[fp.name]:
            bad.append(f'eval_files_sha256:{fp.name}')
    if pathlib.Path(m.aml.__file__).resolve() != dep.resolve() or m.aml.file_sha() != fz.get('ask_match_llm_sha256'):
        bad.append('ask_match_llm_sha256')
    if m.file_sha() != fz.get('turn_match_llm_sha256'):
        bad.append('turn_match_llm_sha256')
    if ph != fz.get('prompt_hash'):
        bad.append('prompt_hash')
    if m.MODEL != fz.get('model'):
        bad.append('model')
    if m.THRESHOLDS != fz.get('thresholds'):
        bad.append('thresholds')
    if m.FIRST_WORDS_WINDOW_S != fz.get('first_words_window_s'):
        bad.append('first_words_window_s')
    try:
        c = _canary()
        red = m.redact(f'token {c} here', None)
        if red is None or c in red:
            bad.append('redaction')
    except Exception:
        bad.append('redaction')
    if arm == ARM_ANCHOR and (getattr(anchor, 'tml', None) is not m
                              or getattr(anchor, 'ANCHOR', None) != TRIGGER_FIRST_TOOL):
        bad.append('anchor')
    if bad:
        return None, 'frozen changed', {**info, 'bad': sorted(set(bad), key=bad.index)}
    if arm == ARM_ANCHOR:
        info['anchor_module'] = anchor
    return m, None, info


class CappedBackend:
    """Counts every call against turnwatch's own daily cap before the frozen backend runs it."""

    def __init__(self, inner, state_dir, unavailable, cap=DAILY_CAP):
        self.inner, self.state_dir, self.cap, self.unavailable = inner, state_dir, cap, unavailable
        self.name = getattr(inner, 'name', '?')
        self.credential = getattr(inner, 'credential', None)
        self.calls = 0

    def call(self, system, prompt, schema):
        if not reserve_call(self.state_dir, self.cap):
            raise self.unavailable('daily cap reached')
        self.calls += 1
        return self.inner.call(system, prompt, schema)


def _askllm_module():
    """lb_askllm_watch, for its shared slot files, claude-binary lookup and session env list."""
    spec = _ilu.spec_from_file_location('lb_askllm_watch_tw', str(HERE / 'lb_askllm_watch.py'))
    w = _ilu.module_from_spec(spec)
    spec.loader.exec_module(w)
    return w


def make_backend(m, state_dir, w):
    import shutil
    aml = m.aml
    mock = os.environ.get(ENV_MOCK)
    if mock:
        text = pathlib.Path(mock).read_text()
        return aml.MockBackend(lambda system, prompt, schema: text)
    cache_dir = pathlib.Path(state_dir) / CLI_DIR_NAME
    on_path = shutil.which('claude')
    binary = None if on_path else w._claude_binary()   # reads CLAUDE_CODE_EXECPATH: before the cut
    w.restrict_child_env()                             # the allowlist askllm's worker uses
    if on_path:
        return aml.make_backend('claude', m.MODEL, CALL_TIMEOUT_S, cache_dir=cache_dir)
    if not binary:
        raise aml.BackendUnavailable('claude CLI not found on PATH')
    return aml.ClaudeCLIBackend(m.MODEL, CALL_TIMEOUT_S, token=aml.keychain('claude-oauth-token'),
                                workdir=cache_dir / 'cli-cwd', binary=binary)


def _enough(events, tool_use_id, need):
    """The events hold this check_state and at least `need` user messages before it."""
    ci = find_check(events, tool_use_id)
    return ci is not None and sum(1 for e in events[:ci] if e['k'] == 'user') >= need


def read_events(m, path, tool_use_id=None, max_bytes=WORKER_MAX_BYTES, block=WORKER_BLOCK):
    """Main-session events from the END of the transcript, read backwards one block at a time
    and parsed as it goes (m.parse_records on each block's complete lines), so memory holds one
    block, the longest line and the small events, never the whole tail. Stops once the events
    hold the check and more user messages before it than the row shows (LIMITS['recent'] + 3,
    room for repeats), at the start of the file, or after max_bytes (the partial line there is
    dropped, as read_tail drops it)."""
    need = m.LIMITS['recent'] + 3
    events = []
    with open(path, 'rb') as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        floor = max(0, pos - max_bytes)
        carry = b''
        while pos > floor:
            n = min(block, pos - floor)
            pos -= n
            fh.seek(pos)
            buf = fh.read(n) + carry
            if pos > 0:
                cut = buf.find(b'\n')
                if cut < 0:                           # one line longer than a block: keep going
                    carry = buf
                    continue
                carry, buf = buf[:cut], buf[cut + 1:]
            else:
                carry = b''
            events = m.parse_records(buf.decode('utf-8', 'replace').split('\n')) + events
            del buf
            if _enough(events, tool_use_id, need):
                break
    return events


def _enough_anchor(a, events, msg_key, need):
    """The events hold the target user message and at least `need` user messages before it."""
    ui = a.find_user(events, msg_key)
    return ui is not None and sum(1 for e in events[:ui] if e['k'] == 'user') >= need


def read_anchor_events(m, a, path, msg_key, max_bytes=WORKER_MAX_BYTES, block=WORKER_BLOCK):
    """read_events() for the anchor arm: (events, tool_uses) from the END of the transcript, read
    backwards one block at a time through turn_anchor.parse_lines (the frozen parse_records per
    line, plus the main session's tool calls), so memory holds one block and the small events,
    never the whole tail. Each block's tool calls are placed among the events ('ei') before the
    older block is prepended. Stops once the events hold the target message and more user
    messages before it than the row shows (LIMITS['recent'] + 3), at the start of the file, or
    after max_bytes."""
    need = m.LIMITS['recent'] + 3
    events, tus = [], []
    with open(path, 'rb') as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        floor = max(0, pos - max_bytes)
        carry = b''
        while pos > floor:
            n = min(block, pos - floor)
            pos -= n
            fh.seek(pos)
            buf = fh.read(n) + carry
            if pos > 0:
                cut = buf.find(b'\n')
                if cut < 0:                           # one line longer than a block: keep going
                    carry = buf
                    continue
                carry, buf = buf[:cut], buf[cut + 1:]
            else:
                carry = b''
            evb, tub = a.parse_lines(buf.decode('utf-8', 'replace').split('\n'))
            del buf
            if evb:
                for t in tus:
                    t['ei'] += len(evb)
            events = evb + events
            tus = tub + tus
            if _enough_anchor(a, events, msg_key, need):
                break
    return events, tus


def find_check(events, tool_use_id):
    """Index of this check_state in events: by tool_use id, else the last check."""
    last = None
    for i, e in enumerate(events):
        if e['k'] != 'check':
            continue
        if tool_use_id and e.get('id') == tool_use_id:
            return i
        last = i
    return None if tool_use_id else last


def run_job(job, state_dir=None, backend=None, delay=None, sleep=time.sleep):
    """Judge one turn and append one line. Never raises. Returns the logged record."""
    held = []
    try:
        return _run_job(job, state_dir, backend, delay, sleep, held)
    finally:
        for fh in held:
            try:
                fh.close()
            except Exception:
                pass


def _run_job(job, state_dir, backend, delay, sleep, held):
    state_dir = pathlib.Path(state_dir or job['state_dir'])
    t0 = time.time()
    rec = _base(job)
    rec['hook_ms'] = job.get('hook_ms')
    arm = ARM_ANCHOR if job.get('arm') == ARM_ANCHOR else ARM_CHECK
    try:
        if switch_reason(state_dir):
            return None
        m, why, info = load_frozen(arm)
        anchor = info.pop('anchor_module', None)
        rec['frozen_sha'] = info.get('file_sha')
        rec['prompt_hash'] = info.get('prompt_hash')
        if arm == ARM_ANCHOR:
            rec['anchor_sha'] = info.get('anchor_sha')
        if m is None:
            rec.update(status='skipped', reason=why, frozen_bad=info.get('bad'))
            _append_log(state_dir, rec)
            return rec
        rec['model'] = m.MODEL
        # Wait out the first-words window, counted from the check.
        if delay is None:
            env = os.environ.get(ENV_DELAY)
            if env is not None and env.strip() != '':
                delay = float(env)
            else:
                delay = max(0.0, m.FIRST_WORDS_WINDOW_S - (time.time() - float(job.get('hook_epoch') or time.time())))
        if delay > 0:
            sleep(delay)
        rec['delay_s'] = round(delay, 1)
        off = switch_reason(state_dir)
        if off:
            rec.update(status='skipped', reason=f'switched off during wait ({off})')
            _append_log(state_dir, rec)
            return rec
        if arm == ARM_ANCHOR:
            # The first tool call after the message the hook saw, found in the transcript (the
            # call that ran the hook may be a later one of the same batch), and the frozen row
            # anchored there: turn_anchor.row_for -> turn_match_llm.build_row.
            events, tus = read_anchor_events(m, anchor, job['transcript_path'], job.get('msg_key'))
            row, why, meta = anchor.row_for(events, tus, job.get('msg_key'), job.get('session') or '',
                                            window_s=m.FIRST_WORDS_WINDOW_S)
            del events, tus
            if row is None:
                rec.update(status='skipped', reason=why, msg_ts=job.get('msg_ts'))
                _append_log(state_dir, rec)
                return rec
            rec['anchor'] = {'tool': meta.get('tool'), 'check_first': bool(meta.get('check_first')),
                             'goal_from_check': bool(meta.get('goal_from_check'))}
        else:
            events = read_events(m, job['transcript_path'], job.get('tool_use_id'))
            ci = find_check(events, job.get('tool_use_id'))
            if ci is None:
                rec.update(status='skipped', reason='check_state not in transcript')
                _append_log(state_dir, rec)
                return rec
            row = m.build_row(events, ci, job.get('session') or '', window_s=m.FIRST_WORDS_WINDOW_S)
            if row is None:
                rec.update(status='skipped', reason='no user message before the check')
                _append_log(state_dir, rec)
                return rec
            # Only the FIRST check_state after the message is judged, as on the dev set: a later
            # one (a lost seen file, the first call after install) spells a goal from mid-turn.
            ui = m.user_index_for(events, ci)
            if any(events[j]['k'] == 'check' for j in range(ui + 1, ci)):
                rec.update(status='skipped', reason='not the first check_state after the message',
                           msg_ts=row['msg_ts'])
                _append_log(state_dir, rec)
                return rec
        rec['msg_ts'] = row['msg_ts']
        rec['msg_via'] = row['msg_via']
        rec['key_matches_hook'] = row['msg_key'] == job.get('msg_key')
        stamp = _ts()

        def fn(d):
            if (d['judged'].get(rec['session']) or {}).get('key') == row['msg_key']:
                return False, ()
            d['judged'][rec['session']] = {'key': row['msg_key'], 'ts': stamp}
            return True, ('judged',)
        if not _with_seen(state_dir, fn):
            rec.update(status='skipped', reason='this user message was already judged')
            _append_log(state_dir, rec)
            return rec
        rec['bare_approval'] = row['bare_approval']
        rec['inputs'] = {'user_recent': len(row['user_recent']), 'proposal': bool(row['proposal']),
                         'goal': bool(row['goal']), 'doing': bool(row['doing']),
                         'first_text': bool(row['first_text'])}
        rec['snippets'] = {'msg': snip(row['msg'], 200), 'goal': snip(row['goal'], 160),
                           'doing': snip(row['doing'], 160), 'proposal': snip(row['proposal'], 200)}
        system, prompt, schema = m.render(row)
        rec['row_sha'] = row_sha(system, prompt)
        w = _askllm_module()
        tw = time.time()
        slot = w.acquire_slot(state_dir, sleep, wait_s=SLOT_WAIT_S)
        rec['slot_wait_s'] = round(time.time() - tw, 2)
        if slot is None:
            rec.update(status='skipped', reason=f'busy: {w.MAX_CONCURRENT} calls already running')
            _append_log(state_dir, rec)
            return rec
        held.append(slot)
        if backend is None:
            backend = make_backend(m, state_dir, w)
        capped = CappedBackend(backend, state_dir, m.aml.BackendUnavailable)
        rec['backend'] = capped.name
        rec['credential'] = capped.credential
        rec['child_env_keys'] = sorted(os.environ) if capped.name != 'mock' else None
        tc = time.time()
        try:
            res, resp, tries = m.call_turn(capped, system, prompt, schema, retries=RETRIES,
                                           backoff=2.0, sleep=sleep)
        except m.aml.BackendUnavailable as e:
            if 'daily cap' in str(e):
                rec.update(status='skipped', reason='daily cap', cap=DAILY_CAP, calls=capped.calls)
            else:
                rec.update(status='error', reason='backend unavailable', error=snip(str(e), 300),
                           calls=capped.calls)
            rec['call_s'] = round(time.time() - tc, 2)
            _append_log(state_dir, rec)
            return rec
        except m.aml.TransientError as e:
            rec.update(status='error', reason='call failed', error=snip(str(e), 300),
                       calls=capped.calls, call_s=round(time.time() - tc, 2))
            _append_log(state_dir, rec)
            return rec
        d = m.decide(resp, m.THRESHOLDS, bare=row['bare_approval'])
        meta = res.get('meta') or {}
        rec.update(status='scored', flag=bool(d['flag']), verdict=d['verdict'],
                   drift_score=d['drift_score'], substituted=d['substituted'], by=d['by'],
                   n_asks=d['n_asks'], missing=[snip(x, 100) for x in d['missing'][:6]],
                   why=snip(d['why'], 300), tries=tries, calls=capped.calls,
                   call_s=round(time.time() - tc, 2), cost_usd=meta.get('cost_usd'),
                   model_usage=meta.get('model_usage'), child_session_id=meta.get('session_id'))
    except BaseException as e:                          # noqa: BLE001
        rec.update(status='error', reason=f'worker: {type(e).__name__}', error=snip(str(e), 300))
    rec['total_s'] = round(time.time() - t0, 2)
    try:
        _append_log(state_dir, rec)
    except Exception:
        pass
    return rec


def worker_main():
    job, state_dir = {}, None
    try:
        import signal
        signal.signal(signal.SIGALRM, lambda *_: os._exit(0))
        signal.alarm(WATCHDOG_S)
    except Exception:
        pass
    try:
        raw = sys.stdin.buffer.read(MAX_JOB_BYTES)
        job = json.loads(raw.decode('utf-8', 'replace'))
        state_dir = job['state_dir']
        run_job(job, state_dir)
    except BaseException as e:                          # noqa: BLE001
        if state_dir:
            _log_error(state_dir, job, 'worker', e)
    return 0


if __name__ == '__main__':
    if sys.argv[1:2] == ['--worker']:
        try:
            worker_main()
        finally:
            os._exit(0)
