#!/usr/bin/env python3
"""lb_gate.py — a PreToolUse gate that makes coverage structural instead of optional.

WHY THIS EXISTS. Nudging does not work, and there is now two days of evidence. The
PostToolUse hook counts steps, captures the ground goal, logs failed commands and prints
a reminder every eight steps. Coverage on 2026-07-24 was 10%. On 2026-07-25, with the
nudge firing and a whole protocol written about it, coverage was 6% — it went DOWN.

An advisory that is ignored is not a control. dogfood.py withholds any detection result
below 50%, calibrate.py refuses to derive a profile, and precision has never once been
computed. All of it waits on a number that discipline has failed to move twice.

So this blocks. After BLOCK_AFTER steps without a spelled check, no tool runs until
check_state is called. Coverage stops being a virtue and becomes a precondition.

TWO THINGS IT MUST NEVER DO:

  deadlock — the laserbrain tools are ALWAYS allowed. Blocking check_state while
             demanding check_state is a trap, and it would be the only bug here that
             could not be worked around.

  break    — any exception, any malformed input, any missing session: allow. A gate that
             fails closed takes the session down with it. Every path exits 0 and the
             default is to permit.

Host notes (2026-07-25, from wiring a second host):
  - WRITE_TOOLS must include search_replace: it is a primary edit tool on some hosts.
  - LASERBRAIN_AGENT is often missing on the hook process (MCP sets it, hooks do not);
    fall back to the session file's agent so a host does not self-block on its own claims.
  - link entries use agent= or from= — accept both.
  - search_tool is always allowed so a blocked agent can re-discover laserbrain schemas
    without burning the gate (discovery is read-only).
  - Deny text is agent-aware: hosts differ in how a tool is invoked (see CHECK_HOWTO).
"""
import sys, json, os, pathlib, fnmatch, hashlib

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


def _link_log_default():
    """~/.config/laserbrain/link.jsonl, falling back to the pre-rename tandem.jsonl.

    Renamed 2026-07-27. FOUR files resolve this path independently — link.py, waves.py,
    lb_gate.py and mcp-server.mjs — and they must land on the same file. If they do not,
    two agents "sharing" a channel each write to a different log and each reads an empty
    one, which presents exactly as the other agent having said nothing. The legacy path is
    honoured when it exists and the new one does not, so an un-migrated machine keeps its
    history instead of silently starting over.
    """
    base = _paths.config_dir()
    new, old = base / 'link.jsonl', base / 'tandem.jsonl'
    return old if (old.exists() and not new.exists()) else new

LINK_LOG = pathlib.Path(os.environ.get('LASERBRAIN_LINK_LOG')
                        or os.environ.get('LASERBRAIN_TANDEM_LOG')
                        or _link_log_default())
# Tools that change files. Reads are never gated on claims — orienting in someone else's
# area is fine; editing it is not.
# Across hosts: Edit / Write / NotebookEdit / StrReplace / search_replace / write.
# search_replace was missing until 2026-07-25, which left the claim gate blind on any
# host that uses it as its primary edit tool.
WRITE_TOOLS = (
    'edit', 'write', 'notebookedit', 'str_replace',
    'search_replace',  # a primary edit tool on some hosts
)

# Steps without a spelled check before the gate closes. The number is not a taste
# judgement — it fixes the floor, because an agent doing the minimum checks only when
# blocked. Simulated over 400 steps:
#
#     12 -> 8%     6 -> 14%     4 -> 20%     3 -> 25%     2 -> 33%     1 -> 50%
#
# Set to 4 by Diego, 2026-07-25: a 20% floor. That is more than three times the 6% that
# discipline produced, and it does NOT clear the 50% dogfood.py needs — only 1 does, and
# a check between every single tool call is a tax nobody would keep paying. 20% is the
# honest trade: the corpus stays attributable and dense enough to be worth reading, and
# the gate stays closed until someone decides the detection result is worth 1.
BLOCK_AFTER = 4

# ── the probe, which exists because the number above cannot otherwise be checked ──
#
# Everything in the paragraph above is a SIMULATION. 4 -> 20% is arithmetic about how often
# an agent doing the minimum would check, not a measurement of whether 4 is better than 12
# at anything. Measured on 2026-08-02, drift against steps-since-own-check reads:
#
#     2-3 steps    18/224    8.0%
#     4-7 steps   154/1397  11.0%     z = 1.35, not significant
#     8-15 steps    0/5      five readings
#
# and the reason the third row is empty is this gate. 85% of every gap ever recorded sits
# in 4-7 because the gate puts it there, and gaps of 8+ are 0.31% of the sample. The
# interval is being evaluated against data the interval produced, which is the same
# circularity that made the gate's own blocks count as evidence against the instrument.
#
# So a stable minority of sessions run relaxed, and both arms are tagged. This costs
# coverage on those sessions ON PURPOSE — that is the measurement, not a side effect.
#
# BOTH THRESHOLDS MOVE TOGETHER, and they have to. Relaxing only BLOCK_AFTER would change
# nothing: the coverage term fires as soon as cov drops under the floor, which it does
# immediately at a 12-step cadence, so the gate would close at 20% coverage anyway and the
# long gaps would never happen. The relaxed floor is the simulated figure for a 12-step
# cadence from the table above.
#
# Assignment is a hash of the session id, not a coin flip: it must not change mid-run, must
# survive the hook being re-entered on every tool call, and must be reproducible from the
# session file alone when someone asks months later which arm a run was in.
# How far past the threshold before the gate stops being proportional and refuses
# everything. A MULTIPLE rather than a constant, so the relaxed arm escalates in the
# same ratio and the probe keeps comparing like with like.
HARD_MULTIPLE = 2

