"""runtime.py — attach the harness to a runtime instead of to your code.

A hook-based host proved the idea and then proved its cost: because a hook runs against
whatever python3 is on PATH, it could not import laserbrain, so the progress rules were
copied into it and pinned together by a test. That works for one runtime. It does not
scale to five, and a drift-detection product maintaining five copies of its drift rules is
a joke with a long setup.

So the logic lives here, once, and a runtime adapter is reduced to the only thing that is
genuinely runtime-specific: the shape of an event. Everything after normalisation —
inference, session recording, the coverage nudge, the file format dogfood.py scores — is
shared.

    from laserbrain.runtime import Session

    s = Session('run-42', goal='ship the sky billboard')
    s.tool('Bash', {'command': 'npm run build'}, ok=False)
    if s.nudge():
        print(s.nudge())           # inject into the agent's context

Any runtime with a tool-call boundary can drive this in about ten lines; see
`from_hook` for any host payload, `from_openai_agents` for that SDK, and `normalise`
for the contract they all meet.
"""
import json, os, pathlib, datetime, re

from .observe import Observer

NUDGE_AFTER = 8          # steps without a SPELLED check before the reminder fires
# NECESSARY, and the only brand left in this package. The path holds the live corpus —
# 1000+ readings and every session record — so renaming it would orphan all of it for a
# cosmetic gain. It is a location, not a claim about who may use it: every agent on the
# machine writes here, which is the point of a shared corpus.
from . import _paths as _P
from . import _evidence                     # the observed channel this session fills
DEFAULT_DIR = _P.sessions_dir()

# Internal dispatchers that wrap a real tool name in their arguments.
_WRAPPER_TOOLS = frozenset({
    'use_tool', 'CallMcpTool', 'call_mcp_tool', 'mcp_tool',
})


def agent_of(ev=None):
    """Which agent is writing this session — for multi-agent corpus splits.

    LASERBRAIN_AGENT is the answer, and in practice the only one used: every hook
    command in every host config sets it explicitly. The fallback exists for a host
    that has not been wired up yet.

    NO VENDOR IS NAMED HERE. This used to enumerate two hosts' session variables by name
    and return the matching brand, and to infer one vendor from
    camelCase event keys and another from snake_case. Both were wrong the same way: an
    instrument shipping a list of which agents exist must be edited to measure a new
    one, and the list is a claim about the world that goes stale. The name is derived
    from whatever <HOST>_SESSION_ID is present, so a host this file has never heard of
    identifies itself.

    A SHAPE IS NOT AN IDENTITY. camelCase versus snake_case says how a payload is
    spelled, not who sent it, and two hosts can share a convention. Guessing a vendor
    from spelling produced a name that looked measured and was not, so the shape hints
    are gone and an unidentifiable agent is 'unknown' — which is true, and which the
    corpus already reports as its own category.
    """
    env = (os.environ.get('LASERBRAIN_AGENT') or '').strip().lower()
    if env:
        return env
    # NO INFERENCE. Deriving the name from a *_SESSION_ID variable was tried and is
    # wrong for the same reason session_id_of stopped doing it: this machine carries
    # a second variable ending _SESSION_ID for a browser pane, so the derived name would
    # have been that pane's — a confident answer nobody measured. Every host config
    # sets LASERBRAIN_AGENT explicitly (10 of 10 hook commands across both hosts here),
    # so the fallback is not carrying weight, and 'unknown' is a true answer the corpus
    # already reports as its own category.
    return 'unknown'


