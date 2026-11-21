#!/usr/bin/env python3
"""lb_askllm_watch.py — the frozen AI-graded ask-mismatch check (askllm), live.

WHAT. Once per helper agent (a subagent or a workflow agent), at its FIRST check_state, the
frozen scorer in research/eval/ask_match_llm.py grades whether the agent set out to do what
the user asked. Offline (research/DAY-FIVE-REAL-SESSIONS.md) it caught 10 of 12 drifted
agents with 1.5% false flags. Start-only variant: there is no final report yet, so
`final_text` is absent.

MODES (LASERBRAIN_ASKLLM_MODE):
  note   (default since the Unreleased entry after 0.58.0) a flag becomes a NOTE: one
         additionalContext line on the flagged agent's next tool call, and one on the parent
         (main) session's next tool call or prompt. Never a block. See deliver_notes().
  watch  the 2026-11-15 behaviour: the verdict is only logged; nothing reaches anyone.
  off    nothing runs. LASERBRAIN_ASKLLM_WATCH=off and <STATE_DIR>/askllm-watch.off still
         switch it off too. An unknown value runs as watch (silent), never as note.

SCORING IS SILENT in every mode: the hook side does a few cheap checks and starts a DETACHED
worker (its own session, stdout and stderr to /dev/null, the job handed over on a pipe that
is closed at once); the worker makes the one Haiku call and appends a line to
<STATE_DIR>/askllm-watch.jsonl. In note mode it also writes the pending note files
(<STATE_DIR>/askllm-notes/<session>/<agent>.agent and .parent, atomically). Delivery runs on
the hook path inside lb_coverage: a stat, and for a session that has notes a directory
listing and one small JSON read. No model call, nothing that can raise into lb_coverage.
Each note is claimed by an atomic rename, so it goes out once even when parallel hook calls
race for it, and each delivery is logged (status note_delivered_agent / note_delivered_parent).
Every pass, helper or main, also expires stale notes (an .agent note after 6 h, a .parent note
after 24 h) and, when the mode is no longer note, drops what is pending (note_dropped_mode), so a
session folder never outlives its notes. The agent's note points it at its TASK, not at a user
message quoted in it (see agent_note_text).

THE WORKER'S ENVIRONMENT is cut to an allowlist (restrict_child_env) before the frozen backend
copies it into `claude -p`; the kept names are logged on each scored line.

THE SCORER IS REUSED, NOT COPIED. The worker loads ask_match_llm.py by absolute path and
uses its MODEL, render(row, 'askllm'), THRESHOLDS, decide(), parse_json/validate (through
call_one) and make_backend('claude') -> ClaudeCLIBackend unchanged: `claude -p` with no
settings sources, disableAllHooks, no tools, no MCP servers, no session persistence and an
empty working directory, so the call cannot re-enter laserbrain's hooks. Before anything
runs, the file's sha256 is compared with the frozen block in eval/day2-llm-results.json
(and, once loaded, prompt_hash('askllm'), MODEL and THRESHOLDS too). Any difference: one
log line, 'skipped: frozen changed', and nothing else.

THE ROW is built the way research/eval/extract_starts.py built the offline rows:
parse_agent() on the agent's own transcript (task, relayed request, plan, early text),
main_user_messages() on the main session transcript (the user's last 6 messages before the
agent started, within 12 hours), every text through research/eval/_common.redact. The goal
is the one this first check_state spelled.

LIMITS. 80 model calls per local day (retries count), at most 2 `claude -p` at once. Off as
above. 60 s per call, one retry, a 300 s watchdog on the worker. Errors are logged, never
raised. The one-week watch window that ended it on 2026-11-22 is replaced by note mode, which
stays on until it is switched off.

STAMPS (since 2026-11-19), so rows from different policies and triggers can be told apart:
every judge row carries `trigger` (what started the job: 'check_state', a helper's first
check) and `policy` (LASERBRAIN_POLICY as the hook saw it, cut to 40 characters, or null when
unset). A row whose prompt was rendered also carries `row_sha`, the first 16 hex digits of
sha256 over system + '\\n' + prompt (UTF-8): the same rendered row gives the same sha, so a
live row can be matched with an offline re-render of it. Rows written before 2026-11-19
have none of the three.

Review: python3 research/eval/askllm_watch_report.py
"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import sys
import time

DAILY_CAP = 80                    # model calls per local day, retries included
CALL_TIMEOUT_S = 60               # per `claude -p` call
RETRIES = 1                       # one retry on a timeout or an unparseable reply
DELAY_S = 30                      # the worker waits this long before reading the agent's
#                                   transcript, so early_text reaches its first acting call
WATCHDOG_S = 300                  # the worker exits after this, whatever it is doing
MAX_CONCURRENT = 2                # `claude -p` runs at once: a workflow that starts 16 agents
#                                   must not start 16 node processes on a Mac that may be
#                                   streaming. Extra workers queue for a slot, then skip.
SLOT_WAIT_S = 90                  # how long a worker queues for a slot (30 + 90 + 2x60 < 300)
MAX_JOB_BYTES = 64_000
SEEN_KEEP = 5000

ENV_SWITCH = 'LASERBRAIN_ASKLLM_WATCH'          # off | 0 | false | no
ENV_MODE = 'LASERBRAIN_ASKLLM_MODE'             # note (default) | watch | off
MODES = ('note', 'watch', 'off')
DEFAULT_MODE = 'note'
ENV_DELAY = 'LASERBRAIN_ASKLLM_WATCH_DELAY'     # seconds (tests use 0)
ENV_MOCK = 'LASERBRAIN_ASKLLM_MOCK_REPLY'       # path to a canned reply: tests, no network
ENV_FROZEN = 'LASERBRAIN_ASKLLM_FROZEN'         # frozen results json (tests)
ENV_EVAL = 'LASERBRAIN_ASKLLM_EVAL_DIR'         # research/eval (tests)
ENV_POLICY = 'LASERBRAIN_POLICY'                # the policy stamp on every judge row
POLICY_CHARS = 40                               # lb_coverage cuts its check-row stamp the same
TRIGGER = 'check_state'                         # the only trigger: a helper's first check

LOG_NAME = 'askllm-watch.jsonl'
SEEN_NAME = 'askllm-watch.seen.json'
OFF_NAME = 'askllm-watch.off'
CLI_DIR_NAME = 'askllm-watch-cli'
NOTES_DIR_NAME = 'askllm-notes'     # <STATE_DIR>/askllm-notes/<session>/<agent>.agent|.parent
NOTE_TTL_S = 6 * 3600               # an agent note nobody picked up by then is dropped
PARENT_NOTE_TTL_S = 24 * 3600       # a parent note too: a session resumed days later gets none
NOTE_REASON_CHARS = 260
PARENT_NOTES_MAX = 4                # per tool call; the rest wait for the next one

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]                          # python/laserbrain/hooks -> repo root

# Env vars that tie a process to the live Claude Code session. A separate headless
# `claude -p` must not claim them; they are dropped from the WORKER's own environment
# before the frozen backend copies it (the backend class itself is unchanged).
SESSION_LINK_ENV = ('CLAUDE_CODE_MESSAGING_SOCKET', 'CLAUDE_CODE_MESSAGING_TOKEN',
                    'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_HOST_SESSION_ID',
                    'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_SESSION_ATTENDED', 'CLAUDE_PID')

# The worker's environment is cut down to this ALLOWLIST before the frozen backend copies it
# into `claude -p` (whose own drop list then removes any credential variable; the backend
# hands the Keychain token over itself). Anything a desktop host sets for its own session
# (effort, simple mode, SDK and auth-refresh flags, a base URL) never reaches the judge, so
# the frozen identity does not depend on which host started the hook. The kept NAMES (never
# values) are logged on every scored line as child_env_keys.
CHILD_ENV_KEEP = ('PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'TMPDIR', 'TZ', 'LANG',
                  'CLAUDE_CONFIG_DIR', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'https_proxy',
                  'http_proxy', 'no_proxy', 'NODE_EXTRA_CA_CERTS', 'SSL_CERT_FILE', 'SSL_CERT_DIR')
CHILD_ENV_KEEP_PREFIX = ('LC_', 'LASERBRAIN_')


def restrict_child_env(environ=None):
    """Drop every variable outside CHILD_ENV_KEEP / CHILD_ENV_KEEP_PREFIX from `environ`
    (os.environ: call it only in the detached worker). Returns the kept names, sorted."""
    env = os.environ if environ is None else environ
    for k in list(env):
        if k not in CHILD_ENV_KEEP and not k.startswith(CHILD_ENV_KEEP_PREFIX):
            env.pop(k, None)
    return sorted(env)


def eval_dir():
    return pathlib.Path(os.environ.get(ENV_EVAL) or (REPO / 'research' / 'eval'))


def frozen_path():
    return pathlib.Path(os.environ.get(ENV_FROZEN) or (REPO / 'eval' / 'day2-llm-results.json'))


def _now():
    return datetime.datetime.now()


def _ts():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


_OFF_WORDS = ('off', '0', 'false', 'no', 'disable', 'disabled')


def switch_reason(state_dir, now=None):
    """None when askllm runs, else why it is off ('env', 'mode', 'file'). `now` is accepted
    for callers of the old signature; nothing expires by date any more."""
    v = (os.environ.get(ENV_SWITCH) or '').strip().lower()
    if v in _OFF_WORDS:
        return 'env'
    if (os.environ.get(ENV_MODE) or '').strip().lower() in _OFF_WORDS:
        return 'mode'
    try:
        if (pathlib.Path(state_dir) / OFF_NAME).exists():
            return 'file'
    except Exception:
        return 'file'
    return None


def mode(state_dir=None):
    """'off', 'note' or 'watch'. Unset is note; an unknown value runs as watch (silent)."""
    if state_dir is not None and switch_reason(state_dir):
        return 'off'
    v = (os.environ.get(ENV_MODE) or '').strip().lower()
    if not v:
        return DEFAULT_MODE
    if v in _OFF_WORDS:
        return 'off'
    return v if v in MODES else 'watch'


# ── shared bookkeeping: one flock'd JSON for markers and the daily count ─────────────

def _with_seen(state_dir, fn):
    """Run fn(d) on <STATE_DIR>/askllm-watch.seen.json under an exclusive lock; fn may mutate d
    and returns a value. Written back in place."""
    import fcntl
    p = pathlib.Path(state_dir) / SEEN_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'a+') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        txt = fh.read()
        try:
            d = json.loads(txt) if txt.strip() else {}
        except Exception:
            d = {}
        if not isinstance(d, dict):
            d = {}
        if not isinstance(d.get('seen'), dict):
            d['seen'] = {}
        if not isinstance(d.get('calls'), dict):
            d['calls'] = {}
        before = json.dumps(d, sort_keys=True)
        out = fn(d)
        if len(d['seen']) > SEEN_KEEP:
            d['seen'] = dict(sorted(d['seen'].items(),
                                    key=lambda kv: str((kv[1] or {}).get('ts', '')))[-SEEN_KEEP:])
        if len(d['calls']) > 30:
            d['calls'] = dict(sorted(d['calls'].items())[-30:])
        if json.dumps(d, sort_keys=True) != before:
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(d))
        return out


def _today(now=None):
    return (now or _now()).date().isoformat()


def calls_today(state_dir, now=None):
    try:
        d = json.loads((pathlib.Path(state_dir) / SEEN_NAME).read_text())
        return int((d.get('calls') or {}).get(_today(now), 0))
    except Exception:
        return 0


def reserve_call(state_dir, cap=DAILY_CAP, now=None):
    """Count one model call against today's cap. False (and nothing counted) at the cap."""
    day = _today(now)

    def fn(d):
        n = int(d['calls'].get(day, 0))
        if n >= cap:
            return False
        d['calls'][day] = n + 1
        return True
    return _with_seen(state_dir, fn)