# What may still run in the proportional band. An ALLOWLIST, and that direction is the
# whole of its safety: a blocklist asks "is this one of the dangerous tools I thought of",
# and the first version of this asked exactly that using WRITE_TOOLS — which does not
# contain `bash`. Bash is the most side-effecting tool on any host; it would have sailed
# through the courtesy band while `edit` was refused, and nothing would have said so.
#
# Inverted, an unclassified tool is refused. A new tool nobody has thought about is treated
# as capable of anything, which is the only safe default for a name you have never seen.
#
# Substring match, because hosts prefix and namespace freely (mcp__x__read_file, Grep,
# str_replace_editor). Kept deliberately short: these are the calls an agent uses to work
# out WHAT to spell, and nothing here can change a file, run a command or send anything.
READ_ONLY = (
    'read', 'grep', 'glob', 'ls', 'list_', 'get_', 'search', 'find',
    'webfetch', 'websearch', 'fetch',
)
RELAXED_BLOCK_AFTER = 12
RELAXED_MIN_COVERAGE = 0.08
# 15 -> 50, 2026-08-05. The probe samples once per SESSION, and at roughly a session a
# day a 15% split had recorded ONE arm in two days — the 8-15 step band it exists to
# populate still holds 0.3% of all gaps. At that rate the BLOCK_AFTER question needs
# months, which is not an experiment, it is a way of never deciding.
#
# The pre-2026-08-05 rows do not carry over regardless: the gate they measured refused
# every call at the threshold, and this one refuses only the acting ones until twice it.
# A restart costs nothing because there was nothing to lose.
DEFAULT_PROBE_SHARE = 50                      # percent of sessions, 0 disables


def probe_share():
    """Percent of sessions assigned to the relaxed arm. 0 turns the probe off."""
    try:
        v = int(os.environ.get('LASERBRAIN_PROBE_SHARE', DEFAULT_PROBE_SHARE))
    except (TypeError, ValueError):
        return DEFAULT_PROBE_SHARE
    return min(100, max(0, v))


def record_arm(session_id, arm, state_dir):
    """Append this session's arm to probe-arms.jsonl, once. Never rewrites anything.

    WHY NOT IN THE SESSION FILE, which is where it lived for a day and lost every write

    Two long-lived processes own ~/.claude/laserbrain/<sid>.json: this hook, and the SDK's
    Session in laserbrain/runtime.py. Both do read-modify-write of the WHOLE dict, and the
    SDK holds its copy in memory across the hook's writes — so whichever saves last drops
    the other's keys. `probe_arm` was stamped by the hook and silently clobbered every
    time. Checked 2026-08-03: not one session file carried it, including the live one, so
    the arms were being applied and never recorded and the probe was collecting nothing.

    Append-only with one writer has neither problem. It is the same argument laserfield
    makes for reading /history straight off the log: "the log is append-only and the field
    loop is the only writer, so a reader can never see a torn row."

    Recorded once per session — the first gated call — because the arm cannot change.
    """
    try:
        log = pathlib.Path(state_dir) / 'probe-arms.jsonl'
        if log.exists():
            with open(log) as fh:
                for line in fh:
                    if f'"{session_id}"' in line:
                        return
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, 'a') as fh:
            fh.write(json.dumps({'session': str(session_id), 'arm': arm,
                                 'share': probe_share(),
                                 'block_after': RELAXED_BLOCK_AFTER if arm == 'relaxed' else BLOCK_AFTER,
                                 'at': __import__('datetime').datetime.now().isoformat(timespec='seconds')}) + '\n')
    except Exception:
        pass          # never let bookkeeping break the gate


