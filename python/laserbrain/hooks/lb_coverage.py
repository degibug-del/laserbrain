#!/usr/bin/env python3
"""lb_coverage.py — PostToolUse / PostToolUseFailure / UserPromptSubmit / Stop hook for laserbrain coverage.

Makes coverage automatic instead of remembered. Reads both snake_case and camelCase
hook payloads, so it works for any host that emits either.

WHY THIS EXISTS. On 2026-07-24 a long, error-dense session produced ten independently
caught errors and ONE laserbrain check across ~48 steps — 2% coverage. The agent
had a standing order to call check_state each step and did not. That is not a
discipline problem to be solved by more discipline: "remember to call it every step"
is not an interface.

WHAT IT CAN AND CANNOT DO. A hook is a shell command; it cannot spell the agent's
goal, progress or distance, so it cannot call check_state on the agent's behalf.
What it can do is:

  1. COUNT the steps (dogfood denominator).
  2. LOG catches it can see (failed calls, red test verdicts).
  3. INTERRUPT when coverage lapses:
       - hosts that read PostToolUse stdout: additionalContext
       - hosts that ignore it: a Stop gate with decision=block under
         LASERBRAIN_GATE_MODE=hard; by default (nudge) the same text as non-blocking
         context, the would-be block logged as stage nudge-stop
  4. ATTRIBUTE steps per agent (nudge mode): <session>.agents.json, keyed by the payload's
     agent_id, so parallel subagents do not spend each other's step budget.

SAFETY. Every path is wrapped; exits 0 unconditionally except intentional stop-blocks.
A hook that crashes the tool it observes is worse than no hook.
"""
import json, os, re, sys, pathlib, datetime

# ONE STATE ROOT — see lb_paths.py. Loaded by absolute path rather than by name: this
# hook is invoked from settings.json, from a synced copy under ~/.grok, and from
# tests in another directory, so `import lb_paths` would resolve only sometimes.
import importlib.util as _ilu
_paths = None
try:
    _spec = _ilu.spec_from_file_location(
        'lb_paths', str(pathlib.Path(__file__).resolve().parent / 'lb_paths.py'))
    _paths = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_paths)
except Exception as _e:                              # noqa: BLE001
    # A HOOK MUST STILL LOAD. lb_paths.py is a FOURTH file the hooks now depend on, and
    # every way this file travels copies a fixed list: sync_from_icloud.sh named three, and
    # test_proportional_gate copies lb_gate.py alone into a temp directory to corrupt it.
    # An ImportError at module scope happens ABOVE the handler that exists to fail open, so
    # a missing sibling would not fail open — it would take the hook out entirely, and on
    # the Grok host that reads as a deadlock rather than as a missing file.
    #
    # So: fall back to the historical defaults, which is what an unset environment resolves
    # to anyway, and SAY SO. Silent degradation here would mean two hosts writing to
    # different roots with nothing to indicate it.
    import sys as _sys, types as _t
    print(f'laserbrain: lb_paths.py unavailable ({type(_e).__name__}: {_e}) — using the '
          f'historical defaults; LASERBRAIN_HOME will be IGNORED in this process. '
          f'Run sync_from_icloud.sh.', file=_sys.stderr)
    _paths = _t.SimpleNamespace(
        home=lambda: None,
        config_dir=lambda: pathlib.Path.home() / '.config' / 'laserbrain',   # one-root: fallback
        sessions_dir=lambda: pathlib.Path(
            os.environ['LASERBRAIN_STATE_DIR']).expanduser()
            if os.environ.get('LASERBRAIN_STATE_DIR')
            else pathlib.Path.home() / '.claude' / 'laserbrain',   # one-root: fallback
        config=lambda *p: (pathlib.Path.home() / '.config' / 'laserbrain').joinpath(*p))  # one-root: fallback

NUDGE_AFTER = 8
WINDOW, REPEAT, FAILS = 6, 3, 2   # must match laserbrain.observe — test_hook_parity.py pins this
# Shared corpus. The path names one host for historical reasons and holds EVERY agent's
# rows; moving it would orphan the existing corpus, so it stays.
# Overridable so the instrument can be run UNDER TEST without writing into the corpus it
# is measured against. laserbrain-trial runs the real hooks in both arms; without this every
# trial run would append synthetic sessions to the shared record that corpus-map.py
# summarises and the paper renders its figures from. Default is unchanged, so nothing that
# does not set the variable behaves differently.
STATE_DIR = pathlib.Path(os.environ.get('LASERBRAIN_STATE_DIR')
                         or _paths.sessions_dir())
# Written when the user speaks, consumed by mcp-server.mjs on the next check_state. A file
# rather than shared memory because the hook and the MCP server are separate processes with
# no channel between them; this is the whole channel.
USER_TURN = _paths.config('user-turn')