def _agent_key(sid, agent):
    return f'{sid}:{agent}'


# ── log ─────────────────────────────────────────────────────────────────────────────

def _append_log(state_dir, rec):
    """One O_APPEND write per line, so parallel workers interleave whole lines."""
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
    """research/eval/_common.redact (lb_secrets patterns). A text that cannot be redacted is
    dropped (None), never written as is."""
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
    t = ' '.join(str(text).split())
    r = _redactor()(t, None)
    if r is None:
        return None
    return r if len(r) <= n else r[:n] + '...'


def policy_now():
    """LASERBRAIN_POLICY as this process sees it, cut to POLICY_CHARS, or None when unset."""
    v = os.environ.get(ENV_POLICY)
    return v[:POLICY_CHARS] if v else None


def row_sha(system, prompt):
    """16 hex digits of sha256(system + '\\n' + prompt): the identity of one rendered prompt.
    surrogatepass keeps it from raising on a lone surrogate (a JSON escape can make one); for
    any other text the bytes are plain UTF-8, so an offline re-render gives the same sha."""
    data = f'{system}\n{prompt}'.encode('utf-8', 'surrogatepass')
    return hashlib.sha256(data).hexdigest()[:16]


def _base(job):
    """The fields every judge row starts with. trigger and policy come from the job; a job
    without a policy key (an error before the job was built, a job from an older hook) takes
    this process's LASERBRAIN_POLICY."""
    return {'ts': _ts(), 'session': job.get('session'), 'agent_id': job.get('agent_id'),
            'agent_type': job.get('agent_type'), 'lane': job.get('lane'),
            'variant': 'start-only', 'trigger': job.get('trigger') or TRIGGER,
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


# ── notes (note mode): written by the worker, delivered by lb_coverage ──────────────

def safe_name(s):
    """A session or agent id as one path component. lb_coverage has a copy of this rule
    (its fast-path stat must name the same folder); test_askllm_notes.py pins the two."""
    return re.sub(r'[^A-Za-z0-9._-]', '_', str(s or 'unknown'))[:120] or 'unknown'


def notes_dir(state_dir, sid):
    return pathlib.Path(state_dir) / NOTES_DIR_NAME / safe_name(sid)


def _write_json_atomic(path, obj):
    path = pathlib.Path(path)
    for attempt in (0, 1):                 # the folder may be removed under us once (rmdir)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
            with open(tmp, 'w', encoding='utf-8') as fh:
                fh.write(json.dumps(obj, ensure_ascii=False))
            os.replace(tmp, path)
            return True
        except FileNotFoundError:
            if attempt:
                raise
    return False


def write_note(state_dir, job, rec):
    """Pending note files for a flagged agent: <agent>.agent and <agent>.parent. Never raises."""
    try:
        body = {'session': job.get('session'), 'agent_id': job.get('agent_id'),
                'label': rec.get('label'), 'lane': rec.get('lane') or job.get('lane'),
                'workflow': rec.get('workflow'), 'workflow_name': rec.get('workflow_name'),
                'where': rec.get('where'), 'verdict': rec.get('verdict'),
                'drift_score': rec.get('drift_score'), 'missing': rec.get('missing') or [],
                'why': rec.get('why'), 'written_ts': _ts(), 'written_epoch': time.time()}
        d = notes_dir(state_dir, job.get('session'))
        a = safe_name(job.get('agent_id'))
        _write_json_atomic(d / f'{a}.agent', body)
        _write_json_atomic(d / f'{a}.parent', body)
        return 'written'
    except Exception as e:                              # noqa: BLE001
        return f'error: {type(e).__name__}'


def _short(text, n=NOTE_REASON_CHARS):
    t = ' '.join(str(text or '').split()).strip()
    return t if len(t) <= n else t[:n - 3].rstrip() + '...'


def note_reason(body):
    """The scorer's missing asks and reason, short. Both were redacted when the row was logged."""
    parts = []
    miss = [str(m) for m in (body.get('missing') or []) if m][:3]
    if miss:
        parts.append('Left out: ' + '; '.join(miss) + '.')
    if body.get('why'):
        parts.append(str(body['why']).strip())
    return _short(' '.join(parts) or f"verdict {body.get('verdict') or 'drift'}").rstrip('.')


def agent_note_text(body):
    """Points the agent at its TASK, never at the user message quoted in it: askllm's own prompt
    treats the task as the authority, and the drifts it caught (DAY-FIVE §2-3) were helpers that
    took a quoted user message, older or about something else, for their job. The asks in
    `missing` are asks of the task."""
    return ('laserbrain (askllm): your goal may leave out part of the task you were handed. '
            f'{note_reason(body)}. The task text is what you were asked to do; a user message '
            'quoted in it can be older or about something else. Re-read the task before '
            'continuing; if you are sure you are on it, carry on.')


def parent_note_text(body):
    who = body.get('label') or body.get('lane') or body.get('agent_id') or 'a helper'
    wf = body.get('workflow_name') or body.get('workflow')
    where = f' in {wf}' if wf else ''
    return (f'laserbrain: helper {_short(who, 80)}{where} may be off its task: '
            f'{note_reason(body)}. Check its result against the task you gave it and the user\'s ask.')


def _claim(path):
    """The note's body if this process claimed it, else None. Claimed by renaming it, which
    exactly one racing process can do; an unreadable file is set aside and never delivered."""
    try:
        body = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
        if not isinstance(body, dict):
            raise ValueError('not an object')
    except FileNotFoundError:
        return None
    except Exception:
        try:                                            # out of the session folder, kept for a look
            p = pathlib.Path(path)
            aside = p.parent.parent / '_set-aside'
            aside.mkdir(parents=True, exist_ok=True)
            os.replace(p, aside / f'{p.parent.name}__{p.name}.corrupt')
        except Exception:
            pass
        return None
    claimed = f'{path}.claimed-{os.getpid()}'
    try:
        os.rename(path, claimed)
    except Exception:
        return None                                     # another hook call got it first
    try:
        os.unlink(claimed)
    except Exception:
        pass
    return body


def _delivered(state_dir, body, status, event, **extra):
    try:
        we = float(body.get('written_epoch') or 0)
        rec = {'ts': _ts(), 'status': status, 'session': body.get('session'),
               'agent_id': body.get('agent_id'), 'label': body.get('label'),
               'workflow': body.get('workflow'), 'event': event,
               'note_written_ts': body.get('written_ts'),
               'delay_s': round(time.time() - we, 1) if we else None}
        rec.update(extra)
        _append_log(state_dir, rec)
    except Exception:
        pass


def _age(path, t_now):
    try:
        return t_now - path.stat().st_mtime
    except Exception:
        return None


def deliver_notes(ev, state_dir, event=None, now=None):
    """Note texts to hand this tool call or prompt as additionalContext, each claimed once.
    A helper agent's call takes its own <agent>.agent note; a main-session call or prompt takes
    the session's pending .parent notes. [] when there are none, when notes are off, and on any
    error. Never raises; no model call, no transcript read.

    Housekeeping runs on EVERY pass, helper or main, so a session folder never outlives its
    notes: an .agent note older than NOTE_TTL_S and a .parent note older than PARENT_NOTE_TTL_S
    expire (note_expired_agent / note_expired_parent) instead of going out, and when the mode is
    not note (watch, off, either off switch) every pending note is dropped (note_dropped_mode).
    The folder is removed once it is empty, so afterwards each call costs one stat again."""
    try:
        sid = ev.get('session_id') or ev.get('sessionId')
        if not sid:
            return []
        d = notes_dir(state_dir, sid)
        if not d.is_dir():
            return []
        t_now = now if now is not None else time.time()
        md = mode(state_dir)
        agent = ev.get('agent_id') or ev.get('agentId')
        mine = f'{safe_name(agent)}.agent' if agent else None
        out = []
        for n in sorted(os.listdir(d)):
            p = d / n
            kind = 'agent' if n.endswith('.agent') else 'parent' if n.endswith('.parent') else None
            if kind is None:
                continue
            if md != 'note':
                body = _claim(p)
                if body is not None:
                    _delivered(state_dir, body, 'note_dropped_mode', event, kind=kind, mode=md)
                continue
            age = _age(p, t_now)
            ttl = NOTE_TTL_S if kind == 'agent' else PARENT_NOTE_TTL_S
            if age is not None and age > ttl:
                body = _claim(p)
                if body is not None:
                    _delivered(state_dir, body, f'note_expired_{kind}', event)
                continue
            if kind == 'agent' and n == mine:
                body = _claim(p)
                if body is not None:
                    out.append(agent_note_text(body))
                    _delivered(state_dir, body, 'note_delivered_agent', event)
            elif kind == 'parent' and not agent and len(out) < PARENT_NOTES_MAX:
                body = _claim(p)
                if body is not None:
                    out.append(parent_note_text(body))
                    _delivered(state_dir, body, 'note_delivered_parent', event)
        try:
            os.rmdir(d)                                 # only succeeds once nothing is pending
        except OSError:
            pass
        return out
    except BaseException:                               # noqa: BLE001 — never into lb_coverage
        return []


# ── hook side: cheap, never raises, never prints ────────────────────────────────────

def _sidecar_checks(state_dir, sid, agent):
    """This agent's check count in lb_coverage's <sid>.agents.json (nudge mode), or None."""
    try:
        d = json.loads((pathlib.Path(state_dir) / f'{sid}.agents.json').read_text())
        e = d.get(agent)
        return int(e.get('checks', 0)) if isinstance(e, dict) else None
    except Exception:
        return None


def _spawn(job):
    """Start the detached worker and hand it the job on a pipe. Returns at once."""
    import subprocess
    argv = [sys.executable] + (['-P'] if sys.version_info >= (3, 11) else []) + \
        [str(pathlib.Path(__file__).resolve()), '--worker']
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
                         cwd=str(job['state_dir']))
    return p