def publish_blind_arm(session_id, state_dir, segment=None):
    """Write the CURRENT session's blind arm where the MCP server can read it.

    THE PROBLEM THIS SOLVES. The blind arm has to be applied where the check_state response
    is built — lasermind/mcp-server.mjs — and that process has no session id. It holds only
    `runId`, which resets on every reset_task; a session that resets twenty times would flip
    between blind and sighted twenty times, destroying exactly the comparison the arm exists
    to make. The MCP config's env block is static strings, so it cannot carry one either.

    The hook is the only process that knows the session id, and it already imports this
    module. So it writes the answer and the server reads it.

    ONE WRITER, ONE READER — which is a different shape from the bug record_arm exists to
    avoid. That failure was two processes doing read-modify-write on the same dict, each
    dropping the other's keys. Here nothing but this function ever writes, and the server
    only reads, so there is nothing to clobber.

    IT WRITES THE ARM, NOT THE SESSION ID, deliberately. Handing the server an id would make
    it compute the assignment itself, in JavaScript, from a second copy of this hash — the
    divergence problem fixed three separate times in this codebase already. The assignment
    lives here, once, and the server is told the answer.

    Atomic via rename: a torn read would be a session in neither arm.
    """
    try:
        # The UNIT is a segment, not a session — see blind_arm. The segment index comes from
        # how many runs have already been archived, so it advances exactly when reset_task
        # fires and never mid-task.
        unit = f'{session_id}#{segment}' if segment is not None else str(session_id)
        arm = blind_arm(unit)
        d = pathlib.Path(state_dir)
        d.mkdir(parents=True, exist_ok=True)
        cur = d / 'current-arm.json'
        # Skip the write when nothing changed — this runs on every tool call.
        if cur.exists():
            try:
                prev = json.loads(cur.read_text())
                if prev.get('unit') == unit and prev.get('blind') == arm:
                    return arm
            except Exception:
                pass
        import datetime as _dt
        rec = {'session': session_id, 'unit': unit, 'segment': segment, 'blind': arm,
               'at': _dt.datetime.now().isoformat(timespec='seconds')}
        tmp = d / f'.current-arm.{os.getpid()}.tmp'
        tmp.write_text(json.dumps(rec))
        tmp.replace(cur)

        # ── AND KEEP IT, BECAUSE current-arm.json IS CURRENT ──────────────────────────────
        #
        # THE EXPERIMENT COULD NOT PRODUCE ITS OWN RESULT. current-arm.json is overwritten on
        # every new unit, session records carry no arm, and their check entries hold only
        # step/drifting/goal/progress/distance. So from 2026-08-08 the blind probe ran,
        # visibly — every session could see `blind: true` — while nothing durable recorded
        # which unit got which arm. Two arms, no way to tell them apart afterwards. Found on
        # 2026-08-10 while trying to pre-register a stopping rule, which is the good news:
        # the design fault surfaced before anyone read a number off it.
        #
        # The assignment is deterministic in `unit`, so history is in principle recomputable
        # — but only for units someone can still enumerate, and nothing enumerates them. An
        # append here is the cheap durable record: one line per new unit, never rewritten.
        #
        # ITS OWN try/except, AND THAT IS THE POINT. The enclosing handler returns 'sighted'
        # on any exception. A bookkeeping failure reaching it would silently move sessions
        # into one arm — bookkeeping deciding the experiment it exists to record. It cannot
        # reach it from in here.
        try:
            with (d / 'blind-arms.jsonl').open('a') as fh:
                fh.write(json.dumps(rec) + '\n')
        except Exception as _e:
            if os.environ.get('LASERBRAIN_DEBUG'):
                sys.stderr.write(f'blind-arms append failed: {type(_e).__name__}: {_e}\n')

        return arm
    except Exception as e:
        # NEVER let bookkeeping change what the agent sees — but do not swallow the reason.
        #
        # The first version of this caught bare Exception and returned 'sighted'. datetime
        # was not imported in this module, so every call failed, no file was written, and it
        # reported the default as though it had decided. That is the same silent-failure
        # shape as `2>/dev/null` hiding the SIGPIPE in upload-build.sh and `set -e` killing a
        # read with no message — written by me an hour after documenting both.
        #
        # LASERBRAIN_DEBUG surfaces it. The fallback still holds, because an experiment that
        # breaks a working harness is worse than no experiment.
        if os.environ.get('LASERBRAIN_DEBUG'):
            sys.stderr.write(f'publish_blind_arm failed: {type(e).__name__}: {e}\n')
        # AND LEAVE A MARK, BECAUSE THIS FALLBACK IS NOT NEUTRAL.
        #
        # Returning 'sighted' keeps a working harness working, which is right. But it also
        # moves a unit into one arm, so a run of failures quietly turns a two-armed
        # experiment into a one-armed one — and until now that was visible only to whoever
        # happened to have LASERBRAIN_DEBUG set, which is nobody.
        #
        # One marked line, so the analysis can exclude these or report how many there were.
        # An experiment whose failure mode is "silently becomes single-arm" cannot be
        # trusted when it agrees with you either.
        try:
            import datetime as _dt2
            d2 = pathlib.Path(state_dir)
            d2.mkdir(parents=True, exist_ok=True)
            with (d2 / 'blind-arms.jsonl').open('a') as fh:
                fh.write(json.dumps({'session': session_id, 'unit': None, 'segment': segment,
                                     'blind': 'sighted', 'fallback': True,
                                     'error': f'{type(e).__name__}: {e}'[:200],
                                     'at': _dt2.datetime.now().isoformat(timespec='seconds')}) + '\n')
        except Exception:
            pass
        return 'sighted'


def probe_arm(session_id):
    """'relaxed' or 'control', stable for the life of a session id.

    Deterministic so that re-running the analysis, or reading a session file a month from
    now, yields the same answer without anything having been stored — and so the hook,
    which runs afresh on every single tool call, cannot flip an agent between arms
    mid-task and destroy the comparison it exists to make.
    """
    share = probe_share()
    if not share or not session_id:
        return 'control'
    h = hashlib.sha256(str(session_id).encode('utf-8')).hexdigest()[:8]
    return 'relaxed' if int(h, 16) % 100 < share else 'control'

def blind_arm(unit_id):
    """'sighted' or 'blind' — does SEEING the verdict change the work? Off unless enabled.

    RE-CUT 2026-08-08 TO KEY ON A SEGMENT, NOT A SESSION. The first version randomised per
    session and was unrunnable: Diego works in ONE session, and the corpus proves it — a
    single session holds 2,436 of 2,483 checks, 98% of everything. Randomising per session
    gives n=1, and the pre-registration asked for 20 per arm. It could never have completed.

    A SEGMENT is the right unit and the codebase already argued for it. The GAP probe below
    says: "randomising per gap is not merely allowed, it is the correct design — and it
    yields one datum per gap instead of one per session." The same holds here. `reset_task`
    means a new task with a new frozen ground, so a segment is exactly one task, and one arm
    per task is the treatment this measures — not a flip mid-task, which is what the session
    version was written to avoid.

      unit       n available in the corpus
      session    12   (one holds 98%)
      segment    254

    So `unit_id` is a RUN id, not a session id — the thing the MCP server already holds and
    that resets on every reset_task. I rejected runId as a session key for exactly the
    property that makes it right here.

    PRE-REGISTERED IN BLIND-PROBE.md, alongside this file, on 2026-08-10 — sample size,
    outcome measure, stopping rule, and what result would mean the harness does not help,
    all written before any of it was read. If a number here and a number there disagree,
    that document is the record of what was decided while the answer was unknown.

    A SECOND, INDEPENDENT ARM. probe_arm above asks whether a tighter gate changes how you
    work. This asks something else: the checks happen either way, Phi is computed and
    recorded either way, and the only difference is whether the agent is TOLD.

    That distinction is the whole point. Every session in the corpus to date ran with the
    harness visible, so there is no arm in which the instrument was measuring without also
    intervening — and "does it help?" has therefore never been answerable, only asserted.
    Diego's own read on 2026-08-07 was "yes, noticeably better", which is exactly the kind
    of belief that needs a control rather than a testimonial.

    WHY NOT SIMPLY TURN THE HARNESS OFF for the control arm: then the control sessions
    record less Phi than the treatment sessions, and the two arms are no longer comparable —
    you would be contrasting a measured population against a partly unmeasured one, which
    manufactures a difference out of the measurement itself. Blinding keeps the data
    identical in both arms and removes only the feedback.

    DIFFERENT SALT, so this is orthogonal to probe_arm. Hashing the same session id twice
    the same way would put every session in matching arms and silently fuse two experiments
    into one; with the salt they cross, and the design is factorial and analysable as such.

    DEFAULT OFF. Returns 'sighted' unless LASERBRAIN_BLIND_PROBE is set, because switching
    it on changes what a live agent can see about itself. Enabling it is a decision someone
    makes on purpose, not a thing that starts happening because a file was updated.
    """
    import os
    if os.environ.get('LASERBRAIN_BLIND_PROBE', '').strip() not in ('1', 'true', 'yes'):
        return 'sighted'
    if not unit_id:
        return 'sighted'
    h = hashlib.sha256(('blind:' + str(unit_id)).encode('utf-8')).hexdigest()[:8]
    return 'blind' if int(h, 16) % 2 == 0 else 'sighted'


