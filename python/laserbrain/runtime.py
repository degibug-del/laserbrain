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
    if not isinstance(ev, dict):
        return (None, '', {}, True, '')

    tool = str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '')
    args = (ev.get('tool_input') if ev.get('tool_input') is not None
            else ev.get('toolInput') if ev.get('toolInput') is not None
            else ev.get('arguments') if ev.get('arguments') is not None
            else ev.get('parameters') if ev.get('parameters') is not None
            else ev.get('input') if ev.get('input') is not None
            else {})
    tool, args = unwrap_tool_args(tool, args)

    # Prompt capture: only when this is not also a tool event.
    prompt = ev.get('prompt')
    if prompt is None:
        prompt = ev.get('userPrompt') if ev.get('userPrompt') is not None else ev.get('promptText')
    if prompt is not None and not tool:
        return ('prompt', '', {}, True, clean_prompt(prompt))

    if not tool:
        return (None, '', {}, True, '')

    resp = (ev.get('tool_response') if ev.get('tool_response') is not None
            else ev.get('toolResult') if ev.get('toolResult') is not None
            else ev.get('output') if ev.get('output') is not None
            else {})
    ok = True
    event_name = str(ev.get('hookEventName') or ev.get('hook_event_name') or '')
    if 'failure' in event_name.lower():
        ok = False
    if isinstance(resp, dict):
        code = resp.get('exit_code')
        if code is None:
            code = resp.get('exitCode')
        if isinstance(code, int):
            ok = code == 0
        elif resp.get('error') or resp.get('is_error') or resp.get('isError'):
            ok = False
    elif isinstance(resp, str) and resp.strip().lower().startswith('error'):
        ok = False

    # A failure whose evidence is INSIDE the text used to sail through as success.
    #
    # Everything above only fires when a failure announces itself structurally: an
    # exit_code, an isError flag, or a string that literally begins with "error". Most
    # real failures do neither. "timeout: command not found" is a bare stderr line. A
    # denied tool call arrives as ordinary MCP content. A compiler error sits in the
    # middle of 200 lines of output. All three were recorded as ok.
    #
    # The cost was recall itself. Recall is hits over CATCHES, and a catch is exactly an
    # independently-detected failure. With this recogniser blind to unlabelled failures,
    # 21 sessions carried ZERO catches on 2026-07-26 — a day containing two failed
    # archives, a rejected upload and a missing binary — so the denominator was always
    # zero and recall was unobtainable no matter how far coverage rose. Raising the
    # coverage floor that morning was necessary and nowhere near sufficient.
    #
    # Deliberately narrow. These are unambiguous failure signatures, anchored to line
    # starts where possible, because a false catch is worse than a missed one: catches
    # are the GROUND TRUTH the harness is scored against, so inventing them would let the
    # instrument grade itself against its own noise.
    if ok:
        probe = (resp if isinstance(resp, str) else json.dumps(resp, default=str))[:4000]
        if _looks_failed(probe):
            ok = False

    low_tool = tool.lower()
    if low_tool.endswith('reset_task') or low_tool.endswith('__reset_task'):
        return ('reset', tool, args, True, '')
    kind = 'check' if low_tool.endswith('check_state') else 'tool'
    text = json.dumps(resp, default=str)[:600] if resp else ''
    return (kind, tool, args, ok, text)


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

    def tool(self, name, args=None, ok=True, self_refusal=False):
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
        if not self_refusal:
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
            self.d['catches'].append({'step': self.d['steps'], 'by': 'build',
                                      'what': f'failed call: {name}', 'clean': True,
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
                f'now with your CURRENT goal, progress and distance 0-10.')
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
                f'now with your CURRENT goal, progress and distance 0-10.')

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
        kind, tool, args, ok, text = normalise(ev)
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
            self.tool(tool, args, ok, self_refusal=is_self_refusal(text))
            return self.nudge()
        return None


# ── adapter shapes — thin wrappers over the same path ───────────────────────
# Failure signatures that a tool reports in its TEXT rather than in a status field.
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
# remain catches.
_SELF_REFUSAL_RE = re.compile(r'laserbrain gate:.*?\bcoverage\b', re.IGNORECASE | re.DOTALL)


def is_self_refusal(text: str) -> bool:
    """True when this result is the coverage gate refusing, rather than work failing.

    Not ground truth in either direction: the call did not run, so nothing was proved
    about the world — only that the instrument stopped its own agent.
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

    Used only after the structural checks (exit_code, isError) have declined to call it a
    failure — so this catches the large class of tools that report failure in prose.
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