def on_post_tool_use(ev, tool, args, state_dir, now=None):
    """lb_coverage calls this on a successful PostToolUse. Returns a short status (for tests).

    Spawns the worker only for a helper agent's FIRST check_state: the payload names an
    agent_id (Claude Code sets it only inside a subagent, so the main session never
    qualifies), the transcript exists, this agent has no marker yet, and lb_coverage's
    per-agent sidecar (when it has this agent) counts this as its first check.
    """
    t0 = time.perf_counter()
    job = None
    try:
        agent = ev.get('agent_id') or ev.get('agentId')
        if not agent:
            return 'main'
        if not str(tool or '').lower().endswith('check_state'):
            return 'not-check'
        if switch_reason(state_dir, now):
            return 'off'
        # The same early return as lb_turnwatch's: with no frozen scorer or frozen block on
        # disk (an installed wheel has neither research/eval nor eval/), the worker could only
        # log a skip, so no process is started at all.
        if not (eval_dir() / 'ask_match_llm.py').is_file() or not frozen_path().is_file():
            return 'no-judge'
        tp = ev.get('transcript_path') or ev.get('transcriptPath')
        if not tp or not os.path.exists(str(tp)):
            return 'no-transcript'
        args = args if isinstance(args, dict) else {}
        sid = str(ev.get('session_id') or ev.get('sessionId') or 'unknown')
        agent = str(agent)
        key = _agent_key(sid, agent)
        n_checks = _sidecar_checks(state_dir, sid, agent)
        day = _today(now)
        stamp = _ts()

        def fn(d):
            if key in d['seen']:
                return 'seen'
            if n_checks is not None and n_checks > 1:
                d['seen'][key] = {'ts': stamp, 'st': 'not-first'}
                return 'not-first'
            if int(d['calls'].get(day, 0)) >= DAILY_CAP:
                d['seen'][key] = {'ts': stamp, 'st': 'cap'}
                return 'cap'
            d['seen'][key] = {'ts': stamp, 'st': 'spawned'}
            return 'spawn'
        st = _with_seen(state_dir, fn)
        job = {'session': sid, 'agent_id': agent,
               'agent_type': ev.get('agent_type') or ev.get('agentType'),
               'lane': str(args.get('session'))[:80] if args.get('session') else None,
               'tool_use_id': ev.get('tool_use_id') or ev.get('toolUseId'),
               'transcript_path': str(tp), 'cwd': ev.get('cwd'),
               'goal': str(args.get('goal'))[:2000] if args.get('goal') is not None else None,
               'hook_ts': stamp, 'state_dir': str(state_dir), 'mode': mode(state_dir),
               'trigger': TRIGGER, 'policy': policy_now()}
        if st == 'cap':
            rec = _base(job)
            rec.update(status='skipped', reason='daily cap', cap=DAILY_CAP)
            _append_log(state_dir, rec)
            return 'cap'
        if st != 'spawn':
            return st
        p = _spawn(job)
        job['hook_ms'] = round((time.perf_counter() - t0) * 1000, 1)
        data = json.dumps(job).encode('utf-8', 'replace')[:MAX_JOB_BYTES]
        try:
            p.stdin.write(data)
            p.stdin.close()
        except Exception:
            pass
        return 'spawned'
    except BaseException as e:                          # noqa: BLE001 — never into lb_coverage
        _log_error(state_dir, job or {'session': (ev or {}).get('session_id'),
                                      'agent_id': (ev or {}).get('agent_id')}, 'hook', e, hook=True)
        return 'error'