def coerce_args(args):
    """toolInput may arrive as a dict or as a JSON object string."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        s = args.strip()
        if s.startswith('{') or s.startswith('['):
            try:
                j = json.loads(s)
                if isinstance(j, dict):
                    return j
            except Exception:
                pass
        return {'_': args}
    if args is None:
        return {}
    return {'_': args}


def unwrap_tool_args(tool, args):
    """Peel use_tool / CallMcpTool envelopes until we reach real tool + args.

    Two shapes exist:

      1. toolName is the dispatcher (`use_tool`); toolInput holds
         {tool_name, tool_input: real_args}.
      2. some hosts rewrite toolName to `server__tool` for matchers, but
         still leaves toolInput as the outer envelope. Peeling only when tool
         is in _WRAPPER_TOOLS left every check_state with empty goals
         (corpus 2026-07-25: goal='', progress='', distance=None while checks
         still incremented — the gate reopened, dogfood got nothing).

    Peel while the current args look like an envelope and not like flat tool
    arguments (e.g. check_state's goal/progress). Bound the loop so a weird
    payload cannot hang the hook.
    """
    tool = str(tool or '')
    args = coerce_args(args)
    for _ in range(4):
        nested_name = str(
            args.get('tool_name') or args.get('toolName') or args.get('name') or ''
        )
        nested_in = (
            args.get('tool_input') if args.get('tool_input') is not None
            else args.get('toolInput') if args.get('toolInput') is not None
            else args.get('arguments') if args.get('arguments') is not None
            else args.get('parameters') if args.get('parameters') is not None
            else args.get('input') if args.get('input') is not None
            else None
        )
        looks_envelope = nested_in is not None and (
            tool in _WRAPPER_TOOLS
            or nested_name
            or ('tool_input' in args or 'toolInput' in args)
        )
        # Flat check_state / reset args: do not peel past goal/progress.
        if looks_envelope and (args.get('goal') is not None or args.get('progress') is not None):
            if tool not in _WRAPPER_TOOLS:
                break
        if not looks_envelope:
            break
        if nested_name:
            tool = nested_name
        args = coerce_args(nested_in)
    return tool, args


def tokens_so_far(ev):
    """Billable tokens spent in this session up to now, from the host's transcript.

    THE PROBE HAD NO OUTCOME VARIABLE. It is registered to compare what sessions spend with a
    verdict against what they spend without one, and no row it ever wrote carried a count.

    Cache reads are weighted at a tenth and cache writes at 1.25, matching how they bill.
    Folding reads in at face value inflates the figure by a number nobody paid — on one
    session here, 21 billion cache reads against 42 million billable, a factor of 500. A
    'saving' computed against an unweighted total would be measuring the cache, not the work.

    Returns None when there is no transcript to read, which is honest: absent must stay
    distinguishable from zero, or a session with no data reads as a session that spent
    nothing.
    """
    path = (ev or {}).get('transcript_path') or (ev or {}).get('transcriptPath')
    if not path:
        return None
    try:
        total = 0.0
        with open(path, 'r', errors='replace') as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    u = (json.loads(line).get('message') or {}).get('usage') or {}
                except Exception:
                    continue
                total += (u.get('input_tokens', 0)
                          + 1.25 * (u.get('cache_creation_input_tokens') or 0)
                          + 0.10 * (u.get('cache_read_input_tokens') or 0)
                          + 5.0 * u.get('output_tokens', 0))
        return int(total)
    except Exception:
        return None


def session_id_of(ev):
    """session id from a hook event or from any host's <HOST>_SESSION_ID.

    The last resort is NOT the literal 'unknown'. On 2026-07-25 two agents ran in tandem
    and both fell back to it: 50 steps landed in one file with
    two runs interleaved and catches attributed to whichever agent happened to be next.
    A merged session is worse than a missing one — dogfood scores it as though it were a
    single run and reports a confident wrong answer.

    The parent pid is the agent process that spawned this hook, so it is stable across
    every event of one run and different between concurrent runs. Two agents would have
    to share a parent to collide, which is far rarer than sharing a constant.
    """
    if not isinstance(ev, dict):
        ev = {}
    # EXPLICIT, OR THE PARENT PID. Nothing in between.
    #
    # This enumerated two hosts' session variables by name, which meant a third host
    # fell through silently. The obvious repair — scan for any *_SESSION_ID — is worse,
    # and provably so: this machine carries two variables that both end _SESSION_ID, one
    # for the agent and one for a browser pane. Any rule for picking between them
    # by NAME is a guess, and the longest-first rule picked the browser. A wrong session
    # id is worse than none: it merges runs and misattributes catches, which is the exact
    # failure the parent-pid fallback below was written for.
    #
    # So a host that wants its session identity honoured sets LASERBRAIN_SESSION_ID, the
    # same way it already sets LASERBRAIN_AGENT. Declared, not inferred.
    explicit = (ev.get('session_id') or ev.get('sessionId')
                or os.environ.get('LASERBRAIN_SESSION_ID'))
    if explicit:
        return str(explicit)
    return f'unattributed-{os.getppid()}'


_PROMPT_WRAPPERS = ('user_query', 'user_prompt', 'query', 'prompt')


def clean_prompt(text):
    """Unwrap a runtime's prompt envelope.

    Some hosts deliver prompts as '<user_query>\n/hello\n</user_query>'. Stored raw, the
    ground goal becomes markup and every later goal comparison is made against tags.
    """
    t = str(text or '').strip()
    for tag in _PROMPT_WRAPPERS:
        open_t, close_t = f'<{tag}>', f'</{tag}>'
        if open_t in t and close_t in t:
            t = t[t.index(open_t) + len(open_t):t.index(close_t)]
    return t.strip()


# Things a person types that are not a task. Kept SMALL and closed on purpose — see
# is_groundable for why a length rule would be wrong here.
_NOT_A_TASK = {
    'hello', 'hi', 'hey', 'yo', 'hiya', 'hello there', 'hey there', 'good morning',
    'good afternoon', 'good evening', 'morning', 'thanks', 'thank you', 'ty', 'ok',
    'okay', 'k', 'cool', 'nice', 'great', 'sure', 'yes', 'no', 'yep', 'nope', 'test',
    'ping', 'you there', 'are you there', 'hello?', 'still there',
}


def is_groundable(text):
    """Can this prompt serve as the fixed reference every later Φ is measured against?

    On 2026-07-28 a session recorded its ground as 'hello there'. Every distance in that
    session was then measured against a greeting, and the verdicts it produced went into
    the corpus the calibration is tuned on. A ground has to be a task or it grounds
    nothing.

    TWO REJECTIONS ONLY, and the restraint is the point:

      · a slash command ('/hello', '/clear') is addressed to the harness, not a task
      · a bare greeting or acknowledgement from the closed set above

    NOT a length rule, however tempting. The most frequent real tasks in this project's
    own history are two words — 'map all', 'reconcile', 'publish', 'fix them', 'go for
    it' — and a minimum length would throw away exactly the terse seeds that turn out to
    be the largest pieces of work. Better to occasionally ground on something odd than to
    routinely discard the real thing.

    When this returns False the ground is simply not set yet. The next substantive prompt
    takes it, or the agent's first spelled check does — Session.check already grounds on
    the goal the agent states, which is a better source anyway.
    """
    t = clean_prompt(text)
    if not t:
        return False
    if t.startswith('/'):
        return False
    return t.strip().lower().rstrip('.!?') not in _NOT_A_TASK


def normalise(ev):
    """Any runtime's event -> (kind, tool, args, ok, text).

    kind is 'prompt' | 'tool' | 'check' | 'reset' | None. This is the ONLY part an
    adapter has to care about; returning None for kind means "ignore this event", which
    is the right answer for most of what a runtime emits.

    Accepts snake_case and camelCase payloads side by side, whichever host sent them.
    """
    return _normalise(ev)[:5]


def _normalise(ev):
    """normalise() plus `via` (how a failure was known, see _outcome) as a sixth element.

    Session.feed reads this so one event is classified ONCE (2026-11-14, round 2 B3/B4
    review). feed used to call normalise() and then tool_outcome() for the via tag, which
    ran the whole verdict scan twice per call; the hook then ran it a third time for
    evidence. normalise() keeps its 5-tuple for every caller that unpacks five values.
    """
    if not isinstance(ev, dict):
        return (None, '', {}, True, '', '')

    tool, args, resp = _tool_parts(ev)

    # Prompt capture: only when this is not also a tool event.
    prompt = ev.get('prompt')
    if prompt is None:
        prompt = ev.get('userPrompt') if ev.get('userPrompt') is not None else ev.get('promptText')
    if prompt is not None and not tool:
        return ('prompt', '', {}, True, clean_prompt(prompt), '')

    if not tool:
        return (None, '', {}, True, '', '')

    # DID THE CALL FAIL: one rule, _outcome(), shared with lb_coverage._event_ok so catches
    # and evidence cannot disagree. Its structural checks are the ones that stood here, in
    # the same order with the same results: a failure event, an int exit code (which still
    # overrides), an error flag, a string result that begins "error".
    #
    # TEXT DECIDES A CALL FAILED ONLY WHEN ITS OUTPUT ENDS RED (2026-11-14, round 2 B4,
    # research/DAY-FOUR-ROUND2.md). Until then any _FAIL_PATTERNS phrase in the first 4000
    # characters failed the call, and in round 2 all 28 "build catches" it made came from
    # commands that exited 0: "fatal:" from `git status` outside a repo (13), "no such
    # file" (5), AssertionError in piped test output or a `cat` of source (5), errors the
    # worker provoked on purpose (3). A hand label found 16 of those 28 false. A false
    # catch is worse than a missed one: catches are the GROUND TRUTH the harness is scored
    # against, so inventing them would let the instrument grade itself against its own
    # noise.
    #
    # THE VERDICT SCAN STAYS, because a pipe hides a red suite's exit status from every
    # host. `python3 -m unittest` exits 1 and arrives as a failure event (B3); `... 2>&1 |
    # tail -15` exits 0 and has to classify the same. In round 2, 108 lbq calls exited 0
    # with a red unittest verdict, against 26 that failed structurally. The old probe saw 8
    # of the 108, for two reasons: it read json.dumps(resp), whose escaped newlines leave
    # `^` anchoring only at the start of the blob, and it cut at 4000 characters, while
    # unittest prints its verdict last (past the cut in 33 of the 224 red runs it missed
    # across both arms).
    # tool_output_text() decodes what the command printed and red_verdict() reads all of
    # it. Replayed over round 2 with B3 delivery: 134 lbq catches, 7 false, all 7
    # structural and none from text (the old rule: 54 catches, 23 false).
    #
    # The 2026-07-26 lesson still holds — 21 sessions carried zero catches because failures
    # arrive in prose — which is why verdicts are read rather than nothing. _looks_failed
    # is kept for the research suites and the replay; nothing here calls it.
    ok, via = _outcome(ev, tool, resp)

    low_tool = tool.lower()
    # A FAILED BOOKKEEPING CALL IS IGNORED, exactly as it was before failures arrived
    # (2026-11-14, round 2 B3). With PostToolUseFailure wired, a failed check_state became a
    # check row with reason 'no-reading', which inflates coverage and in hard mode can clear
    # the gate, and a failed reset_task archived and reset the session. Both reproduced on
    # the prototype. Keyed on the failure EVENT, not on via == 'event', so a denied one
    # ("THIS CALL DID NOT RUN", via 'denied') is ignored too.
    if _failure_event(ev) and low_tool.endswith(('check_state', 'reset_task', 'get_history')):
        return (None, tool, args, True, '', '')
    if low_tool.endswith('reset_task') or low_tool.endswith('__reset_task'):
        return ('reset', tool, args, True, '', '')
    kind = 'check' if low_tool.endswith('check_state') else 'tool'
    text = json.dumps(resp, default=str) if resp else ''
    # A CHECK REPLY IS PARSED, SO IT IS NEVER CUT (2026-11-14, round 2 B2). The 600 cap
    # applied to every kind, and an MCP check reply serialised this way has a median of 734
    # characters: 128 of 149 round-2 replies were cut mid-JSON, verdict_of() could not parse
    # them, and the session row kept reason 'no-reading' with no phi or run. A cut
    # `drifting: true` reply would have been stored as false. Tool text keeps its cap; since
    # 2026-11-14 Session.feed reads a self-refusal from the event itself (self_refused),
    # not from this text.
    if kind != 'check':
        text = text[:600]
    return (kind, tool, args, ok, text, via)


def _tool_parts(ev):
    """(tool, args, resp) out of any host's tool event, after unwrapping a dispatcher.

    One reading of the payload shape for normalise() and tool_outcome(), so the outcome
    lb_coverage records as evidence is computed from the same fields as the catch.
    """
    tool = str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '')
    args = (ev.get('tool_input') if ev.get('tool_input') is not None
            else ev.get('toolInput') if ev.get('toolInput') is not None
            else ev.get('arguments') if ev.get('arguments') is not None
            else ev.get('parameters') if ev.get('parameters') is not None
            else ev.get('input') if ev.get('input') is not None
            else {})
    tool, args = unwrap_tool_args(tool, args)
    resp = (ev.get('tool_response') if ev.get('tool_response') is not None
            else ev.get('toolResult') if ev.get('toolResult') is not None
            else ev.get('output') if ev.get('output') is not None
            else {})
    return tool, args, resp


# ── WHAT A TOOL CALL'S OUTCOME WAS (2026-11-14, round 2 B3/B4) ─────────────────────────
# A red test-runner or build VERDICT, read from the decoded output. These are the only text
# patterns that fail a call; see the comment in normalise() for the round-2 evidence.
#
# Case-sensitive and line-anchored, which is what makes them safe: a runner prints its
# verdict at the start of a line in a fixed spelling, while "FAILED" or "1 failed" inside a
# log line, a source file or a sentence about tests does not match.
#
# `[^\S\n]` (whitespace but not a newline) where the replay's prototype had `\s`. Same
# verdict on every input, because `^` already tries every line start, but `^\s*` restarted
# at each line of a blank run and scanned the rest of it: 20,000 blank lines took 8 s when
# measured on 2026-11-14, and a 200,000-character run would stall the hook. Now linear.
#
# The same fix for jest's `^Tests?:\s+.*`, whose `\s+` and `.*` overlap: 'Tests:' and 30,000
# spaces took 1.6 s per scan, three scans per hook call. `[^\S\n]+(?=\S)` can split the
# line one way only, and the verdict is the same on every jest summary line, which puts
# the counts on the "Tests:" line itself.
#
# NO "THIS CALL DID NOT RUN" HERE since the B3/B4 review (2026-11-14). As a line pattern it
# matched anywhere: a successful `grep -n "THIS CALL DID NOT RUN" lb_safety.py` became a
# 'denied' catch and an evidence failure, and so did 12 of 12 successful greps and diffs of
# gate source in Diego's last 30 days of transcripts. A hook's denial is a message that
# BEGINS with its deny text; red_verdict() tests that with _DENIAL_HEAD_RE below.
_VERDICT_RED_RE = re.compile('|'.join([
    r'^[^\S\n]*(?:\d+[^\S\n]+)?FAILED \((?:failures|errors)=\d+',        # unittest (also after uniq -c)
    r'^[^\S\n]*(?:\d+[^\S\n]+)?(?:FAIL|ERROR): test\w* \([\w.]+\)\s*$',  # unittest per-test header
    r'^=+ .*\b\d+ (?:failed|errors?)\b.*=+\s*$',                          # pytest summary line
    r'^[^\S\n]*(?:\*\* )?(?:BUILD|EXPORT|ARCHIVE) FAILED\b',              # xcodebuild
    r'^Tests?:[^\S\n]+(?=\S)[^\n]*\b\d+ failed\b',                        # jest
]), re.MULTILINE)
# A green verdict. The LAST verdict wins, so a suite run red and then green in one call
# (fix, rerun) is a success.
#
# `[^\S\n]*\n(?:[^\S\n]*\n)+` is the prototype's `\s*\n\s*\n`: any whitespace run that holds
# two or more newlines and ends in one. Written so it splits one way only, because the
# overlapping form went quadratic on a "Ran N tests" line followed by a long blank run.
_VERDICT_GREEN_RE = re.compile(
    r'^Ran \d+ tests? in [\d.]+s[^\S\n]*\n(?:[^\S\n]*\n)+(?:OK\b|NO TESTS RAN)'
    r'|^=+ (?:(?!failed|error).)*\b\d+ passed\b(?:(?!failed|error).)*=+\s*$', re.MULTILINE)

# ── A HOOK'S REFUSAL IS KNOWN BY ITS HEAD (2026-11-14, round 2 B3/B4 review) ─────────────
# A refusal or a denial is a MESSAGE THAT BEGINS WITH THE DENY TEXT. Claude Code delivers it
# bare ("laserbrain gate: ...") or behind its hook prefix ("PreToolUse:Bash hook error: " or
# "PreToolUse:Edit hook error: [command]: "): those are the only two shapes among the 474
# hook denials (423 coverage gate, 51 lb_safety) in Diego's last 30 days of transcripts,
# and every one says THIS CALL DID NOT
# RUN within its first lines. A command that ran and failed starts with "Exit code N"
# instead, and a command that ran and succeeded starts with whatever it printed. lb_gate's
# non-blocking warning ("... Reads still pass.") has no THIS CALL DID NOT RUN, so a log that
# opens with one is not a refusal either.
#
# WHY NOT SEARCH THE WHOLE TEXT, as is_self_refusal() does. That search ran over every call
# once B3 brought failures in, and it took two kinds of real work away:
#   - 63 successful Reads, greps and diffs of laserbrain's own source or logs in those
#     transcripts stopped counting as evidence, because the source quotes the deny text;
#   - a red suite whose output quotes the gate (laserbrain's own test_proportional_gate
#     prints three such lines on a normal run) lost its catch, because "laserbrain gate:"
#     followed anywhere by "coverage" read as the gate refusing.
# It was also slow: a lazy DOTALL search over 200,000 characters of "laserbrain gate:" lines
# with no "coverage" took 2.7 s, four times per hook call. These tests read six lines at most.
# The bracketed command may itself hold ']' (the plugin's own hook command has `[ -n "$LB_PY" ]`),
# so the group runs lazily to the first ']: ' that the deny text follows, on one line only.
_REFUSAL_LEAD = r'\A\s*(?:PreToolUse:\S+ hook error: (?:\[[^\n]*?\]: )?)?'
_DID_NOT_RUN = r'(?:[^\n]*\n){0,5}?[^\n]*?\bTHIS CALL DID NOT RUN\b'
# The coverage gate (its coverage clause is on the first line of every refusal lb_gate
# writes) and the enforced drift gate: the instrument refusing, never a catch.
_SELF_REFUSAL_HEAD_RE = re.compile(
    _REFUSAL_LEAD + r'laserbrain (?:gate:(?=[^\n]*\bcoverage\b)|drift gate:)' + _DID_NOT_RUN,
    re.IGNORECASE)
# Any laserbrain hook's denial, the claim gate and lb_safety included.
_DENIAL_HEAD_RE = re.compile(
    _REFUSAL_LEAD + r'laserbrain (?:claim gate|safety|gate|drift gate):' + _DID_NOT_RUN,
    re.IGNORECASE)
# File-content and subagent tools are never text-scanned: a Read of a red log, a Write of a
# test file or a subagent's report quoting a red run is not the call failing. The last four
# names are Grok's.
_NO_TEXT_SCAN = frozenset({
    'read', 'write', 'edit', 'multiedit', 'notebookedit', 'notebookread', 'grep', 'glob', 'ls',
    'task', 'agent', 'webfetch', 'websearch', 'todowrite',
    'read_file', 'write_file', 'edit_file', 'list_dir'})
# A very long output is read at both ends: a verdict comes last, and a runner's own header
# (or an early crash) comes first.
_SCAN_HEAD, _SCAN_TAIL = 20_000, 180_000


def _blocks_text(blocks):
    """The text blocks of an MCP content list, joined. Images and other blocks are skipped."""
    out = []
    for b in blocks:
        if isinstance(b, str):
            out.append(b)
        elif isinstance(b, dict) and b.get('type') == 'text':
            out.append(str(b.get('text') or ''))
    return '\n'.join(out)


def tool_output_text(tool, resp):
    """The text a command PRINTED, decoded, never json.dumps(resp).

    '' for file-content and subagent tools (_NO_TEXT_SCAN) and for shapes that carry no
    printed text. A string result is itself; an MCP content list is its text blocks; a
    Bash result is stdout then stderr; another host's {output: str} is that output.
    """
    if str(tool or '').lower() in _NO_TEXT_SCAN:
        return ''
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return _blocks_text(resp)
    if isinstance(resp, dict):
        if 'stdout' in resp or 'stderr' in resp:
            return f"{resp.get('stdout') or ''}\n{resp.get('stderr') or ''}"
        if isinstance(resp.get('content'), list):
            return _blocks_text(resp['content'])
        if isinstance(resp.get('output'), str):
            return resp['output']
    return ''


def _message_texts(ev, resp):
    """Every field a hook's refusal can arrive in, decoded, never json.dumps.

    The failure event's `error` (Claude Code's PostToolUseFailure), a string result, an MCP
    content list, and the message fields of a result dict ({isError, content: str} from an
    SDK, {error} from the OpenAI Agents adapter, {stdout, stderr} from Bash, {output} from
    other hosts). Each is tested at its own head: a refusal is a message, not a quotation.
    """
    out = []
    e = error_text(ev)
    if e:
        out.append(e)
    if isinstance(resp, str):
        out.append(resp)
    elif isinstance(resp, list):
        out.append(_blocks_text(resp))
    elif isinstance(resp, dict):
        for k in ('content', 'output', 'stderr', 'stdout', 'error', 'errorMessage', 'message'):
            v = resp.get(k)
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, list):
                out.append(_blocks_text(v))
    return out


def starts_as_self_refusal(text):
    """True when this message IS the coverage gate or the enforced drift gate refusing: it
    begins with the deny text. Quoting that text later in the output is not refusing."""
    return bool(text) and bool(_SELF_REFUSAL_HEAD_RE.match(text))


def starts_as_denial(text):
    """True when this message IS a laserbrain hook's denial (THIS CALL DID NOT RUN)."""
    return bool(text) and bool(_DENIAL_HEAD_RE.match(text))