def _mark_user_turn():
    """The user just spoke, so the next check_state is a re-ground rather than a drift.

    Called from BOTH the primary path and the embedded fallback. They are separate routes
    through this hook and only one runs on any given invocation, which is precisely how
    the first attempt at this fix came to be inert: it was written into the fallback only.
    """
    try:
        USER_TURN.parent.mkdir(parents=True, exist_ok=True)
        # UTC, matching the drift log's new Date().toISOString(). They disagreed until
        # 2026-07-26, and the cost was a wrong diagnosis: a goal-drift fire logged at
        # 01:25 UTC was compared against a flag stamped 19:36 local, which made a fire
        # that happened BEFORE the flag look like it happened seven hours after — i.e.
        # like reground was broken when it was working correctly. One clock per system.
        USER_TURN.write_text(
            datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'))
    except Exception:
        pass          # fail open: a missing flag only restores the old behaviour


# Byte offsets of the transcripts already scanned for queued messages, keyed by path.
QUEUE_SCAN = _paths.config('queue-scan.json')

# EVERY MOMENT THE USER SPOKE, kept by laserbrain itself. USER_TURN above holds only the
# latest one, for the reground. calibrate_attention.py measures drift against the time since
# the user last spoke, and it read those moments from the host's transcripts, which Claude
# Code deletes after cleanupPeriodDays (30 by default). On 2026-10-29 every one of the 3243
# user turns behind the shipped attention.json (2026-07-28..08-22) was gone, and 866 of 913
# readings had nothing left to be measured against. The drift log survived because laserbrain
# owns it; this is the other half of the join, owned the same way. One line per enqueue
# record: its own timestamp, and whether it was the user or a <task-notification>.
USER_TURNS = pathlib.Path(os.environ.get('LASERBRAIN_USER_TURNS') or _paths.config('user-turns.jsonl'))
# A transcript seen for the first time has its history recorded too when it is small, which
# is every new session (its first tool call follows its first prompt). A large one is a long
# session the hook had stopped tracking (QUEUE_SCAN keeps the 40 most recently seen); reading
# it all would stall the tool call, so it is left to the daily catch-up below.
TURNS_FIRST_SIGHT_MAX = 4 * 1024 * 1024


def _record_turns(turns, sid):
    """Append (timestamp, kind) pairs to USER_TURNS in one O_APPEND write, so the hooks of
    parallel subagents interleave whole lines rather than torn ones. A line written twice is
    harmless: readers keep one per timestamp."""
    try:
        USER_TURNS.parent.mkdir(parents=True, exist_ok=True)
        data = ''.join(json.dumps({'ts': ts, 'kind': kind, 'sid': sid, 'src': 'hook'}) + '\n'
                       for ts, kind in turns).encode()
        fd = os.open(str(USER_TURNS), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except Exception:
        pass          # fail open: --harvest recovers it while the transcript still exists


HARVEST_DAY = _paths.config('turns-harvest.day')


def _daily_harvest(ev):
    """Once a day, at a user prompt, copy what the transcripts hold into USER_TURNS in the
    background (python -m laserbrain.turns). The scan below only sees transcripts that run
    this hook after a tool call; a session answered without tools, or one on a host without
    the hook, would otherwise keep its turns only until the host deletes the transcript.
    Detached, so the prompt never waits on it. Only for the default state root: a relocated
    LASERBRAIN_HOME is a test or a sandbox (LASERBRAIN_TURNS_HARVEST=1 forces it, =0 stops it)."""
    flag = os.environ.get('LASERBRAIN_TURNS_HARVEST')
    if flag == '0' or (flag != '1' and os.environ.get('LASERBRAIN_HOME')):
        return
    if _event_name(ev) != 'userpromptsubmit':        # _event_name lowercases
        return
    try:
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        if HARVEST_DAY.exists() and HARVEST_DAY.read_text().strip() == today:
            return
        HARVEST_DAY.parent.mkdir(parents=True, exist_ok=True)
        HARVEST_DAY.write_text(today)
        import subprocess
        subprocess.Popen([sys.executable] + (['-P'] if sys.version_info >= (3, 11) else [])
                         + ['-m', 'laserbrain.turns', '--quiet'],
                         cwd=str(pathlib.Path.home()), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass          # fail open: tomorrow's prompt tries again, and --harvest still works by hand


def _mark_user_turn_if_queued(ev):
    """Catch mid-turn messages, which never reach the UserPromptSubmit hook at all.

    Measured 2026-07-30 over a full session: 37 top-level user messages produced exactly
    37 UserPromptSubmit firings, a clean 1:1 — while four messages typed *while the agent
    was working* produced none. They are not user events as far as the hook is concerned;
    the transcript records them as `{"type": "queue-operation", "operation": "enqueue"}`.
    So every redirection issued mid-turn left the ground unchanged and was then measured
    as drift against the goal it had just replaced.

    `promptId` is no help here — it is stamped per top-level turn and stays fixed across
    the queued messages inside one (verified on the same session), so a change in it can
    never signal an arrival. The enqueue record is the only first-hand evidence, and the
    transcript path rides along on every PostToolUse payload.

    Scans only the bytes appended since the last look, and on first sight of a transcript
    never fires on what is already there — otherwise the initial scan would replay every
    historical enqueue at once and reground on ancient history. (Since 2026-10-29 a first
    sight of a transcript up to TURNS_FIRST_SIGHT_MAX does READ it, to copy its history into
    USER_TURNS; it still re-grounds on none of it.)
    """
    path = ev.get('transcript_path') or ev.get('transcriptPath')
    if not path:
        return
    try:
        transcript = pathlib.Path(path)
        size = transcript.stat().st_size
    except Exception:
        return

    try:
        state = json.loads(QUEUE_SCAN.read_text())
        if not isinstance(state, dict):
            state = {}
    except Exception:
        state = {}

    key = str(path)
    first_sight = key not in state
    offset = state.get(key, 0)
    if not isinstance(offset, int) or offset > size:
        offset = 0            # truncated or rotated out from under us
    if offset == size and not first_sight:
        return

    found = False
    turns = []        # (timestamp, kind) for USER_TURNS: the record keeps every enqueue
    # Outside nudge mode a notification still counts, as it did before 2026-10-16: hard,
    # watch and signal reproduce the old hook byte for byte, and this flag is one of the files
    # it writes (a checker found 11 hard-mode differences per run when the filter ran there).
    skip_notifications = _gate_mode_env() == 'nudge'
    try:
        with transcript.open('r', errors='replace') as fh:
            if not first_sight or size <= TURNS_FIRST_SIGHT_MAX:
                if not first_sight:
                    fh.seek(offset)
                for line in fh:
                    if '"queue-operation"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(rec, dict):
                        continue          # a JSON line that is not a record must not end the scan
                    if (rec.get('type') == 'queue-operation'
                            and rec.get('operation') == 'enqueue'):
                        # A finished background task is queued the same way, as a
                        # <task-notification>. It is not the user, and it is not a
                        # redirection: in session 4038b8f4 358 of 961 enqueues were these, and
                        # 10 re-grounds in the drift log had only a notification before them.
                        c = rec.get('content')
                        note = isinstance(c, str) and c.lstrip().startswith('<task-notification')
                        if isinstance(rec.get('timestamp'), str):
                            turns.append((rec['timestamp'], 'notification' if note else 'user'))
                        if first_sight:
                            continue      # history is recorded, never re-grounded on
                        if skip_notifications and note:
                            continue
                        found = True
            fh.seek(0, os.SEEK_END)
            state.pop(key, None)          # re-inserted last: the dict's order is last-seen order
            state[key] = fh.tell()
    except Exception:
        return
    if turns:
        _record_turns(turns, transcript.stem)

    # Bound the file: one entry per session transcript would otherwise accumulate forever.
    # Transcripts the host deleted go first, then the least recently seen. It kept the 40
    # LARGEST offsets until 2026-10-30, which never dropped a deleted transcript and, once
    # full, evicted every small new session in the call that added it: each call was then a
    # first sight, replaying its history into USER_TURNS and re-grounding on nothing.
    if len(state) > 40:
        state = {k: v for k, v in state.items() if k == key or os.path.exists(k)}
        state = dict(list(state.items())[-40:])
    # Atomically: parallel hooks (a workflow's subagents share the parent's transcript) read
    # this file while others write it, and a half-written read used to reset every offset.
    try:
        QUEUE_SCAN.parent.mkdir(parents=True, exist_ok=True)
        tmp = QUEUE_SCAN.with_name(f'.{QUEUE_SCAN.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(state))
        os.replace(tmp, QUEUE_SCAN)
    except Exception:
        pass

    if found:
        _mark_user_turn()


_PROMPT_WRAPPERS = ('user_query', 'user_prompt', 'query', 'prompt')
_NOT_A_TASK = {
    'hello', 'hi', 'hey', 'yo', 'hiya', 'hello there', 'hey there', 'good morning',
    'good afternoon', 'good evening', 'morning', 'thanks', 'thank you', 'ty', 'ok',
    'okay', 'k', 'cool', 'nice', 'great', 'sure', 'yes', 'no', 'yep', 'nope', 'test',
    'ping', 'you there', 'are you there', 'hello?', 'still there',
}


def clean_prompt(text):
    """Unwrap a runtime's prompt envelope. DUPLICATED from laserbrain.runtime, per the
    convention above — test_hook_parity.py fails if the copies disagree.

    Until 2026-07-29 this fallback stored the prompt RAW while the SDK path cleaned it, so
    which of the two ran decided whether the ground was a task or a lump of markup. The
    fallback is the path that runs when the SDK import fails, which is exactly when nobody
    is watching.
    """
    t = str(text or '').strip()
    for tag in _PROMPT_WRAPPERS:
        open_t, close_t = f'<{tag}>', f'</{tag}>'
        if open_t in t and close_t in t:
            t = t[t.index(open_t) + len(open_t):t.index(close_t)]
    return t.strip()


def is_groundable(text):
    """Can this prompt be the fixed reference every later Φ is measured against?

    DUPLICATED from laserbrain.runtime. Rejects slash commands and a closed set of
    greetings, and deliberately does NOT impose a minimum length: this project's real
    tasks are routinely two words ('map all', 'reconcile', 'fix them'), so a length rule
    would discard the terse seeds that become the largest work.
    """
    t = clean_prompt(text)
    if not t:
        return False
    if t.startswith('/'):
        return False
    return t.strip().lower().rstrip('.!?') not in _NOT_A_TASK


def _call_sig(tool, args):
    """'The same call again', signed the way laserbrain.observe._sig signs it: the tool, a
    readable head of the JSON arguments, and a hash of ALL of them. DUPLICATED on purpose,
    like infer_progress below; test_round2_b6b7.py fails if the two ever disagree.

    Until 2026-11-16 this hook signed a call as str(args)[:200] here and json[:400] on the
    fallback path, so different heredoc edits that began the same way read as repeats and
    a finishing run came back `observed: circling` (round 2, B7). `description` is left out,
    as in observe._sig: a new label on the same command is not a new call."""
    import hashlib
    if isinstance(args, dict) and 'description' in args:
        args = {k: v for k, v in args.items() if k != 'description'}
    try:
        a = json.dumps(args, sort_keys=True, default=str) if args else ''
    except Exception:
        a = str(args)
    h = hashlib.sha1(a.encode('utf-8', 'replace')).hexdigest()[:12]
    return f'{tool}|{a[:120]}#{h}'


def infer_progress(events):
    """advancing | stuck | circling, from the tool trace alone.

    Deliberately DUPLICATED from laserbrain.observe.Observer rather than imported. A hook
    runs against whatever python3 is on PATH, and that interpreter may lag the working
    tree. The copy is small and test_hook_parity.py fails if the two ever disagree.

    Only tool calls count. The fallback path also keeps a `check-unobserved` marker in the
    same list, with no sig or ok; read as a call it raised KeyError on every later step, the
    hook swallowed it, and nothing was saved again until a reset (review of B6/B7, 2026-11-16).
    """
    events = [e for e in events if isinstance(e, dict) and 'sig' in e]
    w = events[-WINDOW:]
    if not w:
        return 'advancing'
    sigs = [e['sig'] for e in w]
    if sigs.count(sigs[-1]) >= REPEAT:
        return 'circling'
    trailing = 0
    for e in reversed(events):
        if e['ok']:
            break
        trailing += 1
    return 'stuck' if trailing >= FAILS else 'advancing'


EVIDENCE = _paths.config('evidence.json')


def _record_evidence(ok, sig=''):
    """Count observed tool outcomes so a self-report can be corroborated.

    Half of Φ has always been the agent's own account of itself — `distance` and
    `progress` are simply typed in — and an agent reporting its distance falling keeps Φ
    low while doing nothing at all. `Verdict.anchored` was added to say so, and then had
    NO CALLER: the evidence channel existed and nothing fed it, so every run reported
    0.5 forever. A number that cannot move is not a measurement.

    This is the feed. The hook is the only thing that sees every tool call and whether it
    failed, so it is the only thing that can supply it — but it runs as a separate process
    from whatever holds the harness, so the bridge has to be a file.

    A MONOTONIC COUNTER, not a flag. A flag would need the reader to reset it, and a reader
    that mutates shared state races with this writer on every step. Instead the reader
    remembers the count it last saw: if `ok` has advanced since then, something succeeded
    in the interval, and that is exactly the question. Nobody has to clear anything.

    Fails open, like everything else in this hook. A missing or unwritable evidence file
    costs a corroboration signal; it must never cost the tool call that produced it.
    """
    try:
        try:
            d = json.loads(EVIDENCE.read_text())
        except Exception:
            d = {'ok': 0, 'fail': 0}
        d['ok' if ok else 'fail'] = int(d.get('ok' if ok else 'fail', 0)) + 1
        d['at'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')

        # A rolling window kept HERE rather than read from the session record, so that
        # inferring progress does not depend on which branch of this hook ran. The session
        # record is written on one path only; this function is called on all of them.
        # Self-contained beats correct-if-you-took-the-right-turn.
        win = (d.get('window') or [])[-(WINDOW - 1):] + [{'sig': sig or '', 'ok': bool(ok)}]
        d['window'] = win
        # The same infer_progress the Observer uses, held identical by test_hook_parity.
        # This is the reading nobody had to remember to take: repetition reads as circling,
        # consecutive failure as stuck, from the trace alone.
        d['progress'] = infer_progress(win)
        d['steps'] = int(d.get('steps', 0)) + 1

        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(EVIDENCE, json.dumps(d))    # a reader never sees half of it
    except Exception:
        pass



def _event_ok(ev, ename):
    """Did this tool call succeed? Read from the response, never from the agent."""
    if 'failure' in ename:
        return False
    # ONE RULE FOR EVIDENCE AND CATCHES (2026-11-14, round 2 B4). Since B5 made this hook
    # the only evidence writer, evidence came from the structural fields below while the
    # catch came from normalise(), which also reads text, so a red suite behind a pipe
    # (108 lbq calls in round 2) would be a catch and an `ok`. runtime.tool_outcome is the
    # classifier the catch uses. The structural code below stays for an older installed
    # package (fails open).
    try:
        from laserbrain.runtime import tool_outcome
        return bool(tool_outcome(ev)[0])
    except Exception:
        pass
    r = _resp(ev)
    if isinstance(r, dict):
        code = r.get('exit_code', r.get('exitCode'))
        if isinstance(code, int):
            return code == 0
        if r.get('error') or r.get('is_error') or r.get('isError'):
            return False
    return True


# The coverage gate's own refusal — never a catch. runtime.py carries the long version of
# why; the short version is that the gate fires BECAUSE the instrument was quiet, so scoring
# its blocks as errors the instrument missed makes the hit rate 0% before any data exists.
# Measured 2026-08-02: all 8 of sensitivity.py's "misses" were this.
#
# Narrow on purpose. "laserbrain claim gate:" and "laserbrain safety:" catch conditions the
# instrument did not create, and stay catches.
#
# "laserbrain drift gate:" joined on 2026-11-14 (round 2 B3): the enforced drift gate blocks
# BECAUSE a reading fired, so its block coincides with a fire by construction, the mirror of
# the 2026-08-02 circle.
#
# READ AT THE HEAD OF EACH MESSAGE, not searched for (2026-11-14, B3/B4 review). A refusal is
# a message that BEGINS with the deny text, bare or behind Claude Code's "PreToolUse:<Tool>
# hook error: [cmd]: " prefix; a failed command's `error` begins "Exit code N". The old
# whole-text DOTALL search made every successful Read, grep or Edit of laserbrain's own
# source stop counting as evidence (63 in Diego's last 30 days of transcripts), took the
# catch from a red suite that quotes the gate, and cost 2.7 s on 200,000 characters. Every
# real refusal also says THIS CALL DID NOT RUN within its first lines. Held identical to
# runtime._SELF_REFUSAL_HEAD_RE and runtime._message_texts; test_round2_b3b4.py compares the
# two. A copy, not an import, because the fallback runs exactly when runtime cannot be
# imported.
# The bracketed command may itself hold ']' (the plugin's own hook command has `[ -n "$LB_PY" ]`),
# so the group runs lazily to the first ']: ' that the deny text follows, on one line only.
_REFUSAL_LEAD = r'\A\s*(?:PreToolUse:\S+ hook error: (?:\[[^\n]*?\]: )?)?'
_DID_NOT_RUN = r'(?:[^\n]*\n){0,5}?[^\n]*?\bTHIS CALL DID NOT RUN\b'
_SELF_REFUSAL_HEAD_RE = re.compile(
    _REFUSAL_LEAD + r'laserbrain (?:gate:(?=[^\n]*\bcoverage\b)|drift gate:)' + _DID_NOT_RUN,
    re.IGNORECASE)


def _message_texts(ev):
    """The fields a refusal can arrive in, decoded (copy of runtime._message_texts)."""
    def blocks(bs):
        return '\n'.join(b if isinstance(b, str) else str(b.get('text') or '')
                         for b in bs
                         if isinstance(b, str) or (isinstance(b, dict) and b.get('type') == 'text'))
    out = []
    e = ev.get('error')
    if e is None:
        e = ev.get('errorMessage')
    if e is not None:
        out.append(e if isinstance(e, str) else json.dumps(e, default=str))
    r = _resp(ev)
    if isinstance(r, str):
        out.append(r)
    elif isinstance(r, list):
        out.append(blocks(r))
    elif isinstance(r, dict):
        for k in ('content', 'output', 'stderr', 'stdout', 'error', 'errorMessage', 'message'):
            v = r.get(k)
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, list):
                out.append(blocks(v))
    return out


def _is_self_refusal(ev):
    """True when this call IS the coverage gate (or the enforced drift gate) stopping its own
    agent: one of its message fields begins with the deny text.

    Reads the failure event's `error` too (2026-11-14, round 2 B3). Claude Code's
    PostToolUseFailure carries the refusal there and sends no tool_response, so a test of
    the response alone would score a gate block as a catch and as evidence.
    """
    try:
        return any(t and _SELF_REFUSAL_HEAD_RE.match(t) for t in _message_texts(ev))
    except Exception:
        return False


def _is_interrupt(ev):
    """The user stopped the call (Esc): a step, but neither a catch nor evidence."""
    return bool(ev.get('is_interrupt') or ev.get('isInterrupt'))


def _probe_arm(sid):
    """Which gate regime this session runs under. Imported from the gate, never re-derived.

    lb_gate.py owns the assignment because it owns the thresholds. Copying the hash here
    would put the definition of an experiment's arms in two files, and the first time one
    drifted, every session between would be labelled one thing and treated as another —
    which is not a bug that announces itself, it is a silently ruined comparison.

    Returns None when the gate is not importable, and None is written rather than a guess:
    a session whose arm is unknown must be droppable by the analysis, not counted as
    'control' because that was the convenient default.
    """
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from lb_gate import probe_arm
        return probe_arm(sid)
    except Exception:
        return None


def _fresh_state(path):
    return {'id': path.stem, 'started': datetime.datetime.now().isoformat(timespec='seconds'),
            'goal': None, 'steps': 0, 'checks': [], 'inferred': [], 'catches': [], 'events': []}


def load(path):
    try:
        d = json.loads(path.read_text())
    except Exception:
        d = _fresh_state(path)
    # probe_arm is NOT stamped here any more. It was, for a day, and lost every single
    # write: the SDK's Session in laserbrain/runtime.py owns the same file, holds its dict
    # in memory across this hook's writes, and saves the whole thing back — so the last
    # writer drops the other's keys. Checked 2026-08-03: not one session file carried the
    # arm, including the live one, so the probe was applying arms and recording none.
    # lb_gate.record_arm appends it to probe-arms.jsonl instead, where there is one writer.
    return d


# ── one writer at a time, never half a file ─────────────────────────────────────────────
# This hook's copy of laserbrain.runtime.session_lock / write_atomic, for the fallback path,
# which runs exactly when that module cannot be imported. The rule and the lock file are the
# same (<sid>.json.lock, flock, bounded wait then proceed, released when the process exits);
# see the note above runtime.session_lock for the race it closes and the numbers.
# test_session_race.py holds one copy's lock and checks the other waits for it.
#
# Not re-entrant across threads, because this hook has none; re-entry in one process holds
# the one descriptor it already has, since a second flock on the same file from the same
# process would wait on itself until the bound ran out.
STATE_LOCK_WAIT = 2.0
_state_held = {}                   # lock path -> [fd, depth]


def _state_lock_path(path):
    p = pathlib.Path(path)
    return p.with_name(p.name + '.lock')


class _state_lock:
    """`with _state_lock(path) as held:` the session's exclusive lock, or held=False when
    LASERBRAIN_LOCK_WAIT (default 2 s) ran out first. The block runs either way."""

    def __init__(self, path, wait=None):
        self.key = str(_state_lock_path(path))
        if wait is None:
            try:
                wait = float(os.environ.get('LASERBRAIN_LOCK_WAIT', STATE_LOCK_WAIT))
            except ValueError:
                wait = STATE_LOCK_WAIT
        self.wait = max(0.0, wait)
        self.fd = None
        self.reentered = False
        self.gave_up = False

    def __enter__(self):
        slot = _state_held.get(self.key)
        if slot is not None:       # re-entry: held (fd) or already given up (None)
            slot[1] += 1
            self.reentered = True
            return slot[0] is not None
        try:
            import fcntl
            import time as _time
        except ImportError:
            return False
        try:
            pathlib.Path(self.key).parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.key, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            return self._give_up()
        deadline, delay = _time.monotonic() + self.wait, 0.0005
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fd = fd
                _state_held[self.key] = [fd, 1]
                return True
            except (BlockingIOError, PermissionError):
                pass
            except OSError:
                break
            left = deadline - _time.monotonic()
            if left <= 0:
                break
            _time.sleep(min(delay, left))
            delay = min(delay * 2, 0.005)
        os.close(fd)
        return self._give_up()

    def _give_up(self):
        # The block runs unlocked; a nested _state_lock on the same file re-enters this slot
        # and proceeds at once rather than waiting the whole bound again.
        _state_held[self.key] = [None, 1]
        self.gave_up = True
        return False

    def __exit__(self, *exc):
        if self.reentered:
            _state_held[self.key][1] -= 1
        elif self.gave_up:
            _state_held.pop(self.key, None)
        elif self.fd is not None:
            _state_held.pop(self.key, None)
            try:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(self.fd)
            self.fd = None
        return False


def _write_atomic(path, text):
    """Temp file in the same directory, then os.replace: a reader sees the old file or the
    new one. Hidden and ending in .tmp so no *.json glob ever picks it up."""
    path = pathlib.Path(path)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        with open(tmp, 'w') as fh:
            fh.write(text)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise                      # the old file is untouched; never truncate it here
    try:
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        path.write_text(text)


def _save_state(path, s):
    _write_atomic(path, json.dumps(s, indent=2))


def _runtime_gave_up(path):
    """Did laserbrain.runtime, already imported in this process, time out on this lock?"""
    rt = sys.modules.get('laserbrain.runtime')
    try:
        return bool(rt is not None and rt.gave_up(path))
    except Exception:
        return False


def _load_for_write(path):
    """load() for the read-modify-write under _state_lock.

    load() starts a fresh session from any file it cannot parse, and the save that follows
    replaces the file with it: the wipe the lock exists to prevent. Every writer is atomic
    now, so an unparseable file means a hook from before the swap is mid-write (look again
    for a few ms) or real damage (copy the bytes to <sid>.json.corrupt first, where no
    *.json glob reads them, then start fresh as before)."""
    import time as _time
    raw = None
    for i in range(6):
        if i:
            _time.sleep(0.002)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = None
            break
        except OSError:
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if isinstance(d, dict):
            return d
    if raw is not None and raw.strip():
        try:
            aside = path.with_name(path.name + '.corrupt')
            tmp = aside.with_name(f'.{aside.name}.{os.getpid()}.tmp')
            tmp.write_bytes(raw)
            os.replace(tmp, aside)
        except Exception:
            pass
    return _fresh_state(path)      # missing, unreadable or damaged: fresh, as load() does


def _sid(ev):
    return str(
        ev.get('session_id') or ev.get('sessionId')
        or os.environ.get('LASERBRAIN_SESSION_ID')
        or 'unknown'
    )


def _tool(ev):
    return str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '')


def _args(ev):
    a = (ev.get('tool_input') if ev.get('tool_input') is not None
         else ev.get('toolInput') if ev.get('toolInput') is not None
         else ev.get('arguments') if ev.get('arguments') is not None
         else {})
    return a if isinstance(a, dict) else {'_': a}


def _verdict(resp):
    """Pull {drifting, reason, phi} out of a check response, whatever shape it arrives in.

    This replaced a substring match on the serialised response:

        '"drifting": true' in text.lower() or '"drifting":true' in text.lower()

    which returned False for EVERY fire and did so silently. The reason is that an MCP
    response arrives wrapped — {"content":[{"type":"text","text":"{...}"}]} — and
    json.dumps escapes the inner quotes, so the serialised text contains \\"drifting\\"
    and neither pattern can match. Verified 2026-07-25: bare dicts and raw JSON strings
    were detected, the wrapped form never was.

    The cost was the whole corpus. 204 checks across 10 sessions recorded zero fires,
    including 104 checks sitting below the 0.30 threshold that DEFINES goal-drift, while
    the agent was being told it had drifted in the same breath. The verdicts had to be
    rebuilt from chat transcripts because the session files never held them.

    So: parse, do not pattern-match. Walk the structure, decode any JSON carried as a
    string, and read the field as the boolean it is. `reason` and `phi` are captured too
    — the old code wrote the literal 'see response', which made it impossible to ask the
    corpus which SIGNAL fired, and that question is the whole point of the corpus.
    """
    def walk(x, depth=0):
        if depth > 6 or isinstance(x, bool):
            return None
        if isinstance(x, dict):
            # A READING IS NOT ONLY A `drifting` KEY. The blind arm answers
            # {blind:true, arm, run, step, note} and carries no `drifting` at all — so a
            # walk that recognised responses by that one field could not see a withheld
            # verdict, fell through to the no-reading default, and every blind check was
            # recorded as a parse failure. The experiment was erasing itself from the
            # corpus it exists to be measured in. Recognise either.
            if isinstance(x.get('drifting'), bool) or x.get('blind') is True:
                return x
            for val in x.values():
                got = walk(val, depth + 1)
                if got is not None:
                    return got
        elif isinstance(x, list):
            for val in x:
                got = walk(val, depth + 1)
                if got is not None:
                    return got
        elif isinstance(x, str):
            t = x.strip()
            if t[:1] in ('{', '['):
                # SALVAGE THE PREFIX. json.loads() demands the WHOLE string be one value, so
                # a single character appended after the payload threw the entire reading away.
                #
                # Not hypothetical: laserbrain appends its own honesty note to check_state
                # responses — "distance has not fallen across the last two checks" — and that
                # note fires very nearly when the judgment layer decides to speak. Measured
                # 2026-08-05 on one run: server steps 2-5 parsed and were stored; steps 6-9
                # were exactly the four carrying an `unbacked` judgment, and all four recorded
                # `no-reading` with every field None. Not only the judgment — reason, phi,
                # anchored and goal_score went with it.
                #
                # So the instrument went blind precisely when it had the most to say, and did
                # it to itself. Across the whole corpus that is 0 of 2,555 drift rows and 0 of
                # 2,157 session rows carrying a judgment, while the field tested green.
                #
                # raw_decode reads the first complete value and stops, which fixes it for ANY
                # trailing text rather than only for ours.
                try:
                    return walk(json.loads(t), depth + 1)
                except Exception:
                    pass
                try:
                    obj, _end = json.JSONDecoder().raw_decode(t)
                    return walk(obj, depth + 1)
                except Exception:
                    return None
        return None

    found = walk(resp) or {}
    # `run` and `step` are the drift log's primary key, and carrying them here is what
    # makes a catch joinable to the reading that was live when it happened. Before this
    # the session file counted its own steps and the server counted its own, with no
    # shared field: precision was computable and sensitivity was not, because a miss is
    # only visible when you can say WHICH reading missed. Absent on servers older than
    # 2026-08-01, so None means "this row predates the join", not "no run".
    # THE JUDGMENT LAYER WAS NOT RECORDED, and it is the layer that gives the strongest
    # advice the instrument owns. `reason` names the reading; `judgment` names what the
    # harness told the agent to DO about the run — abandon, wrong-problem, repeating,
    # narrow. Nothing in the corpus held it, so on 2026-08-04 a bug that attached
    # `abandon` to the first check of a replaced goal could be found only by it happening
    # to me while I watched. Once the field existed the same question took one query: the
    # exposure was 64 regrounds at step >= 13, 3.5% of every recorded check.
    #
    # `anchored` and `goal_score` come along for the same reason. anchored is the fraction
    # of Phi resting outside the agent's own account of itself — 0.5 on the published
    # calibration — and it has been reported on every verdict and stored on none, which
    # makes "does corroboration predict a true catch" unanswerable. goal_score says
    # whether this is still the errand that was asked for, which Phi does not: a faithful
    # goal sits at high Phi when the work is hard.
    #
    # All four are absent on older servers, so None means "this row predates the field",
    # never "there was no judgment".
    j = found.get('judgment') or {}
    return {'drifting': bool(found.get('drifting')),
            'reason': str(found.get('reason') or 'no-reading'),
            'phi': found.get('phi'),
            'run': found.get('run'),
            'run_step': found.get('step'),
            'judgment': (j.get('verdict') if isinstance(j, dict) else None),
            'anchored': found.get('anchored'),
            'goal_score': found.get('goal_score'),
            # WHICH ARM THIS CHECK BELONGED TO. The server states it on both branches; a
            # blind response also carries `blind: true`, which is the fallback for a server
            # too old to say `arm`. None means "not stated", and that is NOT 'sighted' — a
            # check recorded before 2026-08-10 has no arm, and folding it into sighted
            # would enrol the entire pre-blind corpus in one arm of an experiment it was
            # never part of.
            'arm': found.get('arm') or ('blind' if found.get('blind') is True else None)}


def _attribute(s, step):
    """Which drift reading was live when something failed at session `step`.

    A catch is the only evidence in this system that did not come from the agent grading
    itself: a non-zero exit is the build disagreeing, and the build has no opinion about
    the instrument. That makes catches the one place sensitivity can come from — but only
    if a catch can name the reading it belongs to. It could not, so d-prime was reported
    as "not computable, now or ever, from this corpus". This is the field that changes it.

    `since` is carried because attribution decays. A failure one step after a reading was
    almost certainly live under it; a failure fourteen steps later happened during a
    stretch the instrument never saw, and calling that a MISS would blame the detector for
    not firing on a step it was never shown. Anything analysing this must be free to
    discard the far ones, which means the distance has to survive alongside the join.
    """
    checks = s.get('checks') or []
    if not checks:
        return {'run': None, 'run_step': None, 'since': None}
    last = checks[-1]
    return {'run': last.get('run'),
            'run_step': last.get('run_step'),
            'since': step - int(last.get('step') or 0)}


def _resp(ev):
    r = (ev.get('tool_response') if ev.get('tool_response') is not None
         else ev.get('toolResult') if ev.get('toolResult') is not None
         else ev.get('output') if ev.get('output') is not None
         else {})
    return r


def _unwrap(tool, args):
    """Some hosts route MCP through a wrapper tool with a nested tool_name."""
    if tool not in ('use_tool', 'CallMcpTool', 'call_mcp_tool', 'mcp_tool'):
        return tool, args
    nested = str(args.get('tool_name') or args.get('toolName') or args.get('name') or '')
    nested_in = (args.get('tool_input') if args.get('tool_input') is not None
                 else args.get('toolInput') if args.get('toolInput') is not None
                 else args.get('arguments') if args.get('arguments') is not None
                 else args)
    if nested:
        return nested, nested_in if isinstance(nested_in, dict) else args
    return tool, args


def _is_check(tool):
    return tool.lower().endswith('check_state')


def _is_reset(tool):
    t = tool.lower()
    return t.endswith('reset_task') or t.endswith('__reset_task')


def _is_shell(tool):
    return tool in ('Bash', 'run_terminal_command', 'Shell', 'bash')


def _event_name(ev):
    return str(ev.get('hookEventName') or ev.get('hook_event_name')
               or os.environ.get('LASERBRAIN_HOOK_EVENT') or '').lower()


def _reply_event(ev, promptish=False):
    """The hookEventName to answer with: the event that was asked, never a fixed default.

    WHY, 2026-11-14. The prompt path called _emit_inline_nudge() with its default
    'PostToolUse'. Claude Code checks the label against the event it sent and discards a
    mismatch ("expected 'UserPromptSubmit' but got 'PostToolUse'"), so the link and
    subagent guidance written on every prompt reached no one: 40 of 40 lbq episodes in
    round 2 (research/DAY-FOUR-ROUND2.md, B1). The flag file was written just before it,
    which is why nothing else looked wrong.
    """
    raw = str(ev.get('hook_event_name') or ev.get('hookEventName') or '')
    known = {'posttooluse': 'PostToolUse', 'userpromptsubmit': 'UserPromptSubmit',
             'posttoolusefailure': 'PostToolUseFailure', 'sessionstart': 'SessionStart',
             'pretooluse': 'PreToolUse'}
    got = known.get(raw.replace('_', '').lower())
    if got:
        return got
    return 'UserPromptSubmit' if promptish else 'PostToolUse'


def _emit_inline_nudge(nudge, event='PostToolUse'):
    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': event,
            'additionalContext': nudge,
        }
    }))