# ── worker side: the one model call ─────────────────────────────────────────────────

def load_frozen():
    """(ask_match_llm module, None, info) when nothing frozen changed, else (None, reason, info).

    The file's sha256 is checked BEFORE it is executed; prompt_hash, MODEL and THRESHOLDS
    after, against the frozen block of eval/day2-llm-results.json.
    """
    import importlib.util as ilu
    src = eval_dir() / 'ask_match_llm.py'
    info = {}
    try:
        fz = json.loads(frozen_path().read_text()).get('frozen') or {}
    except Exception as e:
        return None, 'frozen block unreadable', {'error': type(e).__name__}
    try:
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
    except Exception as e:
        return None, 'frozen scorer not found', {'error': type(e).__name__}
    info['file_sha'] = sha
    if sha != fz.get('ask_match_llm_sha256'):
        return None, 'frozen changed', {**info, 'bad': ['ask_match_llm_sha256']}
    ed = str(src.parent)
    if ed not in sys.path:
        sys.path.insert(0, ed)
    spec = ilu.spec_from_file_location('ask_match_llm', str(src))
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    ph = m.prompt_hash('askllm')
    info.update(prompt_hash=ph, model=m.MODEL)
    bad = []
    if m.file_sha() != fz.get('ask_match_llm_sha256'):
        bad.append('ask_match_llm_sha256')
    if ph != (fz.get('prompt_hash') or {}).get('askllm'):
        bad.append('prompt_hash')
    if m.MODEL != fz.get('model'):
        bad.append('model')
    if m.THRESHOLDS != fz.get('thresholds'):
        bad.append('thresholds')
    if bad:
        return None, 'frozen changed', {**info, 'bad': bad}
    return m, None, info