def self_refused(ev):
    """The coverage gate or the enforced drift gate refused this call: one of its message
    fields (see _message_texts) begins with the deny text. The rule lb_coverage's
    _is_self_refusal copies, so catches and evidence exclude the same calls."""
    if not isinstance(ev, dict):
        return False
    _tool, _args, resp = _tool_parts(ev)
    return any(starts_as_self_refusal(t) for t in _message_texts(ev, resp))


def red_verdict(text):
    """True when the LAST test or build verdict in the text is red, or when the text is a
    hook's denial (it begins with one: the call did not run).

    The coverage gate's own refusal is never red, for the reason it is never a catch
    anywhere else. Both of those are read at the head of the text only; see
    _SELF_REFUSAL_HEAD_RE.
    """
    if not text:
        return False
    if len(text) > _SCAN_HEAD + _SCAN_TAIL:
        text = text[:_SCAN_HEAD] + '\n' + text[-_SCAN_TAIL:]
    if starts_as_self_refusal(text):
        return False
    if starts_as_denial(text):
        return True
    reds = [m.start() for m in _VERDICT_RED_RE.finditer(text)]
    if not reds:
        return False
    greens = [m.start() for m in _VERDICT_GREEN_RE.finditer(text)]
    return not greens or max(reds) > max(greens)