def _emit_stop_block(nudge):
    # Where PostToolUse stdout is ignored, decision=block on Stop feeds the reason
    # back and keeps the agent working.
    print(json.dumps({'decision': 'block', 'reason': nudge}))


# Same resolution as lb_gate.gate_mode(), read here from the environment so the common path
# does not import lb_gate: unset or empty → nudge, unknown → hard (lb_gate says so on stderr).
_GATE_MODES = ('nudge', 'hard', 'watch', 'signal')


def _gate_mode_env():
    v = (os.environ.get('LASERBRAIN_GATE_MODE') or '').strip().lower()
    if not v:
        return 'nudge'
    return v if v in _GATE_MODES else 'hard'


def _agent_key(ev):
    a = ev.get('agent_id') or ev.get('agentId')
    return str(a) if a else 'main'


def _update_agents(ev, ename):
    """nudge mode: per-agent step counters in <session>.agents.json. Never raises.

    Every subagent shares its parent's session_id, so the session file's one `steps` counter
    sums every agent's calls and any agent's check_state resets it for all of them. The gate
    read that as "N steps since your last check_state" for an agent that had made a fraction
    of N. This file counts per agent_id (the payload names one for subagent calls only;
    'main' otherwise) so lb_gate can attribute each call to the agent that made it. The
    session file itself is untouched. Locked, because parallel subagents write at once: the
    same bounded sidecar lock as the session file (<sid>.agents.json.lock, _state_lock) and
    an atomic save, so _agent_counts, _honesty_due and _agent_dists, which read it unlocked,
    never see half a file. It used to flock the file itself with no time limit and rewrite
    it in place (review, 2026-11-16): the one wait in this hook with no bound.
    """
    try:
        if 'prompt' in ename or 'stop' in ename or 'pretooluse' in ename:
            return
        tool, args = _unwrap(_tool(ev), _args(ev))
        if not tool:
            return
        # A failed check_state is not a check and a failed reset_task is not a reset
        # (2026-11-14, round 2 B3): ignored here as in runtime.normalise, exactly as before
        # PostToolUseFailure was wired. Otherwise a failed check would clear this agent's
        # own "steps since check" and feed a distance it never got a reading for.
        if 'failure' in ename and (_is_check(tool) or _is_reset(tool)
                                   or str(tool).lower().endswith('get_history')):
            return
        import time as _time
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        key = _agent_key(ev)
        apath = STATE_DIR / f'{_sid(ev)}.agents.json'
        with _state_lock(apath):
            try:
                txt = apath.read_text()
            except FileNotFoundError:
                txt = ''
            try:
                d = json.loads(txt) if txt.strip() else {}
                if not isinstance(d, dict):
                    d = {}
            except Exception:
                d = {}
            e = d.get(key) if isinstance(d.get(key), dict) else {}
            if _is_reset(tool):
                e = {'steps': 0, 'checks': 0, 'check_step': 0, 'dists': []}
            else:
                e['steps'] = int(e.get('steps', 0)) + 1
                if _is_check(tool):
                    e['checks'] = int(e.get('checks', 0)) + 1
                    e['check_step'] = e['steps']
                    e['dists'] = (list(e.get('dists') or [])[-1:] + [args.get('distance')])
                    e['prog'] = str(args.get('progress') or '').strip().lower()[:16]
            e['t'] = round(_time.time(), 1)
            d[key] = e
            if len(d) > 200:          # one entry per subagent; keep the most recently active
                d = dict(sorted(d.items(), key=lambda kv: kv[1].get('t', 0))[-200:])
            _write_atomic(apath, json.dumps(d))
    except Exception:
        pass