def resolve(job):
    """{'main', 'agent', 'session_dir', 'workflow'} for the job's transcripts (paths or None).

    transcript_path in a subagent's hook payload is the MAIN session's transcript (the CLI
    gives the agent's own path only on SubagentStop, as agent_transcript_path). The agent's
    transcript is <session dir>/subagents/agent-<id>.jsonl, or
    <session dir>/subagents/workflows/wf_*/agent-<id>.jsonl for a workflow agent.
    """
    tp = pathlib.Path(job['transcript_path'])
    agent = str(job['agent_id'])
    main = sdir = None
    if tp.name == f'agent-{agent}.jsonl':               # an agent's own path, if a host sends it
        for parent in tp.parents:
            if parent.name == str(job.get('session')):
                sdir, main = parent, parent.with_suffix('.jsonl')
                break
        agent_path = tp
    else:
        main, sdir = tp, tp.with_suffix('')
        agent_path = None
        cands = [sdir / 'subagents' / f'agent-{agent}.jsonl'] + \
            sorted((sdir / 'subagents' / 'workflows').glob(f'wf_*/agent-{agent}.jsonl'))
        for c in cands:
            if c.exists():
                agent_path = c
                break
    wf = agent_path.parent.name if agent_path and agent_path.parent.name.startswith('wf_') else None
    return {'main': main if main and main.exists() else None, 'agent': agent_path,
            'session_dir': sdir, 'workflow': wf}