def error_text(ev):
    """A failure event's own message: `error`, else `errorMessage`; '' when absent.

    Claude Code's PostToolUseFailure carries the failure ONLY here ("Exit code 1\\n...", or
    a hook's denial) and sends no tool_response, so a test that reads the response alone
    is blind to it.
    """
    if not isinstance(ev, dict):
        return ''
    e = ev.get('error')
    if e is None:
        e = ev.get('errorMessage')
    if e is None:
        return ''
    if isinstance(e, str):
        return e
    try:
        return json.dumps(e, default=str)
    except Exception:
        return str(e)


def is_interrupt(ev):
    """The user stopped the call (Esc). Counted as a step, never as a catch or evidence."""
    return isinstance(ev, dict) and bool(ev.get('is_interrupt') or ev.get('isInterrupt'))


def _failure_event(ev):
    """The host delivered this call on its failure event (PostToolUseFailure and kin)."""
    return 'failure' in str(ev.get('hookEventName') or ev.get('hook_event_name') or '').lower()


def _outcome(ev, tool, resp):
    """(ok, via): did this tool call fail, and how is that known.

    via is '' for a success, otherwise:
      'event'    the host said so: its failure event (PostToolUseFailure, post_tool_use_failure)
      'exit'     an int exit_code / exitCode that is not 0
      'flag'     error / is_error / isError, or a string result that begins "error"
      'verdict'  no structural failure, but the decoded output ends in a red verdict
      'denied'   a hook refused it: a message field BEGINS with its deny text and THIS CALL
                 DID NOT RUN (the claim gate or lb_safety). The coverage and drift gates
                 are self-refusals and never become catches; see self_refused.

    The structural part is the pre-2026-11-14 normalise() order, result for result, so
    every event it classified then is classified the same now. Only the text step is new.
    """
    ok, via = True, ''
    if _failure_event(ev):
        ok, via = False, 'event'
    if isinstance(resp, dict):
        code = resp.get('exit_code')
        if code is None:
            code = resp.get('exitCode')
        if isinstance(code, int):
            ok = code == 0
            via = '' if ok else 'exit'
        elif resp.get('error') or resp.get('is_error') or resp.get('isError'):
            ok, via = False, 'flag'
    elif isinstance(resp, str) and resp.strip().lower().startswith('error'):
        ok, via = False, 'flag'
    if ok and red_verdict(tool_output_text(tool, resp)):
        ok, via = False, 'verdict'
    # 'denied' only when a message BEGINS with a hook's deny text (_DENIAL_HEAD_RE). A
    # substring test tagged a real exit-1 failure that merely printed the phrase as a
    # denial, so a scorer splitting denials out would have dropped it.
    if not ok and any(starts_as_denial(t) for t in _message_texts(ev, resp)):
        via = 'denied'
    return ok, via