def _agent_counts(ev):
    """(steps, checks, since) for the calling agent from <session>.agents.json, or None."""
    try:
        d = json.loads((STATE_DIR / f'{_sid(ev)}.agents.json').read_text())
        e = d.get(_agent_key(ev))
        if not isinstance(e, dict):
            return 0, 0, 0
        steps = int(e.get('steps', 0))
        check_step = int(e.get('check_step', 0))
        return steps, int(e.get('checks', 1 if check_step else 0)), max(0, steps - check_step)
    except Exception:
        return None


def _agent_reminder(ev, edge_only, fallback):
    """nudge mode: the runtime's reminder, computed from the CALLING agent's own counts.

    Session.nudge() counts every agent's calls as one session total (they share a
    session_id), so a subagent that had just checked in was told "8 steps since your last
    check_state" after its siblings' calls (checker, 2026-10-17). Same text and cadence as
    Session.nudge() (edge_only: every NUDGE_AFTER steps) or coverage_warning() (whenever
    lapsed), with the agent's numbers. `fallback` (the session text) when no sidecar exists.
    """
    c = _agent_counts(ev)
    if c is None:
        return fallback
    steps, checks, since = c
    if since < NUDGE_AFTER or (edge_only and since % NUDGE_AFTER):
        return None
    cov = (checks / steps) if steps else 0.0
    return (f'laserbrain: {since} of your steps since your last check_state '
            f'(coverage {cov:.0%} over your {steps} steps). dogfood.py withholds any detection '
            f'result below 50%. Call check_state now with your CURRENT goal, progress (one '
            f'word: advancing|stuck|circling; a note goes in doing) and distance 0-10.')