def check_ids(agent_path):
    """tool_use ids of the agent's check_state calls, in order."""
    ids = []
    with open(agent_path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if 'check_state' not in line or '"assistant"' not in line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('type') != 'assistant':
                continue
            for b in (r.get('message') or {}).get('content') or []:
                if isinstance(b, dict) and b.get('type') == 'tool_use' \
                        and str(b.get('name') or '').endswith('check_state'):
                    ids.append(b.get('id'))
    return ids


def build_row(job, paths, es):
    """The offline row shape (extract_starts.starts_for_session), for one live start."""
    a = es.parse_agent(paths['agent']) or {}
    start_ts = a.get('start_ts') or job.get('hook_ts')
    users = es.main_user_messages(paths['main']) if paths['main'] else []
    before = [u for u in users if es._ts_key(u[0]) <= es._ts_key(start_ts)]
    recent = [u for u in before[-es.RECENT_N:]
              if (es._hours_between(u[0], start_ts) or 0) <= es.RECENT_WINDOW_H]
    redact = _redactor()
    row = {'id': f"{str(job['session'])[:8]}:{paths['workflow'] or '-'}:{str(job['agent_id'])[:10]}",
           'user_recent': [{'ts': u[0], 'kind': u[1], 'text': redact(u[2], 2000)} for u in recent],
           'user_relayed': a.get('user_relayed'), 'task': a.get('task'),
           'goal': job.get('goal') if job.get('goal') is not None else a.get('goal'),
           'plan': a.get('plan'), 'early_text': a.get('early_text'), 'final_text': None,
           'start_ts': start_ts}
    for k in ('user_relayed', 'task', 'goal', 'plan', 'early_text'):
        row[k] = redact(row[k], es.TEXT_CAP) if row[k] is not None else None
    return row


def _meta(paths):
    out = {'label': None, 'phase': None, 'meta_agent_type': None, 'workflow_name': None}
    try:
        if paths['agent']:
            mp = paths['agent'].with_suffix('.meta.json')
            if mp.exists():
                md = json.loads(mp.read_text())
                out.update(label=md.get('description'), phase=md.get('workflowPhase'),
                           meta_agent_type=md.get('agentType'))
        if paths['workflow'] and paths['session_dir']:
            wj = paths['session_dir'] / 'workflows' / f"{paths['workflow']}.json"
            if wj.exists():
                out['workflow_name'] = json.loads(wj.read_text()).get('workflowName')
    except Exception:
        pass
    return out


class CappedBackend:
    """Counts every call against the daily cap before passing it to the frozen backend."""

    def __init__(self, inner, state_dir, unavailable, cap=DAILY_CAP):
        self.inner, self.state_dir, self.cap = inner, state_dir, cap
        self.unavailable = unavailable
        self.name = getattr(inner, 'name', '?')
        self.model = getattr(inner, 'model', None)
        self.credential = getattr(inner, 'credential', None)
        self.calls = 0

    def call(self, system, prompt, schema):
        if not reserve_call(self.state_dir, self.cap):
            raise self.unavailable('daily cap reached')
        self.calls += 1
        return self.inner.call(system, prompt, schema)


def _claude_binary():
    """A `claude` executable when the hook's PATH has none (hooks can run with a short
    PATH), else None. Nothing is printed."""
    home = pathlib.Path.home()
    for c in (os.environ.get('CLAUDE_CODE_EXECPATH') or '', str(home / '.local' / 'bin' / 'claude'),
              str(home / '.claude' / 'local' / 'claude'), '/opt/homebrew/bin/claude',
              '/usr/local/bin/claude'):
        if c and os.path.basename(c).startswith('claude') and os.path.isfile(c) \
                and os.access(c, os.X_OK):
            return c
    return None


def make_backend(m, state_dir):
    """The frozen file's own backend: make_backend('claude') when `claude` is on PATH, else
    the same ClaudeCLIBackend construction with the binary found by path."""
    import shutil
    mock = os.environ.get(ENV_MOCK)
    if mock:
        text = pathlib.Path(mock).read_text()
        return m.MockBackend(lambda system, prompt, schema: text)
    cache_dir = pathlib.Path(state_dir) / CLI_DIR_NAME
    on_path = shutil.which('claude')
    binary = None if on_path else _claude_binary()     # reads CLAUDE_CODE_EXECPATH: before the cut
    restrict_child_env()                               # SESSION_LINK_ENV and the rest go here
    if on_path:
        return m.make_backend('claude', m.MODEL, CALL_TIMEOUT_S, cache_dir=cache_dir)
    if not binary:
        raise m.BackendUnavailable('claude CLI not found on PATH')
    return m.ClaudeCLIBackend(m.MODEL, CALL_TIMEOUT_S, token=m.keychain('claude-oauth-token'),
                              workdir=cache_dir / 'cli-cwd', binary=binary)


def acquire_slot(state_dir, sleep=time.sleep, wait_s=None, n=None):
    """An open, flock'd slot file (hold it for the call), or None after wait_s. Never raises.
    The lock is released when the handle is closed or the process exits, so a worker killed
    by the watchdog cannot leak a slot."""
    import fcntl
    wait_s = SLOT_WAIT_S if wait_s is None else wait_s
    n = n or MAX_CONCURRENT
    waited = 0.0
    try:
        pathlib.Path(state_dir).mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    while True:
        for i in range(n):
            try:
                fh = open(pathlib.Path(state_dir) / f'askllm-watch.slot{i}.lock', 'a')
            except Exception:
                return None
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fh
            except OSError:
                fh.close()
        if waited >= wait_s:
            return None
        sleep(2)
        waited += 2


def run_job(job, state_dir=None, backend=None, delay=None, now=None, sleep=time.sleep):
    """Score one start and append one line. Never raises. Returns the logged record."""
    held = []
    try:
        return _run_job(job, state_dir, backend, delay, now, sleep, held)
    finally:
        for fh in held:
            try:
                fh.close()
            except Exception:
                pass


def _run_job(job, state_dir, backend, delay, now, sleep, held):
    state_dir = pathlib.Path(state_dir or job['state_dir'])
    t0 = time.time()
    rec = _base(job)
    rec['hook_ms'] = job.get('hook_ms')
    try:
        if switch_reason(state_dir, now):
            return None
        m, why, info = load_frozen()
        rec['frozen_sha'] = info.get('file_sha')
        rec['prompt_hash'] = info.get('prompt_hash')
        if m is None:
            rec.update(status='skipped', reason=why, frozen_bad=info.get('bad'))
            _append_log(state_dir, rec)
            return rec
        rec['model'] = m.MODEL
        import extract_starts as es           # research/eval, on sys.path via load_frozen
        paths = resolve(job)
        rec['workflow'] = paths['workflow']
        rec['session_dir'] = str(paths['session_dir']) if paths['session_dir'] else None
        if not paths['agent']:
            if delay is None:
                delay = float(os.environ.get(ENV_DELAY) or DELAY_S)
            sleep(min(delay, 10))                # a transcript may lag its first hook
            paths = resolve(job)
        if not paths['agent']:
            rec.update(status='skipped', reason='agent transcript not found')
            _append_log(state_dir, rec)
            return rec
        ids = check_ids(paths['agent'])
        mine = job.get('tool_use_id')
        if ids and ((mine and ids[0] != mine) or (not mine and len(ids) > 1)):
            rec.update(status='skipped', reason='not first check_state', n_checks_seen=len(ids))
            _append_log(state_dir, rec)
            return rec
        if delay is None:
            delay = float(os.environ.get(ENV_DELAY) or DELAY_S)
        if delay > 0:
            sleep(delay)
        rec['delay_s'] = delay
        # The switch is read again after the wait: turning the watch off must stop a worker
        # that is already waiting, not only the ones started afterwards.
        off = switch_reason(state_dir, now)
        if off:
            rec.update(status='skipped', reason=f'switched off during wait ({off})')
            _append_log(state_dir, rec)
            return rec
        rec.update(_meta(paths))
        row = build_row(job, paths, es)
        rec['start_ts'] = row['start_ts']
        rec['inputs'] = {'user_recent': len(row['user_recent']),
                         'user_relayed': bool(row['user_relayed']), 'task': bool(row['task']),
                         'goal': bool(row['goal']), 'early_text': bool(row['early_text']),
                         'plan': bool(row['plan']), 'final_text': False}
        rec['snippets'] = {'goal': snip(row['goal'], 160), 'relayed': snip(row['user_relayed'], 160),
                           'task': snip(row['task'], 200),
                           'latest_user': snip((row['user_recent'] or [{}])[-1].get('text'), 160)}
        if not row['task']:
            rec.update(status='skipped', reason='no task in agent transcript')
            _append_log(state_dir, rec)
            return rec
        system, prompt, schema = m.render(row, 'askllm')
        rec['row_sha'] = row_sha(system, prompt)
        tw = time.time()
        slot = acquire_slot(state_dir, sleep)
        rec['slot_wait_s'] = round(time.time() - tw, 2)
        if slot is None:
            rec.update(status='skipped', reason=f'busy: {MAX_CONCURRENT} calls already running')
            _append_log(state_dir, rec)
            return rec
        held.append(slot)
        if backend is None:
            backend = make_backend(m, state_dir)
        capped = CappedBackend(backend, state_dir, m.BackendUnavailable)
        rec['backend'] = capped.name
        rec['credential'] = capped.credential
        rec['child_env_keys'] = sorted(os.environ) if capped.name != 'mock' else None
        tc = time.time()
        try:
            res, resp, tries = m.call_one(capped, system, prompt, schema, 'askllm',
                                          retries=RETRIES, backoff=2.0)
        except m.BackendUnavailable as e:
            if 'daily cap' in str(e):
                rec.update(status='skipped', reason='daily cap', cap=DAILY_CAP, calls=capped.calls)
            else:
                rec.update(status='error', reason='backend unavailable', error=snip(str(e), 300),
                           calls=capped.calls)
            rec['call_s'] = round(time.time() - tc, 2)
            _append_log(state_dir, rec)
            return rec
        except m.TransientError as e:
            rec.update(status='error', reason='call failed', error=snip(str(e), 300),
                       calls=capped.calls, call_s=round(time.time() - tc, 2))
            _append_log(state_dir, rec)
            return rec
        d = m.decide('askllm', resp)
        meta = res.get('meta') or {}
        rec.update(status='scored', flag=bool(d['flag']), where=d['where'], verdict=d['verdict'],
                   drift_score=d['drift_score'], n_asks_in_task=d['n_asks_in_task'],
                   missing=[snip(x, 100) for x in d['missing'][:8]],
                   why=snip(resp.get('why'), 300),
                   reply_flags={k: resp.get(k) for k in ('relay_unrelated', 'goal_follows_relay_scope',
                                                         'start_substituted', 'end_declined')},
                   tries=tries, calls=capped.calls, call_s=round(time.time() - tc, 2),
                   cost_usd=meta.get('cost_usd'), model_usage=meta.get('model_usage'),
                   child_session_id=meta.get('session_id'))      # the throwaway `claude -p` run
        # NOTE MODE: a flag becomes a pending note for the agent and its parent. The mode is
        # read again here, so switching to watch or off while the call ran writes no note.
        rec['mode'] = mode(state_dir)
        if rec['flag'] and rec['mode'] == 'note':
            rec['note'] = write_note(state_dir, job, rec)
    except BaseException as e:                          # noqa: BLE001
        rec.update(status='error', reason=f'worker: {type(e).__name__}', error=snip(str(e), 300))
    rec['total_s'] = round(time.time() - t0, 2)
    try:
        _append_log(state_dir, rec)
    except Exception:
        pass
    return rec


def worker_main():
    job = {}
    state_dir = None
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