def tool_outcome(ev):
    """(ok, via) for one raw tool event, by the rule normalise() uses. (True, '') for
    anything that is not a dict. lb_coverage reads evidence through this."""
    if not isinstance(ev, dict):
        return True, ''
    tool, _args, resp = _tool_parts(ev)
    return _outcome(ev, tool, resp)


class Session:
    """A recorded run, in the shape dogfood.py scores.

    Deliberately does NOT call check_state itself. It cannot: distance is not inferable
    and the goal must come from the task as first stated, not from the runtime's guess at
    what the agent is doing now. It counts, it infers what is inferable, and it interrupts
    when coverage lapses. The spelled check stays the agent's to make.
    """

    def __init__(self, session_id, goal=None, directory=None, nudge_after=NUDGE_AFTER):
        self.path = pathlib.Path(directory or DEFAULT_DIR) / f'{session_id}.json'
        self.nudge_after = nudge_after
        self.d = self._load(session_id)
        if goal and not self.d.get('goal'):
            self.d['goal'] = str(goal)[:400]
        self._obs = Observer(self.d.get('goal') or 'unset')

    def _load(self, sid):
        try:
            d = json.loads(self.path.read_text())
        except Exception:
            d = {'id': sid, 'started': datetime.datetime.now().isoformat(timespec='seconds'),
                 'goal': None, 'steps': 0, 'checks': [], 'inferred': [], 'catches': [],
                 'events': []}
        if not d.get('agent'):
            d['agent'] = agent_of()
        return d

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.d.get('agent'):
            self.d['agent'] = agent_of()
        self.path.write_text(json.dumps(self.d, indent=2))
        return self

    # ── the three things a runtime can tell us ──────────────────────────────
    def prompt(self, text):
        """The task as first stated. Captured ONCE, and only at the true start of a run.

        After a reset_task the goal is deliberately absent, and the next thing the user
        types is usually a continuation rather than a task — on 2026-07-25 a session
        recorded its ground as 'do all', which makes every later goal-drift verdict
        meaningless. Following a reset the ground comes from the next SPELLED check,
        where the agent states the goal explicitly, not from whatever was typed next.
        """
        t = clean_prompt(text)
        if not t:
            return self
        if self.d.get('goal') or self.d.get('was_reset'):
            return self
        # A greeting is not a task. Leaving the ground unset costs one session's early
        # verdicts; setting it to 'hello there' corrupts every verdict in the session and
        # then the corpus, which is worse and much harder to notice.
        if not is_groundable(t):
            return self
        self.d['goal'] = t[:400]
        self._obs = Observer(self.d['goal'])
        return self.save()

    def tool(self, name, args=None, ok=True, self_refusal=False, via=None):
        self.d['steps'] += 1
        # FEED THE OBSERVED CHANNEL. This session has always known every tool call and its
        # outcome; the harness's corroboration channel had no wire to it and depended on the
        # caller remembering to call saw(). Almost nobody did, so `anchored` returned 0.5 for
        # its whole life and the fault went unseen because nothing leaned on it.
        #
        # A self-refusal is excluded for the same reason it is excluded from `catches`: the
        # coverage gate blocking its own agent is the instrument disagreeing with itself, not
        # work that happened. Counting it as observed work would let the harness corroborate
        # its own interruptions.
        # Not when the hook is the writer (LASERBRAIN_HOOK_EVIDENCE, set by lb_coverage in its
        # own process): it already counted this call, and two writers counted it twice
        # (round 2, B5).
        if not self_refusal and not os.environ.get('LASERBRAIN_HOOK_EVIDENCE'):
            try:
                _evidence.bump(ok=ok)
            except Exception:
                pass          # evidence is an addition to the reading, never a precondition
        self._obs.record(name, args, ok=ok)
        self.d['events'] = [{'sig': e['sig'], 'ok': e['ok']} for e in self._obs.events][-40:]
        self.d['inferred'].append({'step': self.d['steps'], 'progress': self._obs.progress(),
                                   'why': self._obs.why()})
        self.d['inferred'] = self.d['inferred'][-200:]
        if not ok and not self_refusal:
            # A failed call is a guard failing or a test going red — dogfood ground truth,
            # recorded without anyone judging anything.
            #
            # `self_refusal` is the one exception, and it is the whole reason this parameter
            # exists: the coverage gate blocking its own agent is not the world disagreeing,
            # it is the instrument disagreeing with itself, and counting it makes the hit
            # rate 0% by construction. See is_self_refusal.
            #
            # `clean` marks a catch as written by code that knows to exclude the coverage
            # gate. It is a version stamp, not a quality claim. Catches already on disk are
            # stored as bare "failed call: Bash" with no text kept, so a gate block cannot
            # be told from a real failure after the fact — they are unusable for sensitivity
            # and sensitivity.py drops anything without this flag. Dating them would not
            # work: the fix landed mid-session, so the contaminated catches share a date
            # with the clean ones.
            #
            # `via` says how the failure was known (see _outcome): 'event', 'exit', 'flag',
            # 'verdict' or 'denied'. Added 2026-11-14 (round 2 B3/B4) and written only when
            # known, so a catch made before the fix has none and the two eras stay separable;
            # 'denied' lets a scorer split hook refusals from the world disagreeing.
            self.d['catches'].append({'step': self.d['steps'], 'by': 'build',
                                      'what': f'failed call: {name}', 'clean': True,
                                      **({'via': via} if via else {}),
                                      **self.attribute()})
        return self.save()

    def attribute(self):
        """Which drift reading was live right now — the join, from the catch's side.

        Catches are the only evidence here that the agent did not produce about itself: a
        failed call is the build disagreeing, and the build holds no opinion about the
        instrument. That makes them the sole possible source of sensitivity. But a catch
        could not name the reading it belonged to, so `corpus-map.py` printed d-prime as
        "not computable, now or ever, from this corpus". It is computable from the moment
        both sides carry the same key, and this is that side.

        `since` travels with it because attribution decays with distance. A failure one
        step after a reading was live under it; a failure fourteen steps later fell in a
        stretch the instrument was never shown, and scoring that as a MISS would blame the
        detector for not firing on a step it never saw. Coverage here runs near 24%, so
        most catches land in exactly that unwatched gap — which makes the ability to
        DISCARD the far ones the difference between a sensitivity number and a fiction.
        """
        checks = self.d.get('checks') or []
        if not checks:
            return {'run': None, 'run_step': None, 'since': None}
        last = checks[-1]
        return {'run': last.get('run'),
                'run_step': last.get('run_step'),
                'since': int(self.d.get('steps', 0)) - int(last.get('step') or 0)}

    def check(self, goal, progress, distance, drifting, reason=None, phi=None,
              run=None, run_step=None, anchored=None, goal_score=None, judgment=None,
              tokens=None):
        """A SPELLED check. Inputs are recorded so the session can be replayed under a
        different calibration — see calibrate.py.

        `reason` and `phi` are the verdict as returned, kept so the corpus can be asked
        WHICH signal fired. Without them every fire is an undifferentiated True and the
        question "do goal-drift fires cluster on goal restatements" cannot be asked of the
        data at all. Optional, because older callers pass four positional arguments.

        `run` and `run_step` are the drift log's primary key, carried so a catch recorded
        HERE can name the reading that was live when it happened. Two step counters ran
        side by side — this file counting tool calls, the server counting readings — with
        nothing joining them, which is why precision was computable and d-prime was not.
        Also optional: a caller that does not have them is an older server, and None must
        stay distinguishable from a real run so those rows can be excluded rather than
        silently joined to nothing.
        """
        self.d['steps'] += 1
        rec = {'step': self.d['steps'], 'drifting': bool(drifting),
               'goal': str(goal)[:400], 'progress': str(progress),
               'distance': distance}
        if reason is not None:
            rec['reason'] = str(reason)
        if phi is not None:
            rec['phi'] = phi
        if run is not None:
            rec['run'] = str(run)
        if run_step is not None:
            rec['run_step'] = run_step
        # THE THREE FIELDS THIS RECORD WAS MISSING, and the reason they had to land HERE.
        #
        # lb_coverage was taught to extract them on 2026-08-04 and they never reached a
        # file. This method is the writer that wins: Session owns the session path, holds
        # its dict across the hook's writes and saves the whole thing back, so a richer row
        # written next door is overwritten by this one. The same race is already documented
        # against `probe_arm`, which is why arms.jsonl exists — and it ate the new fields
        # for a full day before anyone looked at a stored row.
        #
        #   anchored    how much of Phi rests outside the agent's own account of itself.
        #               0.5 on the published calibration and reported on every verdict
        #               since it was added; without it stored, "does corroboration predict
        #               a true catch" cannot be asked.
        #   goal_score  still the errand that was asked for? Phi does not answer that: a
        #               faithful goal sits at high Phi when the work is hard.
        #   judgment    what the harness told the agent to DO — abandon, narrow, unbacked.
        #               The strongest counsel it owns, and the corpus held none of it.
        #
        # Optional in the same way `reason` and `run` are: an older caller omits them, and
        # an absent key stays distinguishable from a measured None.
        if anchored is not None:
            rec['anchored'] = anchored
        if goal_score is not None:
            rec['goal_score'] = goal_score
        # THE PROBE'S OUTCOME VARIABLE, and until 2026-08-19 nothing collected it.
        #
        # The blind probe exists to say what a session spent with a verdict against what it
        # spent without one. Zero of 3,392 drift rows had ever carried a token count, so the
        # comparison it was registered to make could not be computed from its own data at any
        # sample size. Assignment worked; there was simply no outcome to assign.
        #
        # Cumulative, not per-step: what a step cost is the difference between consecutive
        # checks, and a difference is recoverable from cumulative counts while the reverse is
        # not — a dropped row loses one interval instead of corrupting the total.
        if tokens is not None:
            rec['tokens'] = int(tokens)
        if judgment:
            rec['judgment'] = judgment
        self.d['checks'].append(rec)
        # After a reset the agent's own spelled goal is authoritative — it is the task as
        # the agent states it, which is exactly what a ground should be.
        if not self.d.get('goal') and str(goal).strip():
            self.d['goal'] = str(goal)[:400]
            self.d['was_reset'] = False
            self._obs = Observer(self.d['goal'])
        return self.save()

    def reset(self):
        """Close the current segment and start a new one.

        ARCHIVE, then clear. This used to be a bare wipe, and it was quietly destroying the
        entire dogfood corpus: the design tells an agent to reset_task on every genuinely
        new task, so a working session resets five or six times and each reset threw away
        that segment's checks, fires and catches. On 2026-07-25 a ~100-step session was on
        disk as "steps: 4", and the whole nine-session corpus held 0 fires — while the
        transcript of one session mentioned check_state on 1695 lines. The harness had been
        firing all along; the record of it was deleted at every task boundary.

        A segment is also the RIGHT unit to score, not merely a salvaged one. A reset is a
        wave boundary: one declared goal, one interval, one denominator. Coverage over a
        whole session averages a disciplined stretch together with the ungrounded scramble
        before the first check; per segment, each is visible for what it was.
        """
        if int(self.d.get('steps', 0)) > 0:
            self.d.setdefault('segments', []).append({
                'goal': self.d.get('goal'),
                'steps': int(self.d.get('steps', 0)),
                'checks': self.d.get('checks', []),
                'inferred': self.d.get('inferred', []),
                'catches': self.d.get('catches', []),
                'ended': datetime.datetime.now().isoformat(timespec='seconds'),
            })
        self.d.update(steps=0, checks=[], inferred=[], catches=[], events=[], goal=None,
                      was_reset=True)
        self._obs = Observer('unset')
        return self.save()

    # ── what it gives back ──────────────────────────────────────────────────
    @property
    def coverage(self):
        return (len(self.d['checks']) / self.d['steps']) if self.d['steps'] else 0.0

    def steps_since_check(self):
        last = self.d['checks'][-1]['step'] if self.d['checks'] else 0
        return self.d['steps'] - last

    def goal_shape_note(self):
        """Advice when the ground reads as a report rather than an intention, else None.

        Attached to the nudge instead of raised on its own: the observation is only useful
        at the moment the agent is about to restate its goal, and that is exactly when the
        nudge already speaks. See reads_as_report for why this never touches a verdict.
        """
        g = self.d.get('goal')
        if not reads_as_report(g or ''):
            return None
        return (f'Your ground reads as a report of what happened, not what you are '
                f'pursuing: "{str(g)[:60]}". A ground has to stay fixed while the work '
                f'moves, and a sentence about what was just finished cannot — by the next '
                f'step something else has been. State the goal as the thing you are trying '
                f'to reach; it is 5x more likely to fire drift otherwise.')

    def nudge(self):
        """The reminder, or None. Fires every `nudge_after` steps without a spelled check
        rather than once, because one message scrolls away."""
        since = self.steps_since_check()
        if since < self.nudge_after or since % self.nudge_after:
            return None
        base = (f'laserbrain: {since} steps since your last check_state '
                f'(coverage {self.coverage:.0%} over {self.d["steps"]} steps). '
                f'dogfood.py withholds any detection result below 50%. Call check_state '
                f'now with your CURRENT goal, progress (one word: advancing|stuck|circling; a note goes in doing) and distance 0-10.')
        note = self.goal_shape_note()
        return f'{base}\n{note}' if note else base

    def coverage_warning(self):
        """Nudge text whenever coverage has lapsed (not only on the modulo edge).

        Used by Stop hooks on hosts that ignore PostToolUse stdout, where the only
        injection point that reaches the model is a stop-gate reason.
        """
        since = self.steps_since_check()
        if since < self.nudge_after:
            return None
        return (f'laserbrain: {since} steps since your last check_state '
                f'(coverage {self.coverage:.0%} over {self.d["steps"]} steps). '
                f'dogfood.py withholds any detection result below 50%. Call check_state '
                f'now with your CURRENT goal, progress (one word: advancing|stuck|circling; a note goes in doing) and distance 0-10.')

    def feed(self, ev):
        """Drive the session from one raw runtime event. Returns a nudge or None.

        The check branch reads the verdict with `verdict_of` rather than by searching the
        raw text for '"drifting": true'. That search was here until 2026-07-25 and it never
        matched a real response: an MCP result arrives wrapped as
        {"content":[{"type":"text","text":"{...}"}]}, and serialising it escapes the inner
        quotes to \\"drifting\\". Every fire was written to disk as drifting=False while the
        agent was being told, in the same call, that it had drifted.

        The cost was the corpus. 204 checks over 10 sessions recorded ZERO fires, 104 of
        them below the 0.30 overlap that defines goal-drift. dogfood.py reported
        "PRECISION undefined — the harness never fired in these sessions", which read as a
        quiet instrument and was a deaf one. The 8% precision we publish had to be
        recovered from chat transcripts because the session files never held it.
        """
        kind, tool, args, ok, text, via = _normalise(ev)
        if kind == 'prompt':
            self.prompt(text); return None
        if kind == 'reset':
            self.reset(); return None
        if kind == 'check':
            v = verdict_of(text)
            self.check(args.get('goal', ''), args.get('progress', ''), args.get('distance'),
                       v['drifting'], reason=v['reason'], phi=v['phi'],
                       run=v.get('run'), run_step=v.get('run_step'),
                       anchored=v.get('anchored'), goal_score=v.get('goal_score'),
                       judgment=v.get('judgment'),
                       # Read from the host's own transcript, which is the only first-hand
                       # record of what was billed. The agent cannot report its own spend and
                       # a hook cannot ask the API, so this is the one available source.
                       tokens=tokens_so_far(ev))
            return None
        if kind == 'tool':
            # A refusal can arrive in the failure event's own `error` field, with no response
            # at all (2026-11-14, round 2 B3), so both are read. The user pressing Esc is
            # handled the same way: the step counts, the build did not disagree.
            #
            # Read at the HEAD of each message (self_refused), not searched for in `text`:
            # a red suite or a Read of gate source quotes the deny text, and the search made
            # the one lose its catch and the other its evidence (B3/B4 review). `via` comes
            # from the same classification as `ok`, so the event is scanned once.
            refused = self_refused(ev) or is_interrupt(ev)
            self.tool(tool, args, ok, self_refusal=refused, via=via or None)
            return self.nudge()
        return None