# ── the GAP probe: the same question, asked 28 times faster ─────────────────────
#
# probe_arm above is stable per SESSION, deliberately — a persistent treatment ("does
# working under a tight gate change how you work?") is destroyed by flipping mid-task.
#
# But that is not the question BLOCK_AFTER answers. BLOCK_AFTER is set by a MOMENTARY
# question: does a longer gap since the last check raise drift risk on the next reading?
# The outcome is measured on that gap alone, so randomising per gap is not merely allowed,
# it is the correct design — and it yields one datum per gap instead of one per session.
#
# The arithmetic is why this exists. At 2.5 sessions a day, the session probe had recorded
# ONE arm in three days. The same corpus holds ~28 gaps per session, so this collects in
# days what that collects in a quarter.
#
# AND THE CURRENT ANSWER IS "NO EVIDENCE", which is the actual finding. Measured
# 2026-08-05 on 1,878 pairs:
#
#     1 step        2/27     7.4%
#     2-3 steps    19/256    7.4%
#     4-7 steps   160/1590  10.1%     z = 1.325 against 2-3 — not significant
#     8-15 steps    0/5      unpowered
#     16+ steps     0/0      nothing
#
# Drift risk does not measurably rise with steps across the range where data exists, and
# the range is that narrow BECAUSE the gate closes at 4. The threshold costs 22.3% of an
# agent's calls and rests on z = 1.325. The censoring is self-inflicted, and this is the
# instrument that lifts it.
#
# BOUNDED ON PURPOSE. Draws come from a small set topping out at the relaxed arm's 12 —
# a value already judged acceptable and already running for half of all sessions. This
# widens the sample, it does not remove the floor.
GAP_DRAWS = (4, 6, 8, 12)


def gap_probe(session_id, gap_index):
    """The gap this particular lapse is allowed, drawn deterministically.

    Deterministic on (session, gap_index) for the same reason probe_arm is deterministic:
    the hook re-runs on every tool call, so a random draw would change the threshold under
    an agent mid-gap and record a number that was never actually applied.
    """
    if not probe_share() or not session_id:
        return None
    h = hashlib.sha256(f'{session_id}:{gap_index}'.encode('utf-8')).hexdigest()[:8]
    return GAP_DRAWS[int(h, 16) % len(GAP_DRAWS)]


# ── the coverage floor, in ONE place ────────────────────────────────────────────
# The paragraph above records a real decision: 50% coverage means a check between every
# tool call, and that tax gets abandoned, so daily use gates at a cadence that lands
# around 20-25%. Tonight's sessions ran 21-29%, so the trade is holding.
#
# What was NOT decided is that the two thresholds live in different files with nothing
# joining them. dogfood.py had MIN_COVERAGE = 0.5 hard-coded and this hook had a step
# count, so no one editing either could see the other, and a run could satisfy the gate
# while being unscoreable — which is every run we have.
#
# So the floor is named once, here, and read from the environment. A benchmark sets it to
# the scorer's floor and pays the tax deliberately for the length of the study:
#
#     LASERBRAIN_MIN_COVERAGE=0.5 <run the benchmark>
#
# and dogfood.py reads the same variable, so the number the gate enforces and the number
# the scorer demands cannot disagree by accident again. They can still be set low on
# purpose; that is a choice someone makes, not a contradiction nobody sees.
DEFAULT_MIN_COVERAGE = 0.20


def min_coverage():
    """The coverage floor this run is held to. Shared with dogfood.py."""
    try:
        v = float(os.environ.get('LASERBRAIN_MIN_COVERAGE', DEFAULT_MIN_COVERAGE))
    except (TypeError, ValueError):
        return DEFAULT_MIN_COVERAGE
    return min(1.0, max(0.0, v))
# Overridable so the instrument can be run UNDER TEST without writing into the corpus it
# is measured against. laserbrain-trial runs the real hooks in both arms; without this every
# trial run would append synthetic sessions to the shared record that corpus-map.py
# summarises and the paper renders its figures from. Default is unchanged, so nothing that
# does not set the variable behaves differently.
STATE_DIR = pathlib.Path(os.environ.get('LASERBRAIN_STATE_DIR')
                         or _paths.sessions_dir())
