#!/usr/bin/env python3
"""lb_coverage.py — PostToolUse / UserPromptSubmit / Stop hook for laserbrain coverage.

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
  2. LOG catches it can see (non-zero shell exits).
  3. INTERRUPT when coverage lapses:
       - hosts that read PostToolUse stdout: additionalContext
       - hosts that ignore it: a Stop gate with decision=block

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
    records its size WITHOUT firing — otherwise the initial scan would replay every
    historical enqueue at once and reground on ancient history.
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
    try:
        with transcript.open('r', errors='replace') as fh:
            if not first_sight:
                fh.seek(offset)
                for line in fh:
                    if '"queue-operation"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if (rec.get('type') == 'queue-operation'
                            and rec.get('operation') == 'enqueue'):
                        found = True
            fh.seek(0, os.SEEK_END)
            state[key] = fh.tell()
    except Exception:
        return

    # Bound the file: one entry per session transcript would otherwise accumulate forever.
    if len(state) > 40:
        state = dict(sorted(state.items(), key=lambda kv: kv[1])[-40:])
    try:
        QUEUE_SCAN.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_SCAN.write_text(json.dumps(state))
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


def infer_progress(events):
    """advancing | stuck | circling, from the tool trace alone.

    Deliberately DUPLICATED from laserbrain.observe.Observer rather than imported. A hook
    runs against whatever python3 is on PATH, and that interpreter may lag the working
    tree. The copy is small and test_hook_parity.py fails if the two ever disagree.
    """
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
        EVIDENCE.write_text(json.dumps(d))
    except Exception:
        pass



def _event_ok(ev, ename):
    """Did this tool call succeed? Read from the response, never from the agent."""
    if 'failure' in ename:
        return False
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
_SELF_REFUSAL_RE = re.compile(r'laserbrain gate:.*?\bcoverage\b', re.IGNORECASE | re.DOTALL)


def _is_self_refusal(ev):
    """True when the response is the coverage gate stopping its own agent."""
    r = _resp(ev)
    try:
        text = r if isinstance(r, str) else json.dumps(r, default=str)
    except Exception:
        return False
    return bool(_SELF_REFUSAL_RE.search(text or ''))


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


def load(path):
    try:
        d = json.loads(path.read_text())
    except Exception:
        d = {'id': path.stem, 'started': datetime.datetime.now().isoformat(timespec='seconds'),
             'goal': None, 'steps': 0, 'checks': [], 'inferred': [], 'catches': [], 'events': []}
    # probe_arm is NOT stamped here any more. It was, for a day, and lost every single
    # write: the SDK's Session in laserbrain/runtime.py owns the same file, holds its dict
    # in memory across this hook's writes, and saves the whole thing back — so the last
    # writer drops the other's keys. Checked 2026-08-03: not one session file carried the
    # arm, including the live one, so the probe was applying arms and recording none.
    # lb_gate.record_arm appends it to probe-arms.jsonl instead, where there is one writer.
    return d


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
    if 'posttooluse' in ename:
        _record_evidence(_event_ok(ev, ename), f'{_tool(ev)}|{str(_args(ev))[:200]}')
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
            if warn:
                if camel_shape:
                    _emit_stop_block(warn)
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
                extras.append(
                    'laserbrain link: multi-step work in a shared repo → link_read '
                    '(limit≥10) and answer open claims before first write. '
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
                if len(checks) >= 2:
                    a, b = checks[-2], checks[-1]
                    da, db = a.get('distance'), b.get('distance')
                    if da is not None and da == db and da not in (0, '0', 0.0):
                        extras.append(
                            'laserbrain honesty: distance has not fallen across the last '
                            'two checks. If you are circling or stuck, say so — false '
                            'advancing wastes the dogfood corpus.'
                        )
            except Exception:
                pass
            if extras and not camel_shape:
                _emit_inline_nudge('\n'.join(extras) + (('\n' + nudge) if nudge else ''))
            elif nudge and not camel_shape:
                _emit_inline_nudge(nudge)
            elif extras and camel_shape and promptish:
                # UserPromptSubmit: try additionalContext, which some hosts honour.
                print(json.dumps({
                    'hookSpecificOutput': {
                        'hookEventName': 'UserPromptSubmit',
                        'additionalContext': '\n'.join(extras),
                    }
                }))
            elif nudge and is_grok:
                # Where PostToolUse stdout is ignored — still record; Stop will gate.
                pass
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
        s = load(path)
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
            path.write_text(json.dumps(s, indent=2))
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
            path.write_text(json.dumps(s, indent=2))
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
                path.write_text(json.dumps(s, indent=2))
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
            path.write_text(json.dumps(s, indent=2))
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

        if _is_shell(tool) and not ok_flag and not _is_self_refusal(ev):
            cmd = str(args.get('command', ''))[:120]
            # `clean`: written by code that excludes the coverage gate. See runtime.py.
            s['catches'].append({'step': step, 'by': 'build',
                                 'what': f'non-zero exit: {cmd}', 'clean': True,
                                 **_attribute(s, step)})

        try:
            args_s = json.dumps(args, sort_keys=True, default=str)[:400]
        except Exception:
            args_s = ''
        s['events'].append({'sig': f'{tool}|{args_s}', 'ok': ok_flag})
        s['events'] = s['events'][-40:]

        s['inferred'].append({'step': step, 'progress': infer_progress(s['events'])})
        s['inferred'] = s['inferred'][-200:]

        last = s['checks'][-1]['step'] if s['checks'] else 0
        since = step - last
        path.write_text(json.dumps(s, indent=2))

        if since >= NUDGE_AFTER and since % NUDGE_AFTER == 0 and not camel_shape:
            cov = len(s['checks']) / step if step else 0
            _emit_inline_nudge(
                f'laserbrain: {since} steps since your last check_state '
                f'(coverage {cov:.0%} over {step} steps). dogfood.py withholds any '
                f'detection result below 50%. Call check_state now with your CURRENT '
                f'goal, progress (advancing|stuck|circling) and distance 0-10.'
            )
    except Exception:
        pass


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