# ── adapter shapes — thin wrappers over the same path ───────────────────────
# Failure signatures that a tool reports in its TEXT rather than in a status field.
#
# NOT USED BY normalise() SINCE 2026-11-14 (round 2 B4): every one of round 2's 28 text
# catches came from a command that exited 0, and the verdict-only rule (_VERDICT_RED_RE,
# _outcome) replaced it. Kept, with this behaviour, for research/test_self_refusal.py and
# the round-2 replay, which import _looks_failed and _FAIL_PATTERNS.
#
# Kept deliberately short and specific. A catch is the ground truth this harness is scored
# against, so a false catch is strictly worse than a missed one: it would let the instrument
# grade itself against noise it generated. Every entry here is a phrase that does not occur
# in ordinary successful output.
#
# Anchored where possible. "error" alone is useless — it matches "no errors", "error
# handling", and every log line about the concept. `^error` and ": error:" (the compiler
# convention) do not.
_FAIL_PATTERNS = [
    r'^\s*error\b',                     # a line that begins by declaring failure
    r':\s*error:',                      # clang/swift/tsc convention: file:line: error:
    r'command not found',
    r'no such file or directory',
    r'permission denied',
    r'^\s*Traceback \(most recent call last\)',
    r'\bBUILD FAILED\b', r'\bEXPORT FAILED\b', r'\bARCHIVE FAILED\b',
    # A hook denied it. Independent ground truth for the safety block and the claim gate —
    # both catch a condition outside the instrument. NOT for the coverage gate, which is
    # filtered by _SELF_REFUSAL_RE below before this pattern is ever consulted.
    r'\bTHIS CALL DID NOT RUN\b',
    r'\bfatal:', r'\bfatal error\b',
    r'^\s*FAIL\b',
    r'\bexit code [1-9]', r'\bexit status [1-9]',
    r'\bAssertionError\b', r'\bSyntaxError\b',
]
_FAIL_RE = re.compile('|'.join(_FAIL_PATTERNS), re.IGNORECASE | re.MULTILINE)