# Shared corpus lives under ~/.claude/laserbrain for historical reasons. The path names
# one host and holds every agent's rows; moving it would orphan the existing corpus, so
# it stays and this comment is the correction.
# Alias doc: ~/.config/laserbrain/sessions → same path (see sync / rules).

# Never gated. check_state is how you get out; reset_task starts a new ground; the read
# tools are how an agent orients before spelling its state.
# search_tool: MCP schema discovery — read-only; blocking it deadlocks an agent that needs
# the schema before it can call check_state through use_tool.
ALWAYS_ALLOW = (
    'check_state', 'reset_task', 'get_history', 'read_field', 'field_vocabulary',
    'speak_to_field', 'link_read', 'link_whoami', 'link_write', 'drift_grammar',
    'search_tool',  # MCP schema discovery; not a side-effect tool
)


def entry_agent(r):
    """Who authored a link row? Hosts differ: some write from=, some agent=, some payload.from."""
    if not isinstance(r, dict):
        return 'unknown'
    who = r.get('from') or r.get('agent') or (r.get('payload') or {}).get('from')
    return str(who or 'unknown').lower()


def claim_paths(r):
    """Paths locked by a claim row. payload.paths preferred; path-like payload.claims ok."""
    p = r.get('payload') or {}
    paths = list(p.get('paths') or [])
    if not paths:
        for c in p.get('claims') or []:
            if not isinstance(c, str):
                continue
            s = c.strip()
            # path-like only (skip prose claim descriptions)
            if '/' in s or s.endswith(('.py', '.ts', '.tsx', '.js', '.mjs', '.md', '.json')):
                paths.append(s)
    return [x for x in paths if isinstance(x, str) and x.strip()]


def _releases_claims(r):
    """Does this row release the author's standing claims?"""
    k = r.get('kind')
    if k == 'wave_close':
        return True
    if k == 'done':
        p = r.get('payload') or {}
        if p.get('release_claims') or p.get('release') or p.get('event') == 'wave_close':
            return True
        if 'paths' in p and p.get('paths') == []:
            return True
    if k == 'claim':
        p = r.get('payload') or {}
        if p.get('release_claims') or p.get('release'):
            return True
    return False


def claimed_by_others(me):
    """{path: agent} for paths claimed by someone who is not me.

    Two modes:
      1) Open wave — claims with matching payload.wave (or no wave, attached to open
         wave if logged after that wave_open). Closed agents drop out.
      2) Free-form / standing — when no open wave, claims with paths stay active until
         the author wave_close / done(release) / claim(release).

    waves.py refuses overlapping CLAIM at write time; this refuses the EDIT.
    """
    me = (me or 'unknown').lower()
    try:
        rows = [json.loads(l) for l in LINK_LOG.read_text().splitlines() if l.strip()]
    except Exception:
        return {}

    opens = [r for r in rows if r.get('kind') == 'wave_open']
    out = {}

    if opens:
        wid = opens[-1].get('payload', {}).get('wave')
        open_idx = max(i for i, r in enumerate(rows) if r.get('kind') == 'wave_open'
                       and (r.get('payload') or {}).get('wave') == wid)
        wave_claims = [r for r in rows if r.get('kind') == 'claim'
                       and (r.get('payload') or {}).get('wave') == wid]
        claimed_agents = {entry_agent(r) for r in wave_claims} - {'unknown'}
        # on_behalf_of first — a forced close is made BY one agent FOR another, so crediting
        # it to the author credits the wrong party. Identical defect to the one fixed in
        # waves.current_wave() on 2026-07-25, and here it deadlocked the protocol outright:
        # one agent retired, `force-close --for <agent>` was recorded and printed success,
        # and the gate still counted that agent outstanding. So the wave never closed, the free-form
        # release path below was never reached, and the gate went on holding files for an
        # agent that had gone — including refusing every edit to lb_gate.py itself.
        #
        # A guard with no timeout and no correct release is not strict, it is stuck.
        closed = {(r.get('payload') or {}).get('on_behalf_of') or entry_agent(r) for r in rows
                  if r.get('kind') == 'wave_close'
                  and r.get('payload', {}).get('wave') == wid}
        # Match waves.current_wave: open if outstanding claimants OR no claims yet
        wave_still_open = bool(claimed_agents - closed) or not claimed_agents
        if wave_still_open:
            for i, r in enumerate(rows):
                if r.get('kind') != 'claim':
                    continue
                cw = (r.get('payload') or {}).get('wave')
                if cw is not None and cw != wid:
                    continue
                if cw is None and i < open_idx:
                    continue
                who = entry_agent(r)
                if who == me or who in closed or who == 'unknown':
                    continue
                for path in claim_paths(r):
                    out[path] = who
            return out
        # last wave fully closed → fall through to free-form standing claims

    # free-form standing claims (no open wave, or last wave fully closed)
    active = {}
    for r in rows:
        who = entry_agent(r)
        if who == 'unknown':
            continue
        if _releases_claims(r):
            active.pop(who, None)
            continue
        if r.get('kind') != 'claim':
            continue
        paths = claim_paths(r)
        if not paths:
            continue
        active[who] = {p: True for p in paths}

    for who, paths in active.items():
        if who == me:
            continue
        for path in paths:
            out[path] = who
    return out


def touches(target, claim):
    """Does an edit at `target` fall inside `claim`? Same rule waves.overlaps uses."""
    t, c = str(target).rstrip('/'), str(claim).rstrip('/')
    if not t or not c:
        return False
    if t == c or fnmatch.fnmatch(t, c) or fnmatch.fnmatch(c, t):
        return True
    return (t + '/').startswith(c + '/') or (c + '/').startswith(t + '/')