def _nudge_stop(ev, session_warn, camel_shape):
    """nudge mode's end-of-turn check. Never blocks.

    The reminder is the calling agent's own (_agent_reminder). On camelCase hosts, where
    hard mode blocks the Stop, the would-be block is logged to refusals.jsonl as stage
    nudge-stop with the session-wide numbers hard uses (would_hard: whether hard would have
    blocked) and the agent's own numbers beside them.
    """
    own = _agent_reminder(ev, edge_only=False, fallback=session_warn)
    if own:
        _emit_inline_nudge(own + (' (Not blocking: LASERBRAIN_GATE_MODE unset = nudge.)'
                                  if camel_shape else ''), event='Stop')
    if not camel_shape or not (own or session_warn):
        return
    try:
        from lb_gate import record_refusal, min_coverage, probe_arm
        st = load(STATE_DIR / f'{_sid(ev)}.json')
        steps = int(st.get('steps') or 0)
        ck = st.get('checks') or []
        since = steps - (int(ck[-1].get('step') or 0) if ck else 0)
        c = _agent_counts(ev) or (steps, len(ck), since)
        record_refusal(_sid(ev), 'nudge-stop', 'stop', since,
                       (len(ck) / steps) if steps else 0.0, min_coverage(), NUDGE_AFTER,
                       probe_arm(_sid(ev)), extra={
                           'would_hard': bool(session_warn), 'agent': _agent_key(ev),
                           'agent_since': c[2], 'agent_steps': c[0],
                           'agent_coverage': round((c[1] / c[0]) if c[0] else 0.0, 3),
                           'agent_stage': 'stop' if own else None,
                       })
    except Exception:
        pass