# Phrases that LOOK like failures and are not. A guard that reports "0 errors" or a test
# suite that says "no such file or directory: expected" would otherwise manufacture catches.
_NOT_FAIL_RE = re.compile(
    r'\b(0|no|zero)\s+(errors?|failures?)\b|\berrors?:\s*0\b|\bno errors found\b',
    re.IGNORECASE)


# The coverage gate's own refusal, which must never become a catch.
#
# THE CIRCLE, measured 2026-08-02. sensitivity.py reported 0 hits and 8 misses — a 0.0%
# hit rate — and every one of the eight was this gate blocking a call in the session that
# was analysing it. The number was not a measurement. It was an identity:
#
#   the coverage gate fires BECAUSE the instrument has been quiet (a lapse IS "too many
#   steps since check_state"), the block exits non-zero, the non-zero exit is recorded as
#   a catch, and the reading live at that moment is by definition a quiet one.
#
# So a coverage-gate catch can never coincide with a fire, and the hit rate it produces is
# 0% before any data is collected. The comment above _FAIL_PATTERNS already named the rule
# this breaks — "a false catch is strictly worse than a missed one: it would let the
# instrument grade itself against noise it generated" — and this was the instrument
# grading itself against exactly that.
#
# Anchored on "laserbrain gate:" WITH the coverage clause, which is narrow on purpose.
# "laserbrain claim gate:" (another agent holds the path) and "laserbrain safety:"
# (rm -rf and friends) each catch a condition the instrument did not create, and both
# remain catches (tagged via 'denied' since 2026-11-14, so a scorer can split them out).
#
# THE ENFORCED DRIFT GATE TOO, since 2026-11-14 (round 2 B3). "laserbrain drift gate:"
# refuses BECAUSE a reading fired, so its block coincides with a fire by construction: the
# mirror image of the 2026-08-02 circle, an identity that would inflate the hit rate the way
# the coverage gate deflated it. It could not reach a post hook on Claude Code until
# PostToolUseFailure was wired, which is why it was never needed here before.
#
# THIS SEARCH IS NO LONGER WHAT THE LIVE PATH USES (2026-11-14, B3/B4 review). It finds the
# deny text ANYWHERE, which a Read of lb_gate.py or a red laserbrain suite also contains.
# normalise(), Session.feed and lb_coverage read the refusal at the head of each message
# instead (_SELF_REFUSAL_HEAD_RE, self_refused). This search stays, unchanged, for
# _looks_failed, research/test_self_refusal.py and the round-2 replay.
_SELF_REFUSAL_RE = re.compile(r'laserbrain gate:.*?\bcoverage\b|laserbrain drift gate:',
                              re.IGNORECASE | re.DOTALL)


def is_self_refusal(text: str) -> bool:
    """True when this text CONTAINS the coverage gate or the enforced drift gate refusing.

    Not ground truth in either direction: the call did not run, so nothing was proved
    about the world — only that the instrument stopped its own agent.

    A containment test, kept for _looks_failed and the research suites. Whether a CALL was
    refused is self_refused(ev), which reads the head of each message field.
    """
    return bool(text) and bool(_SELF_REFUSAL_RE.search(text))