def edit_target(ev, tool):
    if not any(w in tool for w in WRITE_TOOLS):
        return None
    ti = ev.get('tool_input') or ev.get('toolInput') or {}
    if not isinstance(ti, dict):
        return None
    return ti.get('file_path') or ti.get('path') or ti.get('notebook_path') or ti.get('filePath')


def steps_since_check(sess):
    checks = sess.get('checks') or []
    last = checks[-1].get('step', 0) if checks else 0
    return int(sess.get('steps', 0) or 0) - last


def record_refusal(sid, stage, tool, since, cov, floor, block_after, arm):
    """Append one line for every time the gate warns or refuses. Never raises.

    THE GATE FIRED AND LEFT NOTHING. It logged its arms, and — since this morning — its
    errors, and recorded not one word about the thing it exists to do. Nobody could say how
    often it closes, at which stage, or on what.

    That gap is load-bearing in three places:

      the published cost   /laserbrain says running laserbrain is 22.2% of an agent's
                           calls. That counts the checks an agent MADE. It cannot count
                           the calls this gate destroyed, each one a round trip plus a
                           lost draft — so the published figure is a floor, and the
                           distance above it is exactly what this log measures.
      the middle band      2026-08-05 introduced a proportional stage on the argument that
                           refusing reads was pure cost. Whether that helps is unmeasured,
                           and the agent that wrote it works mostly through Bash, which
                           the allowlist treats as acting — so it may help almost nobody.
      the gap probe        it sweeps thresholds and records which arm was drawn, but not
                           what the draw COST. Without that the sweep answers "does a
                           longer gap drift more" and never "was it worth it".

    NO COMMAND TEXT. The tool name, the stage and the numbers that produced the decision
    are enough for every question above, and a log of what an agent was about to run is a
    privacy surface with no analytic payoff.

    Append-only, single writer, like probe-arms.jsonl and for the identical reason: the session
    file is contested by laserbrain.runtime's Session, which holds its dict in memory and
    saves the whole thing back, so anything written there loses the race.
    """
    try:
        log = STATE_DIR / 'refusals.jsonl'
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, 'a') as fh:
            fh.write(json.dumps({
                'at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
                'session': sid, 'stage': stage, 'tool': tool, 'arm': arm,
                'since': since, 'coverage': round(cov, 3),
                'floor': floor, 'block_after': block_after,
            }) + '\n')
    except Exception:
        pass                       # a broken recorder must never cost a tool call


def warn(reason):
    """Let the call through, but say what nearly stopped it.

    The counterpart to deny(), and the middle of the proportional response. It writes to
    STDERR ONLY and exits 0: the hook contract treats a non-zero exit as a refusal, so a
    warning that used deny()'s JSON shape would silently become a block and the whole
    point of the middle band would be lost.

    Exists so escalation is never a surprise. An agent that reads its way past the
    threshold is told, on each read, that writes are already being refused and where the
    hard stop is — which is the information it needs to decide whether to check now or
    finish orienting first. Bang-bang gave it no such warning: the first signal WAS the
    refusal.
    """
    sys.stderr.write(reason + '\n')


def deny(reason):
    """Emit a block in both shapes and exit. Shared by the coverage and claim gates."""
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
    }}))
    sys.stderr.write(reason + '\n')
    sys.exit(2)


def _tool_of(ev):
    """Match coverage/runtime: peel use_tool envelopes so ALWAYS_ALLOW sees real names."""
    tool = str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '')
    args = (ev.get('tool_input') if ev.get('tool_input') is not None
            else ev.get('toolInput') if ev.get('toolInput') is not None
            else ev.get('arguments') if ev.get('arguments') is not None
            else {})
    try:
        from laserbrain.runtime import unwrap_tool_args
        tool, _ = unwrap_tool_args(tool, args)
        return tool
    except Exception:
        pass
    # Embedded peel (fail-open if package missing)
    if not isinstance(args, dict):
        try:
            args = json.loads(args) if isinstance(args, str) else {}
        except Exception:
            args = {}
    for _ in range(3):
        nested = str(args.get('tool_name') or args.get('toolName') or args.get('name') or '')
        nested_in = (args.get('tool_input') if args.get('tool_input') is not None
                     else args.get('toolInput') if args.get('toolInput') is not None
                     else None)
        if not nested_in and not nested:
            break
        if nested:
            tool = nested
        if isinstance(nested_in, dict):
            args = nested_in
        elif isinstance(nested_in, str) and nested_in.strip().startswith('{'):
            try:
                args = json.loads(nested_in)
            except Exception:
                break
        else:
            break
        if tool and tool not in ('use_tool', 'CallMcpTool', 'call_mcp_tool', 'mcp_tool'):
            if 'goal' in args or 'progress' in args or not (
                'tool_input' in args or 'toolInput' in args
            ):
                break
    return tool


def resolve_me(ev, sess=None):
    """Who am I for the claim gate?

    Priority: LASERBRAIN_AGENT env (MCP or hook wrapper) → session.agent stamp →
    event agent fields → unknown.
    Unknown is dangerous: own claims look foreign and can self-block.
    """
    env = (os.environ.get('LASERBRAIN_AGENT') or '').strip().lower()
    if env and env != 'unknown':
        return env
    if sess:
        a = str(sess.get('agent') or '').strip().lower()
        if a and a != 'unknown':
            return a
    for k in ('agent', 'agent_name', 'agentName'):
        v = ev.get(k)
        if v and str(v).strip().lower() != 'unknown':
            return str(v).strip().lower()
    return 'unknown'