def _honesty_due(ev):
    """nudge mode: may the honesty note go out on this call? Once per spelled check, on the call
    that spelled it (its PostToolUse), and not when that check already said stuck or circling.

    It used to be re-evaluated on every tool call, so one pair of equal distances repeated it on
    each call until the next check: measured 2026-11-04 on one session, 239 tool results carried
    it for 39 check_state calls (414 calls), and 39 of those came right after the agent had
    reported stuck itself, which is the very thing the note asks for. Returns True when the
    agent's own entry isn't recorded, so the note is never lost for lack of data."""
    try:
        d = json.loads((STATE_DIR / f'{_sid(ev)}.agents.json').read_text())
        e = d.get(_agent_key(ev))
        if not isinstance(e, dict) or 'check_step' not in e:
            return True
        if str(e.get('prog') or '') in ('stuck', 'circling'):
            return False
        return int(e.get('steps', 0)) == int(e.get('check_step', -1))
    except Exception:
        return True


def _agent_dists(ev):
    """The calling agent's last two spelled distances, or None if not recorded."""
    try:
        d = json.loads((STATE_DIR / f'{_sid(ev)}.agents.json').read_text())
        e = d.get(_agent_key(ev)) or {}
        ds = e.get('dists') or []
        return ds if len(ds) >= 2 else None
    except Exception:
        return None