# A goal written as a REPORT of what happened rather than a statement of what is being
# pursued. Advisory only — see reads_as_report.
#
# Closed list, and deliberately not a generic /^\w+ed\b/. That catch-all read "Speed up the
# build" and "Need to fix the parser" as reports, and swallowed the imperative "read
# auth.py", whose past and present forms are identical. Measured on 1,191 readings: the
# closed list separates fires from quiet readings at 12.2% vs 2.2% (5.4x, z = 6.87), and
# the generic version scored no better while matching things that are plainly goals.
_REPORT_RE = re.compile(
    r'^\s*(?:'
    r'confirmed|found|promoted|shipped|verified|discovered|learned|identified|determined|'
    r'established|noted|observed|settled|decided|chose|approved|completed|finished|landed|'
    r'merged|fixed|added|committed|created|validated|pushed|reviewed|replaced|updated|built|'
    r'wrote|ran|removed|renamed|moved|deleted|refactored|implemented|deployed|published|'
    r'tested|checked|design settled|build (?:blocked|failed)|blocked by'
    r')\b', re.IGNORECASE)


def reads_as_report(text: str) -> bool:
    """True when a goal narrates what happened instead of naming what is being pursued.

    WHY THIS IS ADVICE AND NOT A VERDICT

    Reading the fires labelled false showed most were not goals at all: "Confirmed all 31
    test files pass locally", "Promoted new-repo.json to shipped workflows", "Build blocked
    by a stale gate", "Diego chose verdict outcome capture". The goal field was being used
    as a progress-narration slot, so each step reported a different fact, consecutive goals
    shared few tokens, overlap collapsed, and goal-drift fired.

    That is a malformed input, not a wrong verdict. Given ⟨confirmed, 31, test, files,
    pass⟩ the grammar behaved correctly; it was handed a sentence that cannot stay fixed,
    because by the next step something else has been confirmed.

    So this changes nothing the instrument decides. Two reasons, and the second binds:

      THE EVIDENCE DOES NOT REACH THAT FAR   Narration predicts a FIRE (5.4x, z = 6.87).
                             It does not predict a fire being WRONG: among labelled fires
                             it runs 19.5% of the false against 14.3% of the useful, on
                             seven useful labels. Seven cannot separate anything, and
                             suppressing on it would be acting past the data.

      THE CORPUS IS THE ASSET   Feeding this into a verdict would make every reading taken
                             before it incomparable with every one after, silently — the
                             same reason self_echo was kept additive in 0.41.0.

    is_groundable is left alone for the reason it rejects only two things: a
    narration-shaped goal is still a task someone is doing, and refusing it would leave the
    session ungrounded, which is worse than grounding on an awkward string.
    """
    return bool(text) and bool(_REPORT_RE.match(text))


def _looks_failed(text: str) -> bool:
    """True when the TEXT of a tool result carries an unambiguous failure signature.

    Not used by normalise() since 2026-11-14 (round 2 B4); kept for research suites and the
    replay. It ran after the structural checks (exit_code, isError) had declined to call a
    result a failure, and in round 2 every call it failed had exited 0. normalise() now
    reads only red verdicts; see red_verdict.
    """
    if not text:
        return False
    if is_self_refusal(text):
        return False
    if _NOT_FAIL_RE.search(text):
        return False
    return bool(_FAIL_RE.search(text))


def verdict_of(text):
    """Read {drifting, reason, phi} out of a check response, whatever shape it arrives in.

    Parses rather than pattern-matches. The shapes that occur in practice are a bare dict,
    a raw JSON string, and — the one that broke this for the entire corpus — the MCP
    envelope {"content":[{"type":"text","text":"{...}"}]}, where the payload is JSON
    carried inside a JSON string and every quote is escaped.

    Returns drifting=False for anything unreadable. That direction is deliberate: an
    unparsed response must not manufacture a fire, because a false fire in the corpus is
    indistinguishable from a real one and would inflate precision. A missed fire at least
    shows up as silence, which is what this bug looked like.
    """
    def walk(x, depth=0):
        if depth > 6 or isinstance(x, bool):
            return None
        if isinstance(x, dict):
            # A WITHHELD VERDICT IS STILL A VERDICT, and this recogniser could not see one.
            #
            # `drifting` was the only marker until 2026-08-19. A blind-arm response does not
            # carry it — it is {blind, arm, run, step, note} — so walk() fell through, found
            # nothing, and returned {}. Every downstream field then took its default: reason
            # became 'no-reading', and phi, run, run_step, arm and goal_score were dropped.
            #
            # The cost was the probe itself. Since 2026-08-08 every blind session row has been
            # six empty fields, so the arm that exists to answer the causal question could not
            # be joined to the drift log it writes — 0 of 106 rows carried `run`. The
            # experiment was recording nothing about its own units.
            #
            # lb_coverage.py's parser already handled this and says so in its own comments.
            # Two parsers, one of them fixed — the same "written into one branch of two" the
            # rest of this file keeps warning about.
            if isinstance(x.get('drifting'), bool):
                return x
            if x.get('run') and ('arm' in x or 'blind' in x):
                return x
            for val in x.values():
                got = walk(val, depth + 1)
                if got is not None:
                    return got
        elif isinstance(x, (list, tuple)):
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

    found = walk(text) or {}
    # `run` and `step` are the drift log's key. They are returned as `run`/`run_step` so
    # the caller never confuses the server's reading number with the session's tool-call
    # number — the two counters that were silently unrelated for the whole corpus. None
    # means the server predates 2026-08-01 and cannot be joined, which is a different
    # statement from "no run" and has to stay tellable apart downstream.
    # THE SAME THREE FIELDS lb_coverage._verdict() was taught to extract on 2026-08-04 —
    # and this is a SECOND COPY of that function, which nobody edited, so the fields were
    # pulled out next door and thrown away here. lb_coverage extracts; this one feeds the
    # writer that actually owns the file. A day of checks recorded none of them.
    #
    # Two implementations of one extractor is the pattern this codebase keeps paying for:
    # drift.ts already carries "This is the FOURTH copy of the rule... Change all four or
    # none". These two should be one function; until they are, they change together.
    j = found.get('judgment') or {}
    return {'drifting': bool(found.get('drifting')),
            'reason': str(found.get('reason') or 'no-reading'),
            'phi': found.get('phi'),
            'anchored': found.get('anchored'),
            'goal_score': found.get('goal_score'),
            'judgment': (j.get('verdict') if isinstance(j, dict) else None),
            'run': found.get('run'),
            'run_step': found.get('step')}


def from_hook(ev, directory=None):
    """A hook payload from any host, on stdin.

    There used to be two of these — from_claude_code and from_grok — and they were
    byte-identical apart from the docstring. The spelling difference they appeared to
    handle (snake_case vs camelCase, tool_name vs toolName) is absorbed by
    session_id_of and normalise, which read both. So the pair was never two adapters;
    it was one function published under two brand names, and a third host would have
    meant a third copy of the same four lines.

    Both old names remain as aliases below. Nothing that imports them breaks.
    """
    s = Session(session_id_of(ev), directory=directory)
    if not s.d.get('agent') or s.d.get('agent') == 'unknown':
        s.d['agent'] = agent_of(ev)
    return s.feed(ev)


#: Kept so existing hooks and integrations import what they always did. They are the
#: same function; the names are history, not behaviour.
from_claude_code = from_hook
from_grok = from_hook


def from_openai_agents(run_id, name, arguments, error=None, directory=None):
    """OpenAI Agents SDK style: a tool name, its arguments, and an optional error."""
    return Session(run_id, directory=directory).feed(
        {'name': name, 'arguments': arguments, 'output': {'error': error} if error else {}})