#: Per-host invocation syntax lives in hosts.json, not here. Hosts genuinely differ in
#: how a tool is called — one takes use_tool(tool_name=...), another an mcp__ prefix —
#: and that difference is real. What was wrong was expressing it as a branch on a vendor
#: name inside the gate: it made the instrument carry a list of which agents exist, which
#: must be edited to support a host nobody has written yet. As config it is a one-line
#: addition, and an unlisted host gets the generic text rather than someone else's.
_HOSTS_PATH = pathlib.Path(__file__).with_name('hosts.json')
try:
    _HOSTS = json.loads(_HOSTS_PATH.read_text()).get('check_howto') or {}
except Exception:
    _HOSTS = {}

CHECK_HOWTO_DEFAULT = _HOSTS.get('default') or (
    'Call mcp__laserbrain__check_state now with your CURRENT goal, progress '
    '(advancing|stuck|circling) and distance 0-10, then reissue the blocked call. '
    'Do not batch check_state with other tools (gate race).'
)


def check_howto(me):
    """The escape-hatch text for this host, or the generic one."""
    return (_HOSTS.get('by_agent') or {}).get(
        str(me or '').strip().lower(), CHECK_HOWTO_DEFAULT)

def load_session(ev):
    # Any HOST_SESSION_ID, not a hardcoded pair. A host this file has never heard of
    # still identifies its own session.
    sid = ev.get('session_id') or ev.get('sessionId')
    if not sid:
        for k in sorted(os.environ, key=len, reverse=True):
            if k.endswith('_SESSION_ID') and os.environ.get(k):
                sid = os.environ[k]
                break
    if not sid:
        return None, None
    path = STATE_DIR / f'{sid}.json'
    try:
        return sid, json.loads(path.read_text())
    except Exception:
        return sid, None