def main():
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        ev = {}

    # A message typed while the agent is working never arrives as a hook event, so this
    # runs above every branch below: it is the only place a mid-turn redirection can be
    # noticed at all. (The diagnostic that established this was removed 2026-07-30 once
    # it had answered the question — see _mark_user_turn_if_queued for the measurement.)
    _mark_user_turn_if_queued(ev)
    _daily_harvest(ev)

    # PUBLISH THE BLIND ARM, above every branch, because the MCP server cannot work it out.
    #
    # lasermind/mcp-server.mjs builds the check_state response and holds only `runId`, which
    # resets on every reset_task — a session that resets twenty times would flip between arms
    # twenty times and destroy the comparison. The MCP config's env block is static strings,
    # so it cannot carry a session id either. This hook is the only process that knows one.
    #
    # It writes the ARM, not the id: handing the server an id would make it recompute the
    # assignment in JavaScript from a second copy of the hash, which is the divergence bug
    # already fixed three times in this codebase. The assignment lives in lb_gate, once.
    #
    # One writer here, one reader there — a different shape from the failure record_arm
    # exists to avoid, which was two processes read-modify-writing the same dict.
    #
    # No-ops entirely unless LASERBRAIN_BLIND_PROBE is set.
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from lb_gate import publish_blind_arm
        # The segment index is how many runs have already been archived. It advances exactly
        # when reset_task fires — never mid-task — so the arm is stable for the life of one
        # task and re-drawn for the next.
        _sd = _sid(ev)
        _seg = 0
        try:
            _st = json.loads((STATE_DIR / f'{_sd}.json').read_text())
            _seg = len(_st.get('segments') or [])
        except Exception:
            pass
        publish_blind_arm(_sd, str(STATE_DIR), segment=_seg)
    except Exception:
        pass          # an experiment must never break the harness it is measuring

    # Prefer the shared implementation when the installed package provides it.
    try:
        from laserbrain.runtime import from_hook, Session, session_id_of
        has_runtime = True
    except Exception:
        has_runtime = False
        from_hook = Session = session_id_of = None

    ename = _event_name(ev)

    # Evidence is recorded HERE, above every branch, and deliberately not beside the
    # existing ok_flag bookkeeping. The first attempt put it there — and that code runs
    # only on the path taken when laserbrain cannot be imported, which never happens on a
    # machine with the SDK installed. So the writer sat in dead code: the counter stayed at
    # zero, the hook returned 0 every time, and nothing errored. It did not look wrong
    # because there was nothing to look at.
    #
    # A signal every reader depends on cannot live behind a branch.
    #
    # NOT laserbrain's own bookkeeping, since 2026-11-14 (round 2, B5). check_state's own
    # PostToolUse landed here as a success, so every check bumped `ok` before the next one
    # and the stall veto (mcp-server.mjs, "every check in the window is backed") read
    # "backed" from check 6 on: an agent that only ever called check_state counted as
    # working, and `stalled` could not fire. Reading the harness is not work.
    #
    # ONE WRITER. runtime.Session.tool() bumped the same counter again for the same call, so
    # every tool counted twice whenever the package imported. The hook is the writer that
    # sees every call on every branch; the env flag below tells Session.tool() to stand down
    # inside this process only. The SDK, with no hook, still bumps as before.
    #
    # NOR THE INSTRUMENT'S OWN REFUSALS, OR THE USER'S ESC, since 2026-11-14 (round 2 B3).
    # 'posttooluse' also matches PostToolUseFailure, which is where a gate block or an
    # interrupt now arrives. Counted, a coverage-gate block would bump `fail`, set the
    # server's sawAny (which enables 'unbacked') and push the window toward 'stuck': the
    # instrument corroborating its own interruption. Session.tool excludes the same calls.
    #
    # ONLY A CALL THAT DID NOT SUCCEED can be a refusal or an interrupt (B3/B4 review,
    # 2026-11-14). The exclusion first ran on every call, so a successful Edit of runtime.py
    # or an exit-0 grep for the deny text stopped counting as work. A successful call cannot
    # be a gate refusal.
    if 'posttooluse' in ename:
        _t0, _a0 = _unwrap(_tool(ev), _args(ev))
        if not (_is_check(_t0) or _is_reset(_t0) or str(_t0).lower().endswith('get_history')):
            _ok0 = _event_ok(ev, ename)
            if _ok0 or not (_is_self_refusal(ev) or _is_interrupt(ev)):
                _record_evidence(_ok0, _call_sig(_tool(ev), _args(ev)))
        os.environ['LASERBRAIN_HOOK_EVIDENCE'] = '1'
    _gm_env = _gate_mode_env()
    if _gm_env == 'nudge':
        _update_agents(ev, ename)      # per-agent attribution; hard/watch/signal write nothing new
    # ASKLLM WATCH, 2026-11-15 to 2026-11-22 (lb_askllm_watch.py). A helper agent's first
    # check_state starts the frozen AI-graded ask-mismatch check in a detached process that
    # only writes askllm-watch.jsonl. Nothing it does reaches stdout, the model or the user,
    # and any failure stops here. Below _update_agents, so the sidecar counts this check.
    if 'posttooluse' in ename and 'failure' not in ename and (ev.get('agent_id')
                                                              or ev.get('agentId')):
        try:
            _tw, _aw = _unwrap(_tool(ev), _args(ev))
            if _is_check(_tw):
                _sw = _ilu.spec_from_file_location('lb_askllm_watch', str(
                    pathlib.Path(__file__).resolve().parent / 'lb_askllm_watch.py'))
                _mw = _ilu.module_from_spec(_sw)
                _sw.loader.exec_module(_mw)
                _mw.on_post_tool_use(ev, _tw, _aw, STATE_DIR)
        except BaseException:          # noqa: BLE001 — watch-only, never into this hook
            pass
    # WHICH PROTOCOL SHAPE, not which vendor. camelCase payloads (sessionId, toolName,
    # toolInput) need a different injection path from snake_case ones — that difference is
    # real and stays. Calling the variable `is_grok` made a fact about payload spelling
    # look like a fact about who sent it, and two hosts can share a convention.
    camel_shape = bool(ev.get('sessionId') is not None or ev.get('toolName') is not None
                       or ev.get('toolInput') is not None
                       or any(k.endswith('_HOOK_EVENT') and os.environ.get(k)
                              for k in os.environ))

    # ── Stop gate (primary injection path where PostToolUse stdout is ignored) ──
    # Only genuine turn ends. Session-end Stop is observe-only.
    if 'stop' in ename and 'failure' not in ename:
        reason = str(ev.get('reason') or '')
        if reason and reason != 'end_turn':
            return
        try:
            if has_runtime:
                sid = session_id_of(ev)
                s = Session(sid, directory=str(STATE_DIR))
                warn = s.coverage_warning() if hasattr(s, 'coverage_warning') else s.nudge()
            else:
                path = STATE_DIR / f'{_sid(ev)}.json'
                st = load(path)
                steps = int(st.get('steps') or 0)
                checks = st.get('checks') or []
                last = checks[-1]['step'] if checks else 0
                since = steps - last
                warn = None
                if since >= NUDGE_AFTER:
                    cov = len(checks) / steps if steps else 0
                    warn = (f'laserbrain: {since} steps since your last check_state '
                            f'(coverage {cov:.0%} over {steps} steps). dogfood.py withholds any '
                            f'detection result below 50%. Call check_state now with your CURRENT '
                            f'goal, progress (advancing|stuck|circling) and distance 0-10.')
            if _gm_env == 'nudge':
                # No block; the calling agent's own reminder as context, and on camelCase
                # hosts the would-be block logged as stage nudge-stop. See _nudge_stop.
                _nudge_stop(ev, warn, camel_shape)
            elif warn:
                if camel_shape:
                    # This stop-block is a step-count refusal, so it follows the gate mode,
                    # read from the environment (lb_gate is imported only when a mode needs
                    # its loggers):
                    #   hard          the block, exactly as before 2026-10-16
                    #   nudge (unset) handled above (_nudge_stop)
                    #   watch|signal  no block; logged to refusal-args.jsonl (unchanged)
                    _gm = _gm_env
                    if _gm == 'hard':
                        _emit_stop_block(warn)
                    else:
                        try:
                            from lb_gate import record_refusal_args
                            record_refusal_args(_sid(ev), _gm, 'stop', 'coverage', 'Stop', ev,
                                                blocked=False)
                        except Exception:
                            pass
                else:
                    _emit_inline_nudge(warn, event='Stop')
        except Exception:
            pass
        return

    # ── Shared Session path when import works ───────────────────────────────
    if has_runtime:
        try:
            if camel_shape:
                nudge = from_hook(ev, directory=str(STATE_DIR))
            else:
                nudge = from_hook(ev, directory=str(STATE_DIR))
            if _gm_env == 'nudge' and 'prompt' not in ename and _tool(ev):
                # from_hook still records the step in the session file; the reminder it
                # returns counts every agent's calls, so say the calling agent's own instead.
                nudge = _agent_reminder(ev, edge_only=True, fallback=nudge)
            # Session-start / prompt: remind multi-agent link hygiene + honest progress.
            promptish = (ev.get('prompt') is not None
                         or ev.get('userPrompt') is not None
                         or ev.get('promptText') is not None
                         or 'prompt' in ename or 'userprompt' in ename.replace('_', ''))
            extras = []
            if promptish:
                # Mark that the NEXT check_state is a re-ground, not a drift. See the long
                # note in the embedded fallback below for why this exists.
                #
                # This copy is the one that RUNS. The first version of the fix was written
                # only into the fallback branch, which fires solely when importing
                # laserbrain.runtime fails — so the flag was never written, no reground
                # ever happened, and the whole patch was inert while every test passed.
                # test_reground.py drives the MCP server directly and simulates the flag
                # itself, so it could not have caught this. Only asking the live hook for
                # the file did.
                _mark_user_turn()
                # The link_read sentence that opened this reminder ("multi-step work in a
                # shared repo → link_read and answer open claims") was dropped 2026-11-15:
                # it served Claude–Grok coordination, which is no longer in use, and the
                # link log had been silent since 2026-08-01. It cost a sentence on every
                # prompt and a link_read call on most tasks. link_read itself still works.
                extras.append(
                    'laserbrain: '
                    'Gate: never batch non-laserbrain tools with the check_state that '
                    'clears the gate — check alone, then reissue. '
                    'Subagents: parent check_state between spawn waves; children do not '
                    'share parent harness Φ.'
                )
            # Subagent spawn: structural reminder (parent must check between waves)
            try:
                tname = str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '').lower()
                if any(x in tname for x in (
                    'spawn_subagent', 'task', 'agent', 'subagent',
                )) and 'check_state' not in tname:
                    extras.append(
                        'laserbrain subagent: child sessions have their own Φ. '
                        'check_state on the parent before the next spawn wave; '
                        'do not assume coverage from the child.'
                    )
            except Exception:
                pass
            # Honesty: if last two spelled checks show same distance while not done, nudge.
            try:
                sid = session_id_of(ev)
                s = Session(sid, directory=str(STATE_DIR))
                checks = s.d.get('checks') or []
                pair = None
                if len(checks) >= 2:
                    pair = (checks[-2].get('distance'), checks[-1].get('distance'))
                if _gm_env == 'nudge':
                    # The session's last two checks may belong to two different agents (they
                    # share a session_id), which made this fire on an agent whose own distance
                    # was falling. Compare the CALLING agent's own last two when recorded.
                    own = _agent_dists(ev)
                    pair = tuple(own) if own else (pair if _agent_key(ev) == 'main' else None)
                if pair and _gm_env == 'nudge' and not _honesty_due(ev):
                    pair = None
                if pair:
                    da, db = pair
                    if da is not None and da == db and da not in (0, '0', 0.0):
                        extras.append(
                            'laserbrain honesty: distance has not fallen across the last '
                            'two checks. If you are circling or stuck, say so — false '
                            'advancing wastes the dogfood corpus.'
                        )
            except Exception:
                pass
            if extras and not camel_shape:
                _emit_inline_nudge('\n'.join(extras) + (('\n' + nudge) if nudge else ''),
                                   event=_reply_event(ev, promptish))
            elif nudge and not camel_shape:
                _emit_inline_nudge(nudge, event=_reply_event(ev, promptish))
            elif extras and camel_shape and promptish:
                # UserPromptSubmit: try additionalContext, which some hosts honour.
                print(json.dumps({
                    'hookSpecificOutput': {
                        'hookEventName': 'UserPromptSubmit',
                        'additionalContext': '\n'.join(extras),
                    }
                }))
            elif nudge and camel_shape:
                # Where PostToolUse stdout is ignored — still record; Stop will gate.
                #
                # THIS USED TO READ `is_grok`, a name that no longer existed. The NameError
                # was swallowed below and the embedded fallback then counted the same step a
                # second time, once every NUDGE_AFTER steps on camelCase hosts. Fixed in nudge
                # mode only: hard, watch and signal must reproduce the pre-2026-10-16 hook
                # byte for byte, double count included (a checker found 17 hard-mode
                # differences in the session file and the Stop text when the fix ran there).
                if _gm_env != 'nudge':
                    raise RuntimeError('pre-2026-10-16 fall-through, kept outside nudge mode')
            return
        except Exception:
            pass  # fall through to embedded copy

    # ── Embedded fallback (older laserbrain or import failure) ──────────────
    try:
        sid = _sid(ev)
        tool = _tool(ev)
        args = _args(ev)
        tool, args = _unwrap(tool, args)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = STATE_DIR / f'{sid}.json'
        # One read-modify-write under the session lock, saved atomically (see _state_lock).
        # If the runtime path just ran in this process and its wait on this same lock ran
        # out (the camelCase fall-through outside nudge mode), try once without waiting: one
        # bounded wait per tool call, not two.
        with _state_lock(path, wait=0.0 if _runtime_gave_up(path) else None):
            s = _load_for_write(path)
            s.setdefault('inferred', []); s.setdefault('events', []); s.setdefault('goal', None)

            prompt = ev.get('prompt')
            if prompt is None:
                prompt = ev.get('userPrompt') if ev.get('userPrompt') is not None else ev.get('promptText')
            if prompt is not None and not tool:
                if not s.get('goal') and is_groundable(prompt):
                    s['goal'] = clean_prompt(prompt)[:400]
                # Mark that the NEXT check_state is a re-ground, not a drift.
                #
                # check_state receives only (goal, progress, distance), and none of those says
                # whether the goal changed because the user changed it. That missing bit made
                # goal-drift 24 of 35 fires in the whole recovered corpus with ZERO coinciding
                # real errors — 22 of the 24 on the first check after Diego spoke. The rule was
                # faithfully reporting that the subject had changed. It had. He changed it.
                #
                # Thresholding on goal overlap cannot substitute: the anchor values at those 24
                # fires run continuously from 0.00 to 0.29 with no gap, so any cut just weakens
                # the rule for everyone. The discriminator genuinely lives out here.
                _mark_user_turn()
                _save_state(path, s)
                return

            # A failed bookkeeping call is ignored, as runtime.normalise ignores it (2026-11-14,
            # round 2 B3): a failed reset_task must not archive and clear the session, and a
            # failed check_state is no reading. Before PostToolUseFailure was wired neither ever
            # arrived, so this keeps the fallback where it was.
            if 'failure' in ename and (_is_check(tool) or _is_reset(tool)
                                       or str(tool).lower().endswith('get_history')):
                return

            if _is_reset(tool):
                # Archive, then clear — mirroring Session.reset in laserbrain.runtime. This
                # branch only runs when importing the SDK failed, but it must not behave
                # differently when it does: a fallback that silently loses data is worse than
                # one that fails outright, because nothing reports it.
                if int(s.get('steps', 0)) > 0:
                    s.setdefault('segments', []).append({
                        'goal': s.get('goal'),
                        'steps': int(s.get('steps', 0)),
                        'checks': s.get('checks', []),
                        'inferred': s.get('inferred', []),
                        'catches': s.get('catches', []),
                        'ended': datetime.datetime.now().isoformat(timespec='seconds'),
                    })
                s.update(steps=0, checks=[], inferred=[], catches=[], events=[], goal=None)
                _save_state(path, s)
                return

            if not tool:
                return

            s['steps'] = int(s.get('steps', 0)) + 1
            step = s['steps']

            if _is_check(tool):
                resp = _resp(ev)
                ti = args
                v = _verdict(resp)

                # ── A CHECK IS A READING. NO READING, NO CHECK. ────────────────────────
                #
                # This appended a row whatever came back, including when the response was not
                # observed at all — and then the row held only what the AGENT had typed:
                # goal, progress, distance, step. No phi, no run id, nothing the instrument
                # said. Those rows are indistinguishable from real readings in every count
                # that matters, including the coverage percentage this gate enforces and any
                # arm comparison the blind probe would make.
                #
                # Measured 2026-08-16: 41 of 56 live checks were exactly this shape, all with
                # phi None and run None. 73% of the recent corpus was the agent talking to
                # itself with no answer written down, and it looked like data.
                #
                # A blind reading is NOT this. Blind carries `arm` and a run id — the server
                # answered and withheld the verdict on purpose, which is a fact worth keeping.
                # Only an unobserved response is dropped, and it is kept as an event so the
                # step is still counted and nothing silently disappears.
                # `run`, `phi` and `arm` are RECENT fields. Testing only for them called every
                # one of the 241 archived checks hollow — rows with real verdicts (advancing,
                # grounded, goal-drift) written by an older hook that stored none of the three.
                # A reading is evidenced by any of them OR by a reason that is not the
                # no-reading default, which is what an old genuine row looks like. Caught by
                # running the rule over the archive before shipping it.
                _r = v.get('reason')
                observed = ((v.get('run') is not None) or (v['phi'] is not None) or bool(v.get('arm'))
                            or (bool(_r) and _r not in ('no-reading', 'unparsed')))
                if not observed:
                    s.setdefault('events', []).append({
                        'step': step, 'kind': 'check-unobserved',
                        'goal': str(ti.get('goal', ''))[:200]})
                    _save_state(path, s)
                    return

                # A withheld verdict is a reading of its own. Recording it as 'no-reading'
                # made the experiment indistinguishable from a parse failure — the probe
                # poisoning the corpus it exists to be measured in.
                reason = 'blind' if (v.get('arm') == 'blind' and v['reason'] == 'no-reading') else v['reason']

                s['checks'].append({'step': step,
                                    'drifting': v['drifting'],
                                    'goal': str(ti.get('goal', ''))[:400],
                                    'progress': str(ti.get('progress', '')),
                                    'distance': ti.get('distance'),
                                    'reason': reason,
                                    'phi': v['phi'],
                                    # The join. `step` above counts tool calls in this session;
                                    # `run`/`run_step` name the row the server wrote. Two
                                    # counters that were never reconcilable now share a key.
                                    'run': v['run'],
                                    'run_step': v['run_step'],
                                    # THE JOIN THAT WAS MISSING. `run` names the server's row by
                                    # UUID; the blind arm names its unit by segment index.
                                    # Neither reaches the other, so the arm is recorded here
                                    # directly and the analysis needs no mapping at all.
                                    # Absent rather than null when unstated — see _verdict.
                                    **({'arm': v['arm']} if v.get('arm') else {}),
                                    # Written only when present, so a row from an older server
                                    # is absent rather than carrying a null that reads like a
                                    # measured "no judgment".
                                    **({'judgment': v['judgment']} if v['judgment'] else {}),
                                    **({'anchored': v['anchored']} if v['anchored'] is not None else {}),
                                    **({'goal_score': v['goal_score']} if v['goal_score'] is not None else {})})
                _save_state(path, s)
                return

            ok_flag = True
            if 'failure' in ename:
                ok_flag = False
            resp0 = _resp(ev)
            if isinstance(resp0, dict):
                code = resp0.get('exit_code')
                if code is None:
                    code = resp0.get('exitCode')
                if isinstance(code, int):
                    ok_flag = code == 0
                elif resp0.get('error') or resp0.get('is_error') or resp0.get('isError'):
                    ok_flag = False

            # Structural only, as before 2026-11-14: the fallback runs when the package cannot be
            # imported, so it carries no copy of runtime's verdict scan. An interrupt (Esc) is the
            # user stopping the call, not the build disagreeing.
            if _is_shell(tool) and not ok_flag and not _is_self_refusal(ev) and not _is_interrupt(ev):
                cmd = str(args.get('command', ''))[:120]
                # `clean`: written by code that excludes the coverage gate. See runtime.py.
                s['catches'].append({'step': step, 'by': 'build',
                                     'what': f'non-zero exit: {cmd}', 'clean': True,
                                     **_attribute(s, step)})

            s['events'].append({'sig': _call_sig(tool, args), 'ok': ok_flag})
            s['events'] = s['events'][-40:]

            s['inferred'].append({'step': step, 'progress': infer_progress(s['events'])})
            s['inferred'] = s['inferred'][-200:]

            last = s['checks'][-1]['step'] if s['checks'] else 0
            since = step - last
            _save_state(path, s)

        if since >= NUDGE_AFTER and since % NUDGE_AFTER == 0 and not camel_shape:
            cov = len(s['checks']) / step if step else 0
            # Labelled with the event that was asked (B1's rule): on PostToolUseFailure the
            # default 'PostToolUse' label is a mismatch Claude Code throws away.
            _emit_inline_nudge(
                f'laserbrain: {since} steps since your last check_state '
                f'(coverage {cov:.0%} over {step} steps). dogfood.py withholds any '
                f'detection result below 50%. Call check_state now with your CURRENT '
                f'goal, progress (advancing|stuck|circling) and distance 0-10.',
                event=_reply_event(ev)
            )
    except Exception:
        pass


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