def main():
    # The gate demands a check_state that only the MCP server can answer. If that server
    # is down — crashed, restarting, misconfigured — the demand is unsatisfiable and the
    # gate blocks every tool call for the rest of the session with no way out. An env var
    # cannot rescue it either: the hook reads its OWN environment, not the environment of
    # the command it is inspecting, so a bypass has to be something a blocked agent can
    # still create. A file is that.
    #
    # Added 2026-07-25 before deliberately restarting the MCP server, but the hazard is
    # general: a guard whose precondition can become impossible needs a door.
    #
    #   touch ~/.config/laserbrain/gate-off     disable
    #   rm    ~/.config/laserbrain/gate-off     re-enable
    if _paths.config('gate-off').exists():
        return
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        return                                   # unparseable → allow

    tool = _tool_of(ev)
    low = tool.lower()
    if any(a in low for a in ALWAYS_ALLOW):
        return                                   # never gate the way out

    sid, sess = load_session(ev)
    me = resolve_me(ev, sess)

    # ── claim gate: never edit into another agent's declared scope ──────────
    target = edit_target(ev, low)
    if target:
        for path, who in claimed_by_others(me).items():
            # match on the tail, since claims are repo-relative and tools pass absolute
            if touches(target, path) or path.rstrip('/') in str(target):
                deny(f'laserbrain claim gate: {path} is claimed by {who} in the open wave.\n'
                     f'THIS CALL DID NOT RUN — nothing was written.\n'
                     f'Editing another agent\'s scope is the collision waves exist to prevent '
                     f'(2026-07-25: a path was edited while another agent was building there).\n'
                     f'Either wait for {who} to close, or say so on the link and agree a '
                     f'handoff before touching it.\n'
                     f'(me={me}; set LASERBRAIN_AGENT on the hook env if this is wrong.)')

    if not sid or not sess:
        return                                   # cannot attribute / no session → do not gate

    since = steps_since_check(sess)
    steps = int(sess.get('steps', 0) or 0)
    cov = (len(sess.get('checks') or []) / steps) if steps else 0.0

    # Which arm of the probe this session is in. Both thresholds move together or neither
    # does — see RELAXED_BLOCK_AFTER. An explicit LASERBRAIN_MIN_COVERAGE always wins, so
    # a benchmark that sets the floor deliberately is never quietly overridden by an
    # experiment it did not ask to join.
    arm = probe_arm(sid)
    record_arm(sid, arm, STATE_DIR)     # append-only; the session file loses this race
    block_after = BLOCK_AFTER
    floor = min_coverage()
    if arm == 'relaxed' and 'LASERBRAIN_MIN_COVERAGE' not in os.environ:
        floor = RELAXED_MIN_COVERAGE
        # THE SESSION ARM DECIDES WHETHER TO SWEEP; THE GAP PROBE DECIDES HOW FAR.
        #
        # Control keeps a fixed 4 so there is a clean baseline to compare against. The
        # relaxed half draws its allowance per gap from {4, 6, 8, 12}, which is what
        # populates the 8-15 band the fixed threshold has been censoring to n=5 — and n=5
        # is the whole reason the agent clock reads z=1.325 instead of an answer.
        #
        # Falls back to the flat relaxed value if the probe is off, so turning the probe
        # off leaves exactly the behaviour that was there before it existed.
        drawn = gap_probe(sid, len(sess.get('checks') or []))
        block_after = drawn if drawn is not None else RELAXED_BLOCK_AFTER

    # Two ways to be gated, and they answer different questions.
    #
    #   since >= BLOCK_AFTER   you have gone too long without checking RIGHT NOW.
    #   cov   <  floor         the run as a whole is below the floor it is held to,
    #                          which is what decides whether the corpus can be scored.
    #
    # Only the first existed before, so an agent could satisfy the gate at every moment
    # and still finish a run that dogfood.py refuses to score. Checking coverage too
    # makes compliance mean the thing it is supposed to mean. It also self-corrects in
    # the agent's favour: front-load checks and the coverage term stays quiet, so
    # discipline early buys slack later rather than being forgotten.
    late = since >= block_after
    thin = steps >= 8 and cov < floor          # ignore the first few steps, where one
    if not (late or thin):                     # check swings coverage wildly
        return

    # ── PROPORTIONAL RESPONSE ───────────────────────────────────────────────────────
    #
    # The old gate was bang-bang: nothing at all until the threshold, then refuse
    # EVERYTHING. That is the crudest controller there is, and the cost fell on exactly
    # the wrong calls — most refusals in practice land on a Read or a grep, work that
    # changes nothing and was only ever going to inform the next check.
    #
    # The actuator here is binary — a call runs or it does not — so proportionality
    # cannot live in the strength of one refusal. It lives in WHICH calls are refused as
    # the error grows:
    #
    #     error                 refused              rationale
    #     ----------------      -----------------    ------------------------------------
    #     below threshold       nothing              silent; the nudge already ran
    #     just past it          side-effecting only  look all you like; do not ACT on a
    #                                                position you have not spelled
    #     far past it           everything           the old behaviour, kept for the case
    #                                                it was actually built for
    #
    # The middle band is the whole point. An agent that has drifted can still read, grep
    # and orient — which is how it works out what to spell — but cannot write, edit or
    # execute against a goal it has not stated. The instrument's own claim is about the
    # relationship between a spelled goal and an ACTION; refusing a read was never that.
    #
    # HARD_MULTIPLE, not a second constant. The escalation point is a proportion of the
    # threshold, so the relaxed arm escalates later in the same ratio and the probe keeps
    # comparing like with like — one number to reason about instead of two that can
    # silently disagree.
    hard_after = block_after * HARD_MULTIPLE
    over = since - block_after
    # A coverage shortfall this deep is not a lapse, it is a run that never checks. Skip
    # the courtesy band for it: the middle stage exists to let an agent finish orienting,
    # and there is nothing to finish here.
    starved = cov < floor / 2 and steps >= 8
    hard = since >= hard_after or starved

    tool = (_tool_of(ev) or '').lower()
    # Allowlisted, not blocklisted — see READ_ONLY. `notebookedit` contains 'edit' and not
    # a read word, so it lands on the refused side without needing its own rule; that is
    # the allowlist working rather than a coincidence.
    reading = any(r in tool for r in READ_ONLY) and not any(w in tool for w in WRITE_TOOLS)

    if not hard and reading:
        # Proportional zone, reading call: allow it, and say why it was nearly refused so
        # the escalation is never a surprise.
        record_refusal(sid, 'warn', tool, since, cov, floor, block_after, arm)
        warn(f'laserbrain gate: {since} steps since your last check_state '
             f'(coverage {cov:.0%}, floor {floor:.0%}). Reads still pass. '
             f'Writes and commands are refused until you check, and at '
             f'{hard_after} steps everything is.')
        return

    why = (f'{since} steps since your last check_state' if late
           else f'coverage {cov:.0%} is below the {floor:.0%} floor this run is held to')
    scope = ('every call' if hard
             else 'calls that change something — reads are still passing')
    reason = (
        f'laserbrain gate: {why} '
        f'(coverage {cov:.0%} over {steps} steps, floor {floor:.0%}).\n'
        f'Refusing {scope}. Nudging alone did not work — coverage was 10% one day and '
        f'6% the next while a reminder printed every 8 steps.\n'
        f'THIS CALL DID NOT RUN. Nothing was written, executed or sent — you must '
        f'reissue it after checking. (A draft composed inside a blocked call is gone: '
        f'on 2026-07-25 a 100-line heredoc was denied here and the file simply did not '
        f'exist, which only surfaced when the next command failed.)\n'
        # THE BATCH CASE, WHICH THE MESSAGE USED TO LEAVE OUT. This fires per call, so a
        # block of parallel calls gets one refusal EACH while the earlier ones in the same
        # block already ran. On 2026-08-10 an agent sent 28 task updates, 7 applied and 21
        # were refused, and it then reissued in shrinking waves — repeating ids it had
        # already completed, because "this call did not run" says nothing about its
        # siblings. It cannot: the gate sees one call. So it says that instead of implying
        # otherwise.
        f'IF YOU SENT SEVERAL CALLS AT ONCE, some of them ran and this one did not. This '
        f'gate sees one call and cannot tell you which. Re-read the state before reissuing '
        f'— do not replay the whole block.\n'
        f'{check_howto(me)}'
    )
    record_refusal(sid, 'hard' if hard else 'acting', tool, since, cov, floor,
                   block_after, arm)
    deny(reason)


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        # FAIL OPEN, ALWAYS — but never silently, which is a different promise.
        #
        # The policy is right: a broken gate must not stop an agent working. The silence
        # was not. On 2026-08-05 a one-character slip in this file — `s` where `sess` was
        # meant — raised NameError on every relaxed-arm call, and this handler swallowed
        # it. The gate was OFF for half of all sessions and the only symptom was that it
        # never fired, which is indistinguishable from the relaxed arm behaving exactly as
        # designed. It was found by a test that asked where the threshold was, not by
        # anything noticing the instrument had stopped.
        #
        # So the exception is now recorded and printed. stderr, not a deny payload: a
        # non-zero exit would turn a crash into a block, which is precisely the failure
        # direction this handler exists to prevent.
        try:
            import traceback
            log = STATE_DIR / 'gate-errors.jsonl'
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, 'a') as fh:
                fh.write(json.dumps({
                    'at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
                    'error': f'{type(e).__name__}: {e}',
                    'where': traceback.format_exc().strip().splitlines()[-2][:200],
                }) + '\n')
            sys.stderr.write(
                f'laserbrain gate: FAILED OPEN — {type(e).__name__}: {e}\n'
                f'The gate did not run for this call. It is not protecting anything until '
                f'this is fixed; see {log}.\n')
        except Exception:
            pass                                 # a broken reporter must not break the hook
    sys.exit(0)
