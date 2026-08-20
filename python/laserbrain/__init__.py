"""
laserbrain — attach the smart recursion harness to any agent loop.

The check is a pure function, so it runs LOCALLY and free — the open grammar, no
key, no latency, no account. That is `ground`, and it is the whole instrument: the
SDK writes every session to disk and keeps it forever, so there is nothing about
one machine you have to pay for.

What a key buys is a PLACE. `group` lets several machines meet — one view across
them, shared history, a ground that outlives the process that set it. `pro` adds
more machines and the statistics over them. You are paying for somewhere to meet,
not for the detector.

    phronesis.world/laserbrain

Model-agnostic: you provide the agent, laserbrain closes the loop.

    from laserbrain import Harness
    hz = Harness()                                  # local + free (add key=... to retain)
    v = hz.check(goal="build the parser", progress="advancing", distance=6)
    if v.drifting: ...                              # v.advice tells the agent to return

    hz.run(step, on_return=lambda v, ctx: ...)      # the act layer: auto-inject the return

    from laserbrain import Team
    Team("adversarial-deliberation", goal="…").run(agent_fn)   # a styled recursion team

The single-agent detector mirrors the frozen drift.ts @ 6b483de7 (the published
instrument); the multi-agent dialogue + recursion teams are the prototype extension.
"""
from __future__ import annotations
from dataclasses import dataclass
import datetime as _dt, hashlib, json, os, re, time as _time, uuid as _uuid
from pathlib import Path as _Path

__all__ = ['Harness', 'Team', 'Verdict', 'PRESETS', 'norm', 'laserscore', 'context_id',
           'verify_audit', 'ground_score', 'MAX_DEPTH']
__version__ = '0.53.0'
MAX_DEPTH = 50   # nesting deeper than this is a drift signal, not a decomposition
API_DEFAULT = 'https://laserbrain-mcp.degibug.workers.dev'


# ── provenance: a tamper-evident, hash-chained ledger of every check ───────────
def _canon(d):
    return json.dumps(d, sort_keys=True, separators=(',', ':'))


def _link(prev, body):
    return hashlib.sha256((prev + _canon(body)).encode()).hexdigest()


def verify_audit(chain: list) -> tuple:
    """Independently verify an exported audit chain. Returns (ok, first_bad_index):
       (True, -1) if intact, else (False, i) at the first tampered/broken link.
       Free and offline — anyone can audit an agent's run without a key."""
    prev = ''
    for i, rec in enumerate(chain):
        body = {k: rec[k] for k in rec if k != 'hash'}
        if rec.get('prev') != prev or _link(prev, body) != rec.get('hash'):
            return (False, i)
        prev = rec['hash']
    return (True, -1)


_SPARK = '▁▂▃▄▅▆▇█'


def _sparkline(values: list, lo: float = 0.0, hi: float = None) -> str:
    """A dep-free unicode sparkline of a numeric series."""
    if not values:
        return ''
    hi = hi if hi is not None else (max(values) or 1.0)
    rng = (hi - lo) or 1.0
    n = len(_SPARK) - 1
    return ''.join(_SPARK[min(n, max(0, int((v - lo) / rng * n)))] for v in values)

# ── the fixed-reference primitive (frozen: drift.ts @ 6b483de7) ────────────────
def _grammar():
    """The shipped grammar.json — the one document all four implementations read.

    Synced from lasermind/grammar.json by scripts/sync-grammar.mjs and packaged with the
    wheel, because a pip install cannot reach the repo it came from. The literals below
    remain as a fallback for the case where the file is somehow absent: an instrument that
    refuses to start because a data file moved is worse than one that starts on its last
    known-good constants and says so.

    These numbers used to be typed out in nine places — thirty stopwords and a stem rule
    here, in mcp-server.mjs, in drift.ts and in three lasermind scripts, plus three
    calibration constants in each of three implementations. check-normaliser-parity.mjs
    existed only to police that copying. A list nobody retypes needs no policing.
    """
    try:
        with open(_Path(__file__).parent / 'grammar.json', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


_G = _grammar()
_FALLBACK_STOP = {'the', 'a', 'an', 'to', 'of', 'and', 'or', 'for', 'in', 'on', 'at', 'is', 'it',
                  'this', 'that', 'with', 'my', 'your', 'our', 'i', 'we', 'be', 'as', 'by',
                  'from', 'into', 'out', 'up', 'so', 'then'}
_STOP = set(_G.get('normalizer', {}).get('stopwords') or _FALLBACK_STOP)
_STEM = re.compile(_G.get('normalizer', {}).get('stem_pattern')
                   or r"(ings?|edly|ed|ers?|es|s|tion|ment)$")
_PROGRESS = {'advancing', 'stuck', 'circling'}


def norm(s):
    out = set()
    for w in re.findall(r"[a-z0-9']+", str(s).lower()):
        if w in _STOP:
            continue
        r = _STEM.sub('', w) if len(w) > 4 else w
        if r:
            out.add(r)
    return out


def _jac(a, b):
    if not a and not b:
        return 0.0
    return 1 - len(a & b) / len(a | b)


def _sim(a, b):
    return 1 - _jac(a, b)


def _asdist(d):
    try:
        return max(0, min(10, int(float(d))))
    except Exception:
        return 5


def fires_first(checks):
    """Whichever raised the alarm first — the agent or the instrument.

    THE ONE THING THAT MEASURED WELL, on ARC-AGI-3, 2026-08-05.

    A 26-step run was scored two ways. The agent's own `progress` reports flagged trouble at
    steps 8, 12 and 21. The instrument's readings flagged it at 11 and 18. Neither is a
    subset of the other:

        step  8   the agent saw it, the instrument was silent
        step 11   the instrument fired while the agent was still reporting `advancing`
        step 18   the same, and the agent did not catch up until 21 — three steps later

    Union: 5 episodes against 3 for the agent alone and 2 for the instrument alone, and
    4 steps of lead across 26 — 15% of the run. On a benchmark scored by action efficiency
    that 15% is not a side effect, it is the metric.

    WHY IT WORKS, and it is not that one source is better. The agent is smarter — it reads
    the situation and can see what no rule anticipates, which is how it caught step 8. The
    instrument is more precise — it applies one rule identically every time and does not
    flatter itself, which is how it caught 11 and 18 while the agent was talking itself
    into `advancing`. Precision catches what intelligence rationalises away; intelligence
    catches what precision has no rule for.

    So: do not arbitrate between them. Take whichever fires first.

    `checks` is any sequence of rows carrying `step`, `progress` and `reason` — the shape
    the session file already stores. Returns the episodes in order, each naming the step,
    the source that called it, and how far ahead of the other it was.
    """
    STALL = {'stalled', 'oscillating'}
    OWN = {'stuck', 'circling'}

    def episodes(pred):
        out, on = [], False
        for c in checks:
            now = bool(pred(c))
            if now and not on:
                out.append(c.get('step'))
            on = now
        return out

    inst = episodes(lambda c: str(c.get('reason') or '') in STALL)
    own = episodes(lambda c: c.get('progress') in OWN)
    out = []
    for step in sorted(set(inst) | set(own)):
        by_inst, by_own = step in inst, step in own
        source = 'both' if (by_inst and by_own) else ('instrument' if by_inst else 'agent')
        other = own if by_inst else inst
        later = [x for x in other if x > step]
        out.append({'step': step, 'first': source,
                    'lead': (later[0] - step) if later else None})
    return out


def laserscore(goal, progress, distance=None, parent_goal=None) -> str | None:
    """One well-formed reading written in the grammar, in canonical form.

    The grammar is the notation. A laserscore is what gets written in it at a single
    step. Φ is a measurement taken of that writing. Naming the middle term is what lets
    the two failures be told apart: a state that cannot be spelled at all is caught
    before any number exists, and no number is ever reported for it.

    The rendering shows exactly the three slots Φ reads, inflection already collapsed by
    norm(), which is why 'building billboards' and 'build a billboard' write the same
    score. Kept byte-identical to the server's renderer in lasermind/mcp-server.mjs --
    test_laserscore_conformance.py fails if the two ever disagree.
    """
    # The precondition, enforced 2026-07-27. The grammar says a laserscore exists only
    # for a well_formed state and is null otherwise — and Harness.check has always
    # honoured that, emitting 'ungrammatical' before any score is written. This function,
    # which anyone can call directly, did not: it rendered '⟨⟩ advancing d5' for an empty
    # goal and '⟨billboard|ship|sky⟩ bogus d5' for a progress value outside the enum.
    # Both are readings of states that cannot be spelled, which is precisely the thing
    # the null is supposed to detect. Found by adding laserscore to the drift vectors and
    # noticing two 'ungrammatical' steps had a score.
    if not goal or not str(goal).strip() or progress not in _PROGRESS:
        return None

    def tok(v):
        return '|'.join(sorted(norm(v)))
    d = 'd?' if distance is None else f'd{_asdist(distance)}'
    base = f'⟨{tok(goal)}⟩ {progress} {d}'
    if parent_goal and str(parent_goal).strip():
        return f'{base} ⊂ ⟨{tok(parent_goal)}⟩'
    return base


def context_id(goal) -> str | None:
    """A stable name for the context a goal belongs to, or None if it cannot be spelled.

    The token set a laserscore already renders IS a fingerprint — inflection collapsed,
    order removed — which is exactly why 'build the parser' and 'building a parser' do not
    score as drift. It was computed, printed once and discarded every step, so the harness
    met the same context on Monday and Thursday with no way to know it had been there.

    FNV-1a over the canonical token string: a function of the words alone, with no clock,
    counter or insertion order in it, so the same context always names itself the same way
    on any machine and in any process. Kept byte-identical to the server's contextId in
    lasermind/mcp-server.mjs — the two are a shared vocabulary or they are nothing, since
    an id that differs between implementations is worse than no id at all.
    """
    toks = '|'.join(sorted(norm(goal)))
    if not toks:
        return None
    h = 0x811c9dc5
    for ch in toks:
        h ^= ord(ch)
        # JS does `Math.imul(h, 0x01000193) >>> 0`; the mask is that `>>> 0`. Without it
        # Python's unbounded ints keep growing and the two implementations diverge on the
        # very first character.
        h = (h * 0x01000193) & 0xFFFFFFFF
    return 'ctx_' + _b36(h)


def _b36(n):
    """Base-36, matching JS Number.prototype.toString(36)."""
    if n == 0:
        return '0'
    digits = '0123456789abcdefghijklmnopqrstuvwxyz'
    out = ''
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


# Written by both implementations, in the same format, at the same path. That is the whole
# point: a context met through the MCP server on Monday is the same context met through the
# package on Thursday, or the memory is worthless.
from . import _paths as _P
from . import _evidence                     # the observed channel, fed by the runtime
CONTEXTS = _P.config('contexts.json')


def _read_contexts():
    try:
        d = json.loads(CONTEXTS.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _with_context_lock(fn, timeout=2.0):
    """Serialise read-modify-write on contexts.json across processes AND languages.

    Measured before this existed: eight concurrent writers recording five checks each
    stored 36 of 40. The file never corrupted — small writes land atomically enough for
    that — but updates were silently lost, because every writer read the whole map,
    edited its own entry, and wrote the whole map back over everyone else's.

    Silent undercounting is worse here than an error would be. `repetition` is what
    raises the `repeating` verdict, so a dropped write does not merely lose a statistic,
    it suppresses a judgment that was true.

    O_CREAT|O_EXCL is atomic on POSIX and has the same semantics as Node's 'wx' flag,
    which is what lets the server and the package take the same lock. A lock older than
    ten seconds is stolen: a crashed writer must not wedge the store forever. On timeout
    the write proceeds unlocked — a possibly-lost update is strictly better than dropping
    the write with certainty.
    """
    lock = CONTEXTS.with_name(CONTEXTS.name + '.lock')
    deadline = _time.monotonic() + timeout
    held = False
    while True:
        try:
            CONTEXTS.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            held = True
            break
        except FileExistsError:
            try:
                if _time.time() - lock.stat().st_mtime > 10:
                    lock.unlink()
                    continue
            except Exception:
                pass
            if _time.monotonic() > deadline:
                break
            _time.sleep(0.005)
        except Exception:
            break
    try:
        return fn()
    finally:
        if held:
            try:
                lock.unlink()
            except Exception:
                pass


def remember_context(cid, goal, distance, reason, run=None, score=None):
    """Record one sighting of a context; return what was known BEFORE it.

    Returns (prior, repetition) — the prior lets a caller tell "first time here" from
    "fourth time here", and `repetition` is how many times this exact laserscore has now
    been written in this context.

    Counting spellings within a context is a reading neither mechanism gives alone: the
    context knows which work this is but nothing about its state, and a laserscore states
    the case exactly but remembers nothing. Mirrors rememberContext in
    lasermind/mcp-server.mjs, including the file format, since both write this file.
    """
    if not cid:
        return None, 0
    # The read and the write are one critical section: reading outside the lock is what
    # made the lost updates possible in the first place.
    return _with_context_lock(lambda: _remember_context_locked(cid, goal, distance, reason, run, score))


def _remember_context_locked(cid, goal, distance, reason, run, score):
    all_ = _read_contexts()
    prior = dict(all_[cid]) if cid in all_ else None
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')
    e = all_.get(cid) or {
        'id': cid, 'tokens': sorted(norm(goal)), 'first_seen': now,
        'sessions': [], 'checks': 0, 'best_distance': None, 'outcomes': {}, 'spellings': {},
    }
    e['last_seen'] = now
    e['checks'] = e.get('checks', 0) + 1
    d = _asdist(distance)
    e['best_distance'] = d if e.get('best_distance') is None else min(e['best_distance'], d)
    e.setdefault('outcomes', {})
    e['outcomes'][reason] = e['outcomes'].get(reason, 0) + 1
    # Sessions are CAPPED, with the true total kept alongside.
    #
    # The list was unbounded and the whole map is read and rewritten on every check, so an
    # ever-growing array does not merely take disk — it makes every future check slower,
    # forever, on a file a published package writes into every user's home directory. One
    # context in the real store had already reached 88 session ids.
    #
    # The list is only needed to recognise the CURRENT run and avoid double-counting it;
    # `session_count` carries the history that judgment actually reads. Twenty is far more
    # than the dedup needs and keeps the record legible.
    e.setdefault('sessions', [])
    e.setdefault('session_count', len(e['sessions']))
    if run and run not in e['sessions']:
        e['sessions'].append(run)
        e['session_count'] = e.get('session_count', 0) + 1
        if len(e['sessions']) > 20:
            e['sessions'] = e['sessions'][-20:]
    e.setdefault('spellings', {})
    repetition = 0
    if score:
        e['spellings'][score] = e['spellings'].get(score, 0) + 1
        repetition = e['spellings'][score]
    all_[cid] = e
    try:
        CONTEXTS.parent.mkdir(parents=True, exist_ok=True)
        CONTEXTS.write_text(json.dumps(all_, indent=1))
    except Exception:
        pass   # fail open: a context we cannot store is a memory we lack, not an error
    return prior, repetition


def _cycle(reasons):
    """The period of a repeating cycle at the tail of the trace, or 0.

    Falls out of x = [x, f(x)]: a fixed-point iteration either converges, diverges or
    CYCLES, and the harness had a verdict for the first two and nothing for the third.
    An agent bouncing between two grounds gets a correct verdict every step and is never
    told the sequence is the problem.

    Whole repeats only, and more than one distinct reading — a constant tail is a settled
    state, not an oscillation, and calling it one would fire on every healthy run.

    PERIODS 2..6, not 2..3. The first version tested only 2 and 3, which happens to miss
    the canonical example of the equation it was derived from. Take x = [sin, f(x)] with
    f = d/dx: sin -> cos -> -sin -> -cos -> sin, period FOUR. Sixteen readings, four
    complete repeats, and the detector returned 0 — the cleanest cycle in mathematics was
    invisible to the verdict built to find cycles. Nothing failed; there was simply no
    period-4 arm to fail.

    Ascending order matters: [a,b,a,b,a,b] is period 2 and also satisfies period 4, and
    the smaller period is the true one, so the first match must win.

    Two whole repeats is the evidence bar, with a floor of six readings — `need` is
    max(6, 2p), which leaves p=2 and p=3 at exactly their old six-reading behaviour and
    asks eight for p=4. Above six, the window required (twelve-plus consecutive readings)
    exceeds anything a real run produces, and a pattern that long is better described as a
    process than an oscillation.
    """
    for p in range(2, 7):
        need = max(6, 2 * p)
        if len(reasons) < need:
            continue
        tail = reasons[-need:]
        if len(set(tail)) < 2:
            continue
        if all(tail[i] == tail[i % p] for i in range(need)):
            return p
    return 0


def _clamp01(x):
    try:
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0


class Calibration:
    """The instrument's numbers, in one object, changeable on purpose.

    Until v0.4.0 these were six literals buried in the decision path. Mutation testing
    on 2026-07-24 showed the suite stayed green when the goal threshold moved 0.30->0.45
    and when the weights were reshuffled — so the published instrument could be retuned
    silently. Naming them does two things at once: it makes retuning POSSIBLE for callers
    who need a different sensitivity, and it makes it VISIBLE, because `Calibration()`
    with no arguments is the published instrument and anything else is an argued choice.

    The theorem is untouched either way. PROOF requires a reference that does not move
    DURING a run; it says nothing about which threshold you picked before it started.
    A Calibration is fixed for the life of a _Run — that is the part that is load-bearing.
    """

    __slots__ = ('goal_min', 'self_report_min', 'stall_window', 'w_goal', 'w_distance',
                 'w_progress', 'echo_min', 'dialogue_window', 'max_checks')

    # Defaults come from grammar.json's `calibration` block, with the published literals
    # as a fallback if the file is missing. `Calibration()` with no arguments therefore
    # still means "the published instrument" — it just no longer means "whatever numbers
    # were last typed into this signature". The same three numbers were retyped in
    # mcp-server.mjs and drift.ts; all three now read the one document.
    _D = (_G.get('calibration') or {})
    _W = (_D.get('weights') or {})

    def __init__(self, goal_min=_D.get('goal_min', 0.30),
                 self_report_min=_D.get('self_report_min', 0.15),
                 stall_window=_D.get('stall_window', 4),
                 w_goal=_W.get('goal', 0.5), w_distance=_W.get('distance', 0.3),
                 w_progress=_W.get('progress', 0.2),
                 echo_min=_D.get('echo_min', 0.25),
                 dialogue_window=_D.get('dialogue_window', 3),
                 max_checks=_D.get('max_checks')):
        for name, v in (('goal_min', goal_min), ('self_report_min', self_report_min)):
            if not 0.0 <= float(v) <= 1.0:
                raise ValueError(f'{name} must be within 0..1, got {v!r}')
        if int(stall_window) < 1:
            raise ValueError(f'stall_window must be >= 1, got {stall_window!r}')
        total = float(w_goal) + float(w_distance) + float(w_progress)
        if abs(total - 1.0) > 1e-9:
            # Not pedantry: Φ is read against fixed thresholds and reported to users as a
            # 0..1 displacement. Weights that sum to anything else silently rescale it.
            raise ValueError(f'weights must sum to 1.0, got {total:.6f}')
        self.goal_min, self.self_report_min, self.stall_window = float(goal_min), float(self_report_min), int(stall_window)
        if not 0.0 <= float(echo_min) <= 1.0:
            raise ValueError(f'echo_min must be within 0..1, got {echo_min!r}')
        if int(dialogue_window) < 1:
            raise ValueError(f'dialogue_window must be >= 1, got {dialogue_window!r}')
        self.w_goal, self.w_distance, self.w_progress = float(w_goal), float(w_distance), float(w_progress)
        self.echo_min, self.dialogue_window = float(echo_min), int(dialogue_window)
        # A COUNT, NOT A JUDGMENT. None means no budget — the published instrument.
        self.max_checks = None if max_checks is None else max(1, int(max_checks))

    def __eq__(self, o):
        return isinstance(o, Calibration) and all(
            getattr(self, f) == getattr(o, f) for f in self.__slots__)

    def __repr__(self):
        d = ', '.join(f'{f}={getattr(self, f)}' for f in self.__slots__)
        return f'Calibration({d})'

    @property
    def is_published(self):
        """True when this is the instrument as shipped — what drift.ts carries at 6b483de7."""
        return self == PUBLISHED


PUBLISHED = Calibration()


def _displacement(goal, progress, distance, ground, sim=None, cal=None):
    # The goal term is the only VOCABULARY judgment — swap `sim` to change the
    # grammar without touching the theorem (PROOF blesses *a* fixed reference,
    # never a particular vocabulary). sim=None keeps the frozen word-overlap path.
    cal = cal or PUBLISHED
    goal_term = (1.0 - _clamp01(sim(goal, ground['goal']))) if sim else _jac(norm(goal), norm(ground['goal']))
    # None means "not known", not "zero" and not the 5 that _asdist would fall back to.
    # An unknown term contributes nothing, which makes Φ a LOWER bound: inferred state can
    # under-report drift and cannot invent it. See observe.py.
    if distance is None or ground['dist'] is None:
        dist_term = 0.0
    else:
        dist_term = abs(_asdist(distance) - ground['dist']) / 10
    return (cal.w_goal * goal_term
            + cal.w_distance * dist_term
            + cal.w_progress * (0 if progress == ground['progress'] else 1))


_DRIFT = ('ungrammatical', 'goal-drift', 'stalled')


def _terms(goal, progress, distance, ground, sim=None, cal=None):
    """The three components of Φ, separately. Handed back with the verdict so a reader
    can see WHICH part moved rather than being told a single number."""
    cal = cal or PUBLISHED
    g = (1.0 - _clamp01(sim(goal, ground['goal']))) if sim else _jac(norm(goal), norm(ground['goal']))
    if distance is None or ground['dist'] is None:
        d = None
    else:
        d = abs(_asdist(distance) - ground['dist']) / 10
    pr = 0 if progress == ground['progress'] else 1
    return {'goal': cal.w_goal * g, 'distance': None if d is None else cal.w_distance * d,
            'progress': cal.w_progress * pr}


def _isdrift(reason):
    return reason in _DRIFT or reason.startswith('self-report')


def ground_score(phi: float) -> float:
    """Turn a displacement Φ into a bounded [0,1] 'how grounded' reading: 1.0 at
       ground, falling as the agent displaces. This is v's system score, 1/(1+4·P),
       applied to Φ — the shared primitive between laserbrain and the language of
       zeros (see the note "The Present as the Fixed Reference")."""
    try:
        return round(1.0 / (1.0 + 4.0 * max(0.0, float(phi))), 3)
    except Exception:
        return 0.0


@dataclass
class Verdict:
    drifting: bool
    reason: str
    phi: float
    advice: str
    # The evidence behind the verdict, in plain English and actual numbers. A monitor
    # that can only interrupt gets switched off; one that can be argued with gets
    # trusted. Defaulted so every existing Verdict(...) call site keeps working.
    why: str = ''
    # The grammatical object this verdict was derived FROM, in canonical form. None
    # exactly when the state could not be spelled -- for an 'ungrammatical' verdict that
    # None is not a missing field, it is the finding. Defaulted so every existing
    # Verdict(...) call site keeps working.
    laserscore: str = None
    # How much of Φ's weight is anchored OUTSIDE the agent's own account of itself.
    #
    # The product claim is that laserbrain measures against a fixed external reference,
    # which an agent watching only itself provably cannot do. That is true of the goal
    # term — the ground is frozen at first call and cannot be revised mid-run — and it is
    # NOT true of the other two: `distance` and `progress` are whatever the agent says
    # they are. On the published calibration that is 0.5 anchored and 0.5 self-report, and
    # nothing said so. An agent that simply reports its distance falling keeps Φ low while
    # doing nothing at all.
    #
    # So: 0.5 when only the ground is anchored, 1.0 when the self-reported terms are
    # corroborated by observed events since the last check. Reported, never folded into
    # Φ — reweighting would move the published instrument and invalidate every calibration
    # and vector, and there is no data yet to justify a particular new weight. This is the
    # honest thing that can be said today: here is the number, and here is how much of it
    # you are taking on trust.
    anchored: float = 1.0
    # How much of the goal just spelled is still the goal this run started with.
    #
    # Computed since the beginning and reported only on failure: it decides the goal-drift
    # verdict, was interpolated into the advice STRING at the moment it crossed the floor,
    # and was invisible at every other step. So the one number that says how far the
    # SUBJECT has travelled could only be read once it had already gone too far.
    #
    # It answers a different question from Φ, which is why it deserves its own slot. Φ
    # asks 'how far from ground', this asks 'still the same errand?'. A faithful goal can
    # sit at high Φ while the work is genuinely hard, and a low-Φ reading can belong to a
    # task nobody asked for. Defaulted so every existing Verdict(...) call keeps working.
    goal_score: float = 1.0
    # The context this verdict was taken in — stable across sessions and machines, so a
    # run can be recognised as another attempt at something already tried. See context_id.
    context: str = None
    # Set only when a parent_goal was declared AND fell below goal_min. None means no
    # declaration was made; a number means one was made, measured, and rejected — and the
    # advice says so rather than telling the agent to do what it just did.
    parent_overlap: float = None
    # THE FROZEN GROUND, RETURNED ON EVERY VERDICT — not only when one fires.
    #
    # Until 2026-08-18 the ground came back only inside a firing `goal-drift`, buried in
    # `why`. So an agent on a healthy step never saw the goal it started with, and the
    # advice could say "return to the goal you started with" without saying what that was.
    #
    # That made re-presentation conditional on a detector with 4/50 published precision,
    # while the mechanism measured to work is unconditional: re-presenting the ground at
    # every step took rule survival from 0/8 chains to 8/8, with no detector in the loop.
    # A generic reminder to be careful, fired just as often, scored 0/6 — exhortation is
    # not transmission.
    #
    # WHAT IT COSTS IS UNMEASURED, and an earlier version of this comment claimed
    # otherwise. It said 11.9% cheaper than carrying no constraint, from a cache-position
    # test that did not replicate: the identical manipulation measured -11.9% one day and
    # +5.9% the next, within-arm variance reached 101% of the mean, and no contrast
    # cleared |t| = 2. Sixteen links per arm cannot resolve a 10% effect at that spread;
    # roughly 250 would be needed. Placing this ahead of per-step varying content should
    # still help in principle, but it has not been demonstrated.
    #
    # The reason for the field is untouched: unconditional re-presentation takes rule
    # survival from 0/8 relayed chains to 8/8, scored by substring match in plain code
    # with no judge and no billing involved.
    ground: str = None
    # The introspection ceiling, read off the agent's own words rather than its events.
    #
    # `anchored` asks whether observed work backs the claim; this asks whether the agent
    # was CLAIMING or REPORTING in the first place. They disagree in both directions and
    # that is the point: an agent that ran nothing but wrote pure observation is
    # unanchored and honest, and one whose tests passed but who writes "this should fix
    # it" is corroborated and still guessing.
    #
    # None when the step carried no free text, or when no phrase matched — a marker that
    # read nothing must not report 0.0, which would mean "entirely cause-claims". Like
    # `anchored`, reported and NEVER folded into Φ. See laserbrain/ceiling.py.
    #
    # TEST IT WITH `is None`, NEVER FOR TRUTHINESS. None and 0.0 are both falsy, so
    # `if v.claims['grounded']:` silently merges "the marker read nothing" with "every
    # phrase was a cause-claim" — the exact distinction this field exists to draw. That
    # is why `scores` omits the key entirely rather than carrying a number for it.
    claims: dict = None

    @property
    def ground_score(self) -> float:
        """Φ as a bounded [0,1] confidence-in-ground reading (1.0 = fully grounded)."""
        return ground_score(self.phi)

    @property
    def scores(self) -> dict:
        """Every reading this verdict carries, named — not one blended number.

        A single figure hides which thing went wrong. A goal held faithfully through hard
        work and a goal quietly swapped for an easier one sit at the same Φ, and the
        difference between them is the only part worth knowing.
        """
        out = {
            'goal': round(self.goal_score, 2),
            'ground': round(self.ground_score, 2),
            'drift': round(self.phi, 2),
            'evidence': round(self.anchored, 2),
        }
        # Present only when the marker actually read something. An absent key is
        # "no free text was spelled this step", which is different from a low score
        # and must not be reported as one.
        if self.claims and self.claims.get('grounded') is not None:
            out['language'] = self.claims['grounded']
        return out

    def __str__(self) -> str:
        mark = '⚑ drifting' if self.drifting else ('✓ grounded' if self.reason == 'grounded' else '· on track')
        return f'[{mark}] {self.reason} · Φ={self.phi:.2f} · ground={self.ground_score:.2f} — {self.advice}'


class _Run:
    """Single-agent drift state for one task run."""
    def __init__(self, sim=None, cal=None):
        self.ground = None
        self.first_goal = set()
        self.first_goal_text = ''
        self.sim = sim           # optional custom text-similarity (the pluggable grammar)
        # Fixed for the life of the run. Swapping calibration mid-run would move the
        # reference while measuring against it, which is the one thing PROOF forbids.
        self.cal = cal or PUBLISHED
        self.dist_hist = []
        self.trace = []          # (reason, drifting)
        # The canonical spelling of the GROUND at each step. Separate from `trace` because
        # trace is unpacked as (reason, drifting) in several places and widening the tuple
        # would break every one of them silently.
        #
        # This exists because of x = [x, f(x)]. The state is the PAIR — the ground and its
        # measurement — and `trace` only ever held the measurement. Running the cycle
        # detector on verdicts alone was running it on f(x), so a genuinely cycling agent
        # was only caught when its READINGS happened to line up periodically too, which is
        # a coincidence stacked on top of the thing we actually wanted to detect. A ground
        # that returns to a previous ground is the cycle, whatever the verdicts did.
        self.trail = []
        # Events observed since the last check — what the agent DID, as opposed to what it
        # says about itself. Cleared each check, because corroboration is a claim about the
        # interval just measured, not about the run as a whole.
        self.evidence = []
        self._backed = []
        self.corroborated = 0       # checks whose self-report was backed by observed work
        # WHETHER ANYTHING WAS EVER OBSERVED. Without it, "never corroborated" cannot be
        # told apart from "nobody called saw()", and a harness used bare — every test in
        # this repo, and any user who skips an optional API — would be accused of claiming
        # progress it had not earned. Uninstrumented is not the same as unbacked, and an
        # instrument that cannot tell them apart must say nothing.
        self.saw_any = False
        # WHERE THE RUNTIME COUNTER STOOD WHEN THIS RUN BEGAN. Corroboration is an advance
        # between two checks, never a total, so a counter already carrying thousands of
        # outcomes from earlier work starts this run at zero credit. Read at construction
        # rather than at the first check, or everything that happened between the two would
        # be silently claimed by it.
        # TWO BASELINES, because liveness and corroboration are different questions.
        # `_ev_seen` is every outcome, pass or fail — a run whose work all failed is the most
        # instrumented case there is, and must read as live so `unbacked` can speak. `_ev_ok`
        # is successes only, and it is what corroboration advances against.
        try:
            _ok, _fail = _evidence.count()
            self._ev_mark = self._ev_ok = _ok
            self._ev_seen = _ok + _fail
        except Exception:
            self._ev_mark = self._ev_ok = self._ev_seen = 0
        self.checks = 0
        self._osc = False        # already reported an oscillation for the current cycle
        # Identity of this run, so a context can count the SESSIONS it has been opened in
        # and not merely the checks. Three attempts across three sessions is a different
        # fact from thirty checks in one, and only the first justifies 'abandon'.
        # Random, not a timestamp. A millisecond clock collides: thirty runs created in a
        # loop produced only fourteen distinct ids, so a context opened thirty times
        # reported thirteen and the sentence "opened in N earlier sessions" was simply
        # false. The server has always used randomUUID here; this matches it.
        self.run_id = _uuid.uuid4().hex[:12]
        self.repetition = 0      # times the current spelling has been written in its context
        self.context = None
        # WHERE THE CURRENT GROUND BEGINS, as an index into `trace`.
        #
        # A reground replaces the setpoint: ground, first_goal and dist_hist all become the
        # new goal's. `trace` deliberately does not reset, because the rules that judge the
        # SEQUENCE of grounds — oscillation, drifts-against-regrounds — have no subject
        # without it. But the rules that judge PROGRESS were reading that same trace, so on
        # the first check after a reground they saw a dozen checks of someone else's work
        # against a distance that had just been re-zeroed. `steps >= 12 and closed <= 0` was
        # then true by construction, and the strongest counsel the instrument owns — stop
        # working — was delivered on the first check of a task nobody had attempted yet.
        # Observed live 2026-08-04; test_windup.py holds it down.
        #
        # This is integrator windup across a setpoint change, and this index is the
        # anti-windup reset: progress is measured from here, sequence is measured from zero.
        self.ground_at = 0

    def _goal_score(self, goal):
        """Overlap between the goal just spelled and the one this run started with."""
        if not self.first_goal:
            return 1.0
        g = set(norm(goal))
        union = g | self.first_goal
        if not union:
            return 1.0
        return round(len(g & self.first_goal) / len(union), 2)

    def phronesis(self):
        """Judgment, beside the measurement. Returns a verdict on the WORK, not the state.

        Φ is a distance; it is silent on whether the journey is worth making. An agent can
        hold a perfect goal score, report advancing honestly, sit at Φ=0.05 — and be twelve
        checks into work that has not moved the distance once. Every existing verdict calls
        that 'advancing', because by its own definition it is.

        This is deliberately willing to say abandon. An instrument that can only ever
        counsel continuing is offering encouragement rather than judgment, and the agent
        already supplies plenty of that itself.

        Kept in step with the `phronesis` tool in lasermind/mcp-server.mjs: same verdicts,
        same thresholds, same evidence. One instrument, two front doors.
        """
        dh, trace = self.dist_hist, self.trace
        steps = len(trace)
        # THE SPLIT. `steps` is the whole run and stays that way for the rules whose
        # subject IS the whole run — a cycle in the ground, drifts weighed against
        # regrounds. `here` is the current setpoint's own accumulator, and every rule that
        # asks "is this work going anywhere" reads that instead, because `closed` and
        # `pace` are computed from a dist_hist the reground already re-zeroed. Pairing a
        # never-reset counter with a reset distance is what made `abandon` fire on the
        # first check of a fresh task. See ground_at.
        here = max(1, steps - self.ground_at)
        since = trace[self.ground_at:]
        if not self.ground or not steps:
            return {'verdict': 'ungrounded',
                    'because': 'No ground state — nothing has been measured yet.',
                    'counsel': 'Ground a goal first; judgment needs a trace to judge.'}

        started, now = (dh[0] if dh else None), (dh[-1] if dh else None)
        closed = (started - now) if (started is not None and now is not None) else 0
        pace = closed / here
        reasons = [r for r, _ in trace]
        # Stalls belong to the work in front of you; a stall on a goal the user replaced is
        # not evidence about the goal they replaced it with.
        stalls = [r for r, _ in since].count('stalled')
        # These two keep the whole trace on purpose. `oscillating` exists to catch an agent
        # returning to grounds it has already held, and the drift-against-reground ratio is
        # a statement about the sequence of grounds. Scoping either to the current ground
        # would delete its subject.
        goal_drifts = reasons.count('goal-drift')
        regrounds = reasons.count('reground')
        oscillations = reasons.count('oscillating')

        flat = 0
        for i in range(len(dh) - 1, 0, -1):
            if dh[i] >= dh[i - 1]:
                flat += 1
            else:
                break

        gs = self._goal_score(self.ground.get('goal', '') if isinstance(self.ground, dict)
                              else self.first_goal_text)
        window = getattr(self.cal, 'stall_window', 4)

        # The two mechanisms read together. `repetition` is how many times the CURRENT
        # spelling has been written in this context; `ceiling` is the closest this context
        # has ever come to done across every session. Neither is available to either
        # mechanism alone — a context knows which work this is but nothing of its state,
        # and a laserscore states the case exactly but remembers nothing.
        cid = self.context or context_id(self.first_goal_text)
        known = _read_contexts().get(cid) if cid else None
        spellings = (known or {}).get('spellings') or {}
        repetition = max(spellings.values()) if spellings else 0
        ceiling = (known or {}).get('best_distance')
        # From session_count, not from the capped list: reading len(sessions) would have
        # quietly stopped counting past twenty and weakened `abandon` exactly on the
        # longest-running contexts, which are the ones it exists to catch.
        _sess = (known or {}).get('sessions', [])
        _total = (known or {}).get('session_count', len(_sess))
        prior_runs = max(0, _total - (1 if self.run_id in _sess else 0))

        # Three checks before any hard verdict. Replaying the 141-run corpus, several
        # two-check runs were handed 'narrow' and 'wrong-problem' on a trace with almost
        # nothing in it. Judgment needs evidence; two readings is a rumour.
        judged = here >= 3

        # A BUDGET IS NOT A JUDGMENT, and it is checked before every one of them.
        #
        # Everything below reasons about the WORK — is it reachable, is it the right problem,
        # is the goal too large — and each is a call that can be wrong; published precision on
        # individual fires is 9-14.6%. A budget cannot be wrong that way. It is a count
        # against a number the caller chose: no evidence, no three-check warm-up, no
        # interpretation.
        #
        # Taken from Prime Intellect's harness, read 2026-08-06, where continuation is decided
        # by external gates plus maxTurns/maxTokens/maxContinuations and the agent's opinion is
        # never consulted at all. Hard limits do the stopping job laserbrain has been
        # attempting with `abandon`, and they do it without a precision problem.
        #
        # DEFAULT OFF, and the cost of that is worth naming rather than hiding: an optional
        # mechanism nobody switches on is worth nothing, which is precisely what happened to
        # `saw()`. It is off because arming it by default would silently change the published
        # instrument for every existing caller, and that is the one thing a calibration must
        # never do. Set Calibration(max_checks=N), or `max_checks` in grammar.json, to arm it.
        if self.cal.max_checks is not None and here >= self.cal.max_checks:
            verdict = 'over-budget'
            because = (f'{here} checks against a budget of {self.cal.max_checks}. This is a '
                       f'count, not an assessment of the work.')
            counsel = ('The budget you set is spent. Stop, or raise it deliberately — but '
                       'decide that rather than drifting past it.')
        elif judged and here >= 12 and closed <= 0:
            verdict = 'abandon'
            because = (f'{here} checks. Distance began at {started} and stands at {now} — it has '
                       f'never once improved. Nothing tried so far has moved this.')
            counsel = ('Stop. Either the approach is wrong or the goal is not reachable as stated. '
                       'Say plainly what is blocking it rather than taking a thirteenth run at it.')
        elif judged and prior_runs >= 2 and closed <= 0:
            # Only history can say this. A run watching itself sees one attempt and cannot
            # know it is the fourth — which is exactly the reading the context store exists
            # to make possible.
            verdict = 'abandon'
            because = (f'This context has been opened in {prior_runs} earlier sessions and closed in '
                       f'none. Best distance ever reached is {ceiling}; this run has closed {closed}.')
            counsel = ('A problem that resists three separate attempts is usually the wrong problem. '
                       'Change the approach or hand it back before spending another session.')
        elif judged and self.saw_any and self.corroborated == 0 and here >= 5 and closed > 0:
            # A CLAIM WITH NOTHING UNDER IT.
            #
            # Half of Φ is the agent's own account of itself — 0.5 anchored on the
            # published calibration — and `anchored` has been reported on every verdict
            # since it was added and read by nothing. An agent that simply reports its
            # distance falling keeps Φ low while doing no work at all, and every reading
            # it gets is `advancing`.
            #
            # This is the one case where the harness can say so: work WAS observed in this
            # run, so the machinery is live, and yet not one check had its self-report
            # backed by it, while the agent claims to have closed distance. `verify` is
            # the neighbouring verdict and a different fact — it fires when the observed
            # trace DISAGREES; this fires when there is nothing to agree with.
            verdict = 'unbacked'
            because = (f'Distance is reported down {closed} over {here} checks, and not one of '
                       f'them was backed by observed work — {self.corroborated} corroborated '
                       f'of {here}.')
            counsel = ('Run something and read the output before reporting progress again. '
                       'Half of this score is your own account of yourself, and nothing has '
                       'agreed with it yet.')
        elif judged and goal_drifts >= 3 and goal_drifts > regrounds and pace <= 0:
            # IT MAY ONLY COMMAND WITH CORROBORATION. Diego's call, 2026-08-16, after this
            # branch told an agent to stop working while it was working correctly. Shipped in
            # lasermind's mcp-server.mjs the same day; this is the same fix in the wheel,
            # which went out as 0.51.0 without it.
            #
            # What happened: a subagent's reset_task had destroyed the parent's ground, so the
            # parent's byte-identical goal string scored 0.02 five times running. Every input
            # to the condition above was true and every one was an artifact of the fault. The
            # counsel read "You are not solving what you set out to solve" — to an agent that
            # was solving exactly that, and had the goal string to prove it.
            #
            # The asymmetry is the point. goal_drifts, regrounds and pace are all computed by
            # this instrument from the agent's own words, so one fault in it can satisfy all
            # three at once. `corroborated` counts checks backed by observed work: output
            # something INDEPENDENT produced. It is the one signal laserbrain cannot
            # manufacture, and a verdict that can halt an agent should have to pass it.
            #
            # Uncorroborated the finding is neither suppressed nor softened into vagueness. It
            # is stated as what it is — a reading that may be about the instrument — and it
            # asks the agent to check its ground rather than to abandon its work.
            backed = self.corroborated
            verdict = 'wrong-problem'
            because = (f'The goal has failed its overlap check {goal_drifts} times against only '
                       f'{regrounds} legitimate re-grounds. The subject keeps moving while the '
                       f'ground stays put.'
                       + ('' if backed else
                          f' Nothing independent has agreed with any check in this run '
                          f'({backed} corroborated), so this pattern is equally consistent '
                          f'with the ground having moved underneath you.'))
            counsel = (
                ('You are not solving what you set out to solve. Either re-ground to the goal '
                 'you actually have now, or return to the original and finish it.')
                if backed else
                ('Check the ground before acting on this. Compare the goal you are passing '
                 'against the one this run started with — if they are the same, this reading '
                 'is the thing that is wrong, not your work. If they differ, re-ground to the '
                 'goal you actually have.'))
        elif oscillations and pace <= 0:
            # `pace <= 0` is load-bearing, and it was found by dogfooding rather than
            # reasoning: this judgment fired on a run whose distance had gone 6→4→3→2
            # monotonically. The cycle detector was reading the VERDICT sequence, which
            # repeats naturally when a healthy run is re-grounded a few times, and a
            # repeating verdict over falling distance is a rhythm, not a loop. Circling
            # means coming back to the same place; a run that is measurably closer than it
            # was has not come back anywhere.
            verdict = 'wrong-problem'
            because = ('A repeating cycle was detected and the distance is not falling — you have '
                       'returned to the same place after being told to return.')
            counsel = 'Returning again will land you here a third time. Change the approach, not the position.'
        elif judged and repetition >= 3 and pace <= 0:
            # THRESHOLD FROM THE CORPUS, not from taste. Re-derived 2026-08-05 on the OBSERVED
            # corpus, after 248 of 680 contexts turned out to be test fixtures — sweeps like a
            # conformance probe with 14,508 checks, which land on exactly the repeat tail this
            # threshold reads. Across 432 observed contexts the maximum identical-spelling
            # repeat distributes:
            #
            #     >= 2   12.0%   noise — ordinary work restates itself once
            #     >= 3    7.2%   buys 4.9 points over 2
            #     >= 4    6.0%   buys 1.2
            #     >= 5    5.8%   buys 0.2
            #
            # THE CONSTANT DOES NOT MOVE. The elbow is still between 2 and 3, and past 3 the
            # curve is flat — a context repeating four times usually repeats many more, so
            # raising the bar excludes almost nothing while missing the three-repeat cases.
            #
            # The figures it used to quote (382 contexts: 9.7% / 2.6% / 1.0%) were measured on
            # the mixed corpus. Stale, not wrong in kind: the >= 2 rate barely moved, which is
            # the check that the method still matches. What moved was the tail, and the tail
            # was fixtures.
            #
            # A stronger claim than `stalled`, hence its place above `narrow`. Stalled
            # reads the distance alone, and distance sits flat through legitimate
            # sub-work; an identical laserscore means goal, progress AND distance are all
            # unchanged. Not failing to get closer — writing the same sentence again.
            verdict = 'repeating'
            because = (f'The identical state has been written {repetition} times in this context. '
                       f'Goal, progress and distance are all unchanged.')
            counsel = ('Not a slow patch — the same patch. Change what you are doing, or say plainly '
                       'what is blocking it. Restating the position will not move it.')
        elif now is not None and now >= 6 and flat >= window:
            verdict = 'narrow'
            because = (f'Distance has sat at {", ".join(str(d) for d in dh[-flat:])} for {flat} checks '
                       f'without falling, and {now} is still far from done.')
            # NAME THE MECHANISM, or this counsel is a trap. Followed literally — replace
            # the goal with a smaller one — the reading layer then scores the new goal
            # against the ground and returns goal-drift at goal_score 0.00. Measured
            # 2026-08-05 while an agent was obeying it: narrow -> narrow the goal ->
            # goal-drift, phi 0.53, and the same counsel again. The instrument was
            # faulting an agent for doing exactly what it had just been told to do.
            #
            # `parent_goal` is the mechanism that makes narrowing legal, and it already
            # works: declare the original and the verdict is `excursion`, not drift. It
            # simply was never mentioned at the one moment an agent needs it.
            counsel = ('The goal is too large to close in one move. Name the smallest piece that would '
                       'genuinely reduce the distance and make that the goal — and pass the goal you '
                       'have now as parent_goal, so narrowing reads as a sub-task rather than as '
                       'drift.')
        elif now is not None and now <= 2 and closed > 0:
            verdict = 'finish'
            because = f'Distance is {now}, down from {started} over {here} checks.'
            counsel = 'Close it out. Do not add scope, refactor, or polish — finish what was asked and stop.'
        elif judged and stalls and pace <= 0 and now is not None and now >= 4:
            # `now >= 4` came out of the corpus: this branch was telling runs sitting at
            # distance 1 or 2 to break the goal into smaller pieces. At distance 1 you are
            # nearly there and the counsel is simply wrong — narrowing a goal that is one
            # step from done adds ceremony, not progress. Splitting is for work too large
            # to close, which is a statement about the distance remaining, not the stall.
            verdict = 'narrow'
            because = (f'{stalls} stall{"s" if stalls > 1 else ""} recorded and net distance closed is '
                       f'{closed} over {here} checks, still at {now}.')
            counsel = ('Motion without progress. Pick one concrete sub-result you can actually finish, '
                       'and make that the goal.')
        else:
            verdict = 'continue'
            because = (f'Distance {started} → {now} over {here} checks ({pace:.2f}/check), '
                       f'goal held at {gs}.')
            counsel = ('Working. Keep the goal fixed and keep going.' if pace > 0 else
                       'Holding ground but not closing yet. If the next two checks do not move the '
                       'distance, narrow the goal.')

        return {
            'verdict': verdict,
            # No 'drift' here: the SDK's trace holds (reason, drifting) and never carried Φ,
            # so a drift score would have to be invented rather than read. Φ is on the
            # Verdict, which is where it was actually measured.
            'scores': {'goal': gs,
                       'closure': round(closed / started, 2) if started else (1 if now == 0 else 0),
                       'pace': round(pace, 2),
                       # THE RUN'S RATE, not a fresh reading — and the difference was a bug.
                       #
                       # This called _anchor() again, here, and _anchor() answers "was the
                       # interval since the LAST CHECK backed by observed work". phronesis
                       # runs after the last check, so that interval is empty by
                       # construction and the answer was 0.5 however well corroborated the
                       # run had been. Measured on a six-check run with every check backed:
                       # corroborated 6 of 6, evidence 0.5.
                       #
                       # Worse, _anchor() increments `checks`, so every phronesis() call was
                       # adding a check that never happened to the denominator of the very
                       # rate this field should have been reporting.
                       #
                       # The same shape as the server's anchored() memo bug — a field that
                       # structurally could not report the thing it was named for, reported
                       # on every call, and read by nobody closely enough to notice.
                       'evidence': (round(self.corroborated / self.checks, 2)
                                    if self.checks else 0.0),
                       'recurrence': prior_runs,
                       'repetition': repetition,
                       'ceiling': ceiling},
            'because': because,
            'counsel': counsel,
            'control': self._control(here, prior_runs, goal_drifts, regrounds),
            'context': context_id(self.first_goal_text),
        }

    # ── THE SPLIT ───────────────────────────────────────────────────────────────────────
    #
    # Two decisions were being made by one rule, and they have opposite tolerances for
    # being wrong.
    #
    #   LEARNING   "what does this agent think is happening, and what should it try next"
    #              — narrow, finish, continue. Wrong costs a suggestion nobody had to take.
    #              Self-report is the right input: it is the only thing that knows intent.
    #
    #   CONTROL    "should this run go on at all" — stop, verify. Wrong costs a killed run
    #              that was about to work, or a runaway that should have been killed. The
    #              agent's own account is the worst possible input, because the agent is the
    #              subject of the decision.
    #
    # `verdict` above is the learning decision and is UNCHANGED — same rules, same
    # thresholds, same order, every existing caller reads exactly what it read before.
    # `control` is new and additive, and it is the one that may only read things the agent
    # cannot type its way out of.
    #
    # THE TEST FOR ADMISSION, applied to every input:
    #   can the agent silence this rule by typing different numbers, without doing
    #   different work?
    #
    #   here, max_checks    no  — the harness counts calls; nothing typed changes a count
    #   saw_any, corroborated
    #                       no  — tool outcomes, recorded by a hook from what actually ran
    #   prior_runs          no  — how many earlier SESSIONS opened this context
    #   goal_drifts,        no  — overlap against a ground frozen at first call. The theorem
    #   regrounds               is that the ground cannot be revised; that is what makes the
    #                           goal term the anchored half of Φ.
    #
    #   distance, closed,   YES — all of it is whatever was typed into `distance`, and every
    #   pace, now, flat,        one of them is barred here. This is the whole change: today
    #   stalls, repetition,     `abandon` requires closed <= 0, so an agent that types a
    #   ceiling                 falling number is never told to stop, however little it does.
    #                           repetition and ceiling are counted by the store but counted
    #                           over typed spellings, so they fail the test too.
    #
    # Two rules therefore drop a condition their `verdict` twins carry — `unbacked` loses
    # `closed > 0` and the recurrence arm of `abandon` loses `closed <= 0`. Both conditions
    # were self-report, and both had the same effect: they made the rule wait for the agent's
    # permission to fire. Control fires without it, which means control is STRICTLY LOUDER
    # than the matching verdict. That is intended and it is the measurable claim — where the
    # two disagree is precisely where self-report was carrying the decision.
    #
    # From Prime Intellect's harness, read 2026-08-06: `shouldAutonomouslyContinue` decides
    # on external quality gates and hard limits, and never once consults the model's opinion
    # of how it is doing. laserbrain had no such separation at all.
    def _control(self, here, prior_runs, goal_drifts, regrounds):
        """Continue-or-not, decided only on what the agent cannot author.

        decision is one of:

            stop      a count or a record says this should not go on — a spent budget, or a
                      context four sessions deep and finished in none. Safe to halt on.
            reground  the work may be fine; the GOAL has moved and nobody declared it.
                      reset_task to the goal you actually have, or hand it to a human.
                      Deliberately not `stop`: see the note on that branch — every
                      disagreement in the corpus came from here, and halting on them would
                      have killed twelve runs that were working.
            verify    work was observed and none of it corroborated the self-report.
            proceed   nothing the agent cannot author says otherwise.

        Returns {decision, because, observed, reads}. `observed` is the honest part: it is
        False when nothing has ever been recorded through saw(), and on that path control is
        running on the call count alone and says so instead of implying evidence it does not
        have. Most callers never call saw(), so most runs will read False — that is not a
        defect of this method, it is the measurement of how much of laserbrain has been
        resting on self-report, and it is now visible on every single call rather than
        inferable from nothing.
        """
        reads = {'checks': here, 'budget': self.cal.max_checks, 'observed_any': self.saw_any,
                 'corroborated': self.corroborated, 'prior_sessions': prior_runs,
                 'goal_drifts': goal_drifts, 'regrounds': regrounds}

        if self.cal.max_checks is not None and here >= self.cal.max_checks:
            d, why = 'stop', (f'{here} checks against a budget of {self.cal.max_checks}. A count, '
                              f'not an assessment.')
        elif prior_runs >= 3:
            # No `closed <= 0` here, unlike the verdict twin. Whether THIS run believes it is
            # closing distance is not evidence about a context that four sessions have opened
            # and none have finished.
            d, why = 'stop', (f'This context has been opened in {prior_runs} earlier sessions and '
                              f"finished in none. The current run's own account of itself was "
                              f'not consulted.')
        elif goal_drifts >= 3 and goal_drifts > regrounds:
            # `reground`, NOT `stop`, and the corpus is what changed my mind.
            #
            # Replaying 231 runs through both decisions (lasermind/control_vs_verdict.py),
            # EVERY ONE of the 134 rows where control was louder than the verdict came from
            # this arm — the recurrence arm produced none. So this arm is, empirically, the
            # whole of control's extra reach, and it was reporting itself with the same word
            # as a spent budget.
            #
            # That is not a wording nit, it is a correctness problem. Control exists to be
            # acted on mechanically; a caller wiring `if decision == 'stop': halt()` would
            # have killed all twelve of those runs, and reading them they were working —
            # fixing mutate.sh, regenerating a stale fixture, shipping a registry pin. What
            # was wrong with them was never that the work was worthless. It was that the
            # goal kept moving and nobody said so: the heaviest, run 6718dbcd, ran 40 steps
            # under 37 distinct goals.
            #
            # The right response to that is to re-establish the ground — reset_task to the
            # goal you actually have now, or hand it to a human — which is a different act
            # from stopping. The word is the one the grammar already uses for it.
            d, why = 'reground', (
                f'The goal failed its overlap check {goal_drifts} times against {regrounds} '
                f'declared re-grounds, measured against the frozen ground. This is not a '
                f'judgement that the work is worthless — it is that nobody has said what the '
                f'work now is.')
        elif self.saw_any and self.corroborated == 0 and here >= 5:
            # Also no `closed > 0`. The verdict twin waits for the agent to CLAIM progress
            # before objecting that nothing backs it; the objection stands either way.
            d, why = 'verify', (f'{here} checks, work was observed, and not one check was '
                                f'corroborated by it.')
        elif not self.saw_any:
            d, why = 'proceed', (f'{here} checks and no reason to stop — but nothing has been '
                                 f'recorded through saw(), so this read the count and nothing '
                                 f'else. Treat it as the absence of a signal, not as an all-clear.')
        else:
            d, why = 'proceed', (f'{here} checks, {self.corroborated} corroborated by observed '
                                 f'work. No count or record says stop.')
        return {'decision': d, 'because': why, 'observed': bool(self.saw_any), 'reads': reads}

    def _anchor(self):
        """What fraction of Φ's weight is anchored outside the agent's self-report.

        The goal term is always anchored: the ground is frozen at first call and cannot be
        revised, which is the whole content of the theorem. The distance and progress terms
        are not — they are whatever the agent typed. On the published calibration that is
        0.5 external and 0.5 introspection, and until now nothing said so.

        Corroboration means: at least one thing was OBSERVED to happen since the last
        check, and nothing observed failed outright. An agent reporting `advancing` with a
        falling distance and no successful work behind it is making a claim with nothing
        under it — that is `unrun` from catches.py, applied to the harness's own inputs.

        Deliberately NOT folded into Φ. Reweighting would move the published instrument,
        invalidate every calibration and every drift vector, and I would be inventing a
        weight with no data behind it. Reporting it is the honest thing available today.
        """
        self.checks += 1
        ev = self.evidence
        self.evidence = []
        if not ev:
            # NOTHING WAS HANDED IN — so ask the runtime instead of assuming the worst.
            #
            # `saw()` shipped opt-in and was called by almost nothing, which did not merely
            # leave a feature unused: it left `anchored` returning 0.5 for its entire life,
            # unnoticed, because nothing depended on it enough to look. The default was the
            # bug. runtime.Session has known every tool call and its outcome the whole time
            # and simply had no wire to here.
            #
            # AN ADVANCE, NOT A TOTAL. A counter left over from other work on this machine
            # must not lend credibility to a run doing nothing, so what counts is movement
            # between this check and the last. Same rule as evidenceAdvanced() on the
            # server, and the same shared file — one observed channel per machine, not two
            # that disagree.
            return self._anchor_from_runtime()
        ok = [e for e in ev if getattr(e, 'ok', None) is not False]
        if not ok:
            self._backed.append(False)
            return round(self.cal.w_goal, 2)
        self.corroborated += 1
        self._backed.append(True)
        return 1.0

    def _anchor_from_runtime(self):
        """The observed channel when the caller never called saw(). Fails open to 0.5."""
        try:
            ok, fail = _evidence.count()
        except Exception:
            ok = fail = 0
        # LIVE FOR THIS RUN, not merely present on this machine. The counter is shared — the
        # server's hook fills the same file — so a count that was already there when this run
        # began says nothing about this run. Treating it as instrumentation is how the first
        # version of this broke the rule the harness is built on: uninstrumented is not the
        # same as unbacked, and an instrument that cannot tell them apart must say nothing.
        # Caught by test_unbacked, which exists for precisely that sentence: an ordinary
        # Harness with no runtime attached was being handed `unbacked` because some earlier
        # process had written to the file it reads.
        #
        # So corroboration must ARRIVE DURING the run. _ev_start is frozen at construction
        # and never moves; _ev_mark rolls forward per check.
        if (ok + fail) <= self._ev_seen:          # dark: nothing observed since this began
            self._backed.append(False)
            return round(self.cal.w_goal, 2)
        # The channel is live, which is a different fact from "observed and unconvincing" —
        # `unbacked` and `control` both read saw_any to tell those apart.
        self.saw_any = True
        advanced = ok > self._ev_mark
        self._ev_mark = ok
        self._backed.append(bool(advanced))
        if not advanced:
            return round(self.cal.w_goal, 2)
        self.corroborated += 1
        return 1.0

    def saw(self, event):
        """Record one observed event for the interval up to the next check."""
        self.evidence.append(event)
        self.saw_any = True

    def step(self, goal, progress, distance, parent_goal=None, user_turn=False):
        prev = _isdrift(self.trace[-1][0]) if self.trace else False
        # Stays None until the state is known grammatical, a few lines below. emit() reads
        # it at call time, so the ungrammatical return below correctly carries no score --
        # there is nothing to write when the state cannot be spelled.
        score = None

        def emit(reason, drifting, advice, phi=0.0, why='', parent_overlap=None):
            # The trace records the READING; the cycle is a fact about the sequence, so the
            # original goes in and `oscillating` is what comes out. Storing the meta-verdict
            # instead would erase the pattern that produced it.
            self.trace.append((reason, drifting))
            self.trail.append('|'.join(sorted(norm(goal))) if goal else '')

            # Recorded here because emit is the single exit every verdict passes through —
            # putting it on the individual return paths is how the first version of the
            # user-turn fix came to sit in dead code, written into one branch of two.
            # Every step, not only the fires: a context whose history exists only for its
            # bad moments cannot answer "did this ever work".
            cid = context_id(goal)
            if cid:
                try:
                    _, rep = remember_context(cid, goal, distance, reason, self.run_id, score)
                    self.repetition = rep
                    self.context = cid
                except Exception:
                    pass

            # GROUND FIRST, then readings. x = [x, f(x)] — the ground is x and the verdicts
            # are f(x), and a cycle in x is the thing the verdict was built to name. Checking
            # the ground first means an agent that keeps returning to the same goals is
            # caught on that fact alone, instead of having to also produce a periodic
            # sequence of readings. The verdict pass is kept because a repeating READING
            # over a moving ground is a real pattern too — it just is not the same one.
            p = _cycle(self.trail)
            # THE READING FALLBACK IS RETIRED, 2026-08-04, on the corpus.
            #
            # It fired 16 times in 1,823 recorded readings and was wrong all 16. Not one
            # had a cycle in the GOALS: every window looked like A A A B — an agent working
            # one goal, then handed another — where only the sequence of verdicts happened
            # to repeat. That is the ordinary rhythm of a working session (grounded,
            # advancing, advancing, grounded, ...), so the arm fired on task switching and
            # on nothing else. Precision 0.00, and it cannot be tuned: the period it finds
            # is a property of how often a user speaks, not of the work.
            #
            # The GROUND arm stays and is the principled one. x = [x, f(x)] — the ground is
            # x, the verdicts are f(x), and a cycle in x is the thing this verdict was built
            # to name. It has produced no fires yet, which makes it untested rather than
            # disproven; an arm that has never cried wolf is not the one to remove.
            of = 'ground'
            if p and not self._osc:
                self._osc = True
                what = ('You have returned to the same goals in a repeating order'
                        if of == 'ground' else 'Your reading has cycled')
                osc = Verdict(True, 'oscillating', round(phi, 2),
                              f'{what} with period {p} — you have been told to return and have '
                              f'come back to the same place. Re-ground explicitly instead of '
                              f'returning again.', why or f'period-{p} {of} cycle', score,
                              self._anchor())
                osc.ground = getattr(self, 'first_goal_text', None)
                return osc
            if not p:
                self._osc = False
            v = Verdict(drifting, reason, round(phi, 2), advice, why, score, self._anchor(),
                        self._goal_score(goal), context_id(goal))
            # How well a DECLARED parent matched the ground, when one was declared and fell
            # short. Present only then — an absent field means no declaration was made,
            # which is different from one that was made and rejected, and the corpus needs
            # to tell those apart to ever settle what the right measure is.
            if parent_overlap is not None:
                v.parent_overlap = round(parent_overlap, 2)
            # Stamped here rather than on the individual return paths: emit() is the single
            # exit, and the file already records what happens otherwise — "putting it on the
            # individual return paths is how the first version of the user-turn fix came to
            # sit in dead code, written into one branch of two".
            v.ground = getattr(self, 'first_goal_text', None)
            return v

        goal = str(goal or '').strip()
        if not goal or progress not in _PROGRESS:
            bad = 'the goal is empty' if not goal else f'{progress!r} is not one of {sorted(_PROGRESS)}'
            return emit('ungrammatical', True,
                        'You cannot spell a clear goal and a valid progress. Return to ground.',
                        why=bad)
        d = None if distance is None else _asdist(distance)
        score = laserscore(goal, progress, d, parent_goal)
        if self.ground is None:
            self.ground = {'goal': goal, 'progress': progress, 'dist': d}
            self.first_goal = norm(goal)
            self.first_goal_text = goal
            self.dist_hist = [] if d is None else [d]
            self.ground_at = len(self.trace)
            return emit('grounded', False, 'Ground state set — continue, and check each step.',
                        why=f'ground is goal={goal!r}, progress={progress!r}, '
                            f'distance={"unknown" if d is None else d}')
        phi = _displacement(goal, progress, d, self.ground, self.sim, self.cal)
        tm = _terms(goal, progress, d, self.ground, self.sim, self.cal)
        parts = ', '.join(f'{k} {("unknown" if v is None else format(v, ".2f"))}' for k, v in tm.items())
        if progress in ('stuck', 'circling') and phi > self.cal.self_report_min:
            return emit(f'self-report:{progress}', prev,
                        f'You reported {progress} and have moved from ground. Return to your goal.' if prev
                        else f'You reported {progress}. If it holds next step, return to ground.', phi,
                        why=f'you said {progress!r} and Φ={phi:.2f} is above the '
                            f'{self.cal.self_report_min:.2f} self-report floor ({parts})')
        if self.sim:                       # pluggable grammar: has the goal's MEANING moved?
            anchor = _clamp01(self.sim(goal, self.first_goal_text))
        else:                              # frozen default: word overlap, unchanged
            g = norm(goal)
            anchor = (len(g & self.first_goal) / len(g | self.first_goal)) if (g or self.first_goal) else 0.0
        if anchor < self.cal.goal_min:
            # ── the user changed the subject ────────────────────────────────────────
            # This is the single highest-value rule in the instrument, and it was in the
            # MCP server and not here. The graded corpus (CLAIM.md, 35 fires) puts
            # goal-drift at 24 fires and 0 true catches — 69% of everything this
            # instrument has ever produced, with a precision of zero — and 22 of those 24
            # were the FIRST CHECK AFTER THE USER SPOKE. The rule was faithfully detecting
            # that the subject had changed. It had: someone changed it.
            #
            # A goal that was replaced was not drifted from, so this is not a softened
            # verdict, it is a different event. The caller has to say so, because a
            # library cannot see the conversation the way the server's hook can — hence an
            # explicit flag rather than a guess.
            if user_turn:
                self.ground = {'goal': goal, 'progress': progress, 'dist': d}
                self.first_goal = norm(goal)
                self.first_goal_text = goal
                self.dist_hist = [] if d is None else [d]
                # The setpoint moved, so the progress accumulator starts here. Everything
                # before this index belongs to a goal the user has replaced.
                self.ground_at = len(self.trace)
                return emit('reground', False,
                            'New instruction — ground reset to the goal you just stated.',
                            why=f'the goal moved (overlap {anchor:.2f}) on the first check '
                                f'after a user turn, so it was replaced, not drifted from')
            # ── quantized recursion: the excursion case ─────────────────────────────
            # This grammar is a discrete measurement grid. `distance` is 11 integers,
            # `progress` is 3 enum values, and `goal` is ONE slot. An agent inside a
            # legitimate sub-task holds two goals at once — the parent it still serves and
            # the branch it is on — and one slot forces it to spell a single one. It spells
            # the branch, overlap with ground collapses, and the QUANTIZATION ERROR is
            # reported as drift.
            #
            # The arithmetic was never wrong. Φ measured exactly what it was handed; the
            # loss happened before the measurement, writing a two-valued state into a
            # one-valued field. So the repair belongs to the grammar, not the detector.
            #
            # An agent that can say "this branch serves that parent" is measured against
            # whichever it declares live, and the result is an `excursion` — recorded and
            # counted, but not called drift.
            #
            # Strictly additive. parent_goal=None takes the identical path it always took,
            # so the frozen instrument stays frozen and the old corpus stays comparable.
            # Cleared on EVERY pass through this branch, before anything can set it.
            # Leaving it to the parent block meant a later bare call inherited the previous
            # step's rejection and reported parent_overlap on a call that declared nothing —
            # collapsing the one distinction this field exists to draw, that None means no
            # declaration was made and a number means one was made and rejected.
            self._rejected_parent = None
            if parent_goal and str(parent_goal).strip():
                if self.sim:
                    p_anchor = _clamp01(self.sim(parent_goal, self.first_goal_text))
                else:
                    p = norm(parent_goal)
                    p_anchor = ((len(p & self.first_goal) / len(p | self.first_goal))
                                if (p or self.first_goal) else 0.0)
                # A DECLARATION THAT FALLS SHORT MUST NOT VANISH.
                #
                # Below the floor this used to drop straight through to goal-drift, whose
                # advice then said "If this is a sub-task, pass parent_goal" — to an agent
                # that had just passed one. The declaration was received, measured,
                # rejected, and never mentioned. All three parents ever declared in the
                # corpus were rejected this way (overlaps 0.03, 0.04, 0.17 against a floor
                # of 0.30), which is the whole of why adoption sits at 0.2%: the field
                # appears not to work, and nothing says otherwise.
                #
                # The threshold is NOT changed here. Three rejected declarations cannot
                # choose a replacement measure — containment rescues one of them,
                # child-in-parent rescues a different one, neither rescues the third — and
                # moving a published calibration on three points is the mistake the corpus
                # exists to prevent. Making the rejection legible is what generates the
                # data to settle it.
                self._rejected_parent = None if p_anchor >= self.cal.goal_min else p_anchor
                if p_anchor >= self.cal.goal_min:
                    return emit('excursion', False,
                                f'On a sub-task (overlap {anchor:.2f}) that still serves your ground '
                                f'goal (parent overlap {p_anchor:.2f}). Not drift — but the parent is '
                                f'what you owe.', phi,
                                why=f'goal overlap {anchor:.2f} is below goal_min '
                                    f'{self.cal.goal_min:.2f}, but the declared parent overlaps '
                                    f'{p_anchor:.2f}, so this is a branch and not a departure')
            # Name the remedy, not just the fault. A goal legitimately stops matching ground
            # in three ways and the verdict used to describe none of them: the user
            # redirected you (reset), you are on a sub-task (parent_goal), or you really did
            # wander off (return). Only the third is drift. A verdict that names one cause
            # teaches the agent that cause is the only one.
            rej = getattr(self, '_rejected_parent', None)
            if rej is not None:
                # Name what happened to the declaration, and never tell an agent to do the
                # thing it just did.
                return emit('goal-drift', True,
                            f'Your goal no longer matches the one you started with (overlap '
                            f'{anchor:.2f}). You DID declare a parent, and it was measured at '
                            f'{rej:.2f} against your ground — below the {self.cal.goal_min:.2f} '
                            f'floor, so this reads as drift rather than an excursion. Either the '
                            f'parent is not the goal this serves, or it shares too little wording '
                            f'with it to be recognised. If the user redirected you, reset.', phi,
                            why=f'overlap with the first goal is {anchor:.2f} and the declared '
                                f'parent overlaps {rej:.2f}, both below goal_min '
                                f'{self.cal.goal_min:.2f}; first goal was {self.first_goal_text!r}',
                            parent_overlap=rej)
            return emit('goal-drift', True,
                        f'Your goal no longer matches the one you started with (overlap {anchor:.2f}). '
                        f'If the user redirected you, reset. If this is a sub-task, pass parent_goal. '
                        f'Otherwise return to the goal you started with.', phi,
                        why=f'overlap with the first goal is {anchor:.2f}, below goal_min '
                            f'{self.cal.goal_min:.2f}; first goal was {self.first_goal_text!r}')
        if d is None:
            # No distance, no stall detector: "distance stopped falling" is undefined when
            # there are no distances. Losing a detector is the honest cost of inference.
            return emit('advancing', False,
                        f'On track (Φ={phi:.2f}, distance unknown — Φ is a lower bound).', phi,
                        why=f'Φ={phi:.2f} from {parts}; no distance, so no stall detector')
        self.dist_hist.append(d)
        dh = self.dist_hist
        w = self.cal.stall_window
        if len(dh) > w and min(dh[-w:]) >= dh[-w - 1]:
            # A FLAT DISTANCE IS NOT A STALL WHEN THE WORLD IS RESPONDING.
            #
            # `stalled` read distance monotonicity and nothing else, which cannot tell three
            # different situations apart:
            #
            #   the run is genuinely stuck        distance flat, nothing happening
            #   the agent is EXECUTING a plan     distance flat by nature — carrying a box
            #                                     across a room does not reduce distance-to-
            #                                     done on any single step
            #   the GOAL MOVED                    distance rose through no fault of the agent
            #
            # Measured on ARC-AGI-3, 2026-08-05: across five agent runs `stalled` fired on 35
            # of 133 steps, and ALL 35 reached a state the run had never seen before. Not one
            # was a step where nothing was happening. Three agents independently wrote that
            # the fires were "purposeful walking rather than confusion", "pure execution
            # toward a target I'd already verified", "execution along a route I already
            # understood". The rule was right about the number and wrong about the run.
            #
            # So the observed channel gets a veto. `saw()` already records what actually
            # happened between checks and `_anchor` already decides per check whether the
            # report was backed — this reads that history rather than inventing a new signal.
            # If every check in the window was backed by observed events, the distance is flat
            # because the agent is doing the work, and saying "return" would be wrong.
            #
            # DELIBERATELY CONSERVATIVE: it requires the WHOLE window backed, not a majority.
            # A run with intermittent evidence still stalls. And with no evidence at all —
            # every agent that never calls saw() — the behaviour is exactly as before, so
            # nothing already calibrated moves.
            backed = self._backed[-w:] if len(self._backed) >= w else []
            if backed and all(backed):
                return emit('advancing', False,
                            f'Distance is flat, but every check in the window is backed by '
                            f'observed work — this reads as execution, not a stall. (Φ={phi:.2f})',
                            phi,
                            why=f'distance {dh[-1]} no better than {dh[-w - 1]} from {w} steps '
                                f'ago, but {w} of {w} recent checks were corroborated, so the '
                                f'flat distance is execution rather than a stall')
            return emit('stalled', prev,
                        "Distance stopped falling and you were already off ground — return." if prev
                        else "Distance isn't falling. If it holds, return.", phi,
                        why=f'distance {dh[-1]} is no better than {dh[-w - 1]} from {w} steps ago '
                            f'(recent: {dh[-w - 1:]})')
        return emit('advancing', False, f'On track (Φ={phi:.2f}). Continue.', phi,
                    why=f'Φ={phi:.2f} from {parts}')


def _post(api, key, path, body):
    try:
        import urllib.request
        r = urllib.request.Request(api + path, method='POST', data=json.dumps(body).encode(),
                                   headers={'authorization': f'Bearer {key}', 'content-type': 'application/json',
                                            'user-agent': 'laserbrain-sdk/0.2'})
        with urllib.request.urlopen(r, timeout=8) as resp:
            return json.load(resp)
    except Exception:
        return None


class _Mirror:
    """The API mirror, moved off the critical path.

    `check()` ended with a blocking POST to /v1/drift, commented "best-effort". It was not
    best-effort in any sense the caller could feel: profiling put 96% of check() inside
    urlopen, at ~135 ms against 869 us keyless — a 155x tax on the measurement, paid by
    every keyed check. A hung network would have paid the full 8-second timeout, so the
    instrument's worst case was the network's worst case.

    Mirroring is genuinely a side-effect: nothing in the verdict depends on it and the
    return value was discarded. So it belongs on a thread, and the only real requirements
    are the ones a naive `Thread(target=...)` per call would break:

    ORDER. One worker draining one queue, so the server sees the steps in the order they
    happened. A thread per post would race and scramble a run's history — worse than slow.

    BOUNDED. maxsize, and a full queue drops the OLDEST and counts it. A mirror that grows
    without limit while the network is down is a memory leak inside the thing that was
    supposed to cost nothing, and dropping the oldest keeps the most recent history — the
    part anyone is actually looking at.

    HONEST ON EXIT. Daemon thread, so it can never hang a process, plus an atexit drain
    with a short bound. Anything still queued after that is dropped and counted rather
    than waited on; `stats()` says so. Losing a mirrored row is acceptable, hanging
    somebody's script on exit is not.
    """

    def __init__(self, maxsize: int = 256, drain_seconds: float = 2.0):
        self._q = None
        self._thread = None
        self._maxsize = maxsize
        self._drain = drain_seconds
        self.sent = 0
        self.dropped = 0
        self.failed = 0

    def _ensure(self):
        if self._thread is not None:
            return
        import atexit
        import queue
        import threading
        self._q = queue.Queue(maxsize=self._maxsize)

        def worker():
            while True:
                item = self._q.get()
                if item is None:
                    self._q.task_done()
                    return
                try:
                    if _post(*item) is None:
                        self.failed += 1
                    else:
                        self.sent += 1
                except Exception:
                    self.failed += 1        # a mirror may never raise into the caller
                finally:
                    self._q.task_done()

        self._thread = threading.Thread(target=worker, name='laserbrain-mirror', daemon=True)
        self._thread.start()
        atexit.register(self.flush)

    def send(self, api, key, path, body) -> None:
        """Queue a mirror. Never blocks, never raises, never returns a verdict."""
        try:
            self._ensure()
            try:
                self._q.put_nowait((api, key, path, body))
            except Exception:                # Full
                try:
                    self._q.get_nowait()     # drop the OLDEST, keep the recent history
                    self._q.task_done()
                    self.dropped += 1
                    self._q.put_nowait((api, key, path, body))
                except Exception:
                    self.dropped += 1
        except Exception:
            self.dropped += 1

    def flush(self, seconds: float | None = None) -> bool:
        """Drain, bounded. True if everything went; False if anything was left behind."""
        if self._q is None:
            return True
        import time as _t
        deadline = _t.monotonic() + (self._drain if seconds is None else seconds)
        while _t.monotonic() < deadline:
            if self._q.unfinished_tasks == 0:
                return True
            _t.sleep(0.01)
        left = self._q.unfinished_tasks
        if left:
            self.dropped += left
        return left == 0

    def stats(self) -> dict:
        return {'sent': self.sent, 'failed': self.failed, 'dropped': self.dropped,
                'queued': 0 if self._q is None else self._q.qsize()}


#: One mirror for the process. Module-level so every Harness shares the single ordered
#: worker — a queue per instance would reintroduce exactly the race it exists to avoid.
MIRROR = _Mirror()


def _get(api, key, path):
    try:
        import urllib.request
        r = urllib.request.Request(api + path, headers={'authorization': f'Bearer {key}',
                                                        'user-agent': 'laserbrain-sdk/0.2'})
        with urllib.request.urlopen(r, timeout=8) as resp:
            return json.load(resp)
    except Exception:
        return None


class Harness:
    """Single-agent harness. Local + free; pass key= to also retain history via the API."""
    def __init__(self, key=None, run_id=None, api=API_DEFAULT, similarity=None, calibration=None):
        self.key, self.api = key, api
        self.run_id = run_id or 'run'
        # `similarity(a, b) -> 0..1` swaps the GRAMMAR (how "the same goal" is judged)
        # without touching the theorem. None = the frozen word-overlap instrument.
        self.similarity = similarity
        self.calibration = calibration or PUBLISHED
        self._run = _Run(similarity, self.calibration)
        self._audit = []             # append-only, hash-chained ledger (survives reset)
        # nested recursion: a recursion decomposes into a SET of recursions, and that
        # set is itself a recursion needing its own ground (PROOF §4's third adjective —
        # the reference must be defined at every depth the process nests to).
        self._parent = None
        self._root = self
        self._depth = 0
        self._children: list = []
        self._tree_log: list = []    # root only: every check anywhere in the tree
        self._root_dist: list = []   # root only: the root's own distance history
        self._since_progress = 0     # root only: steps anywhere since root distance fell

    def _record(self, goal, progress, distance, v):
        prev = self._audit[-1]['hash'] if self._audit else ''
        body = {'i': len(self._audit), 'run_id': self.run_id, 'goal': str(goal or ''),
                'progress': progress, 'distance': _asdist(distance),
                'reason': v.reason, 'drifting': v.drifting, 'phi': v.phi, 'prev': prev}
        body['hash'] = _link(prev, {k: body[k] for k in body if k != 'hash'})
        self._audit.append(body)
        # every step anywhere in the tree is a step the ROOT paid for.
        r = self._root
        r._tree_log.append({'depth': self._depth, 'run_id': self.run_id, 'goal': str(goal or ''),
                            'reason': v.reason, 'drifting': v.drifting, 'phi': v.phi})
        r._since_progress += 1
        if self is r:                                   # only the root's own distance counts as progress
            d = _asdist(distance)
            if not r._root_dist or d < min(r._root_dist):
                r._since_progress = 0
            r._root_dist.append(d)

    def saw(self, kind, name, ok=None, **kw):
        """Tell the harness what actually happened, so the self-report can be corroborated.

            hz.saw('tool', 'pytest', ok=True)
            hz.saw('edit', 'drift.ts', sites=1)
            v = hz.check(goal=..., progress='advancing', distance=3)
            v.anchored        # 1.0 — the report is backed by observed work
                              # 0.5 — only the frozen ground is; the rest is your word

        Half of Φ has always been the agent's own account of itself: `distance` and
        `progress` are simply typed in, and an agent that reports its distance falling
        keeps Φ low while doing nothing. This is the channel that lets that be checked
        rather than assumed. Events are the same shape catches.py uses, because it is the
        same question — what is this claim resting on.
        """
        from .catches import Event
        fields = set(Event.__dataclass_fields__)
        self._run.saw(Event(**{k: v for k, v in dict(kind=kind, name=name, ok=ok, **kw).items()
                               if k in fields}))
        return self

    def corroboration(self):
        """Across this run: what fraction of checks had their self-report backed.

        The number worth putting on a dashboard. A run at 0.0 is one where the instrument
        measured the agent's opinion of itself for every step it took.
        """
        r = self._run
        return round(r.corroborated / r.checks, 3) if r.checks else 0.0

    #: The most recent Verdict, or None if this harness has never been checked. None is
    #: a meaningful value and must not be read as "fine": it means no reading was taken.
    last = None

    def check(self, goal, progress='advancing', distance=5, tokens=None, overhead=False,
              inferred=False, parent_goal=None, user_turn=False,
              *, doing=None, next=None, blocked=None) -> Verdict:
        """`doing`, `next` and `blocked` are the grammar's CARRIED fields.

        grammar.json has declared all four carried fields since the beginning and this
        signature accepted exactly one of them (parent_goal). The hosted Worker's
        check_state accepts all three and reads none. So the fields were declared
        everywhere, accepted in one place, and read nowhere — spelled by agents into a
        slot that dropped them.

        They are not measured and do not touch Φ: they are free text, and Φ is defined
        over the three fields that can be spelled canonically. What they now feed is the
        ceiling marker, which reads whether this step was CLAIMED or REPORTED.
        """
        v = self._run.step(goal, progress, distance, parent_goal, user_turn)
        if inferred:
            # Marked so a spelled check and an inferred one are never averaged into one
            # number and reported as the same measurement.
            v = Verdict(v.drifting, v.reason, v.phi, v.advice + ' [inferred: Φ is a lower bound]')
        if doing or next or blocked:
            from .ceiling import mark as _mark
            v.claims = _mark(doing, next, blocked)
        self._record(goal, progress, distance, v)
        # Held so something OTHER than the caller can read the reading. Added 2026-07-29
        # for Operator(harness=…): the hands need to know whether the agent asking them to
        # act is currently on its ground, and an operator cannot call check() itself —
        # it has no goal, no progress and no distance, and inventing them would be the
        # operator marking its own homework.
        self.last = v
        if self.key:  # mirror to the API for retained history / alerts (best-effort)
            body = {'run_id': self.run_id, 'goal': goal, 'progress': progress, 'distance': distance}
            if tokens is not None:
                body['tokens'] = tokens
                body['overhead'] = overhead
            MIRROR.send(self.api, self.key, '/v1/drift', body)
        return v

    def audit(self) -> list:
        """The tamper-evident ledger of every check this harness ran. Verify it with
           laserbrain.verify_audit(chain) — offline, no key. Append-only across reset()."""
        return list(self._audit)

    def export_audit(self, path: str) -> str:
        """Write the audit chain to a JSON file a reviewer can independently verify."""
        with open(path, 'w') as f:
            json.dump(self._audit, f, indent=2)
        return path

    def report(self) -> str:
        """A human-readable summary of this harness's run: how far it displaced, where
           it drifted, and the Φ trajectory as a sparkline. Reads the ledger, no key."""
        a = self._audit
        if not a:
            return 'laserbrain · no checks yet'
        phis = [r['phi'] for r in a]
        peak = max(phis)
        drifts = sum(1 for r in a if r['drifting'])
        reasons: dict = {}
        for r in a:
            if r['drifting']:
                reasons[r['reason']] = reasons.get(r['reason'], 0) + 1
        tail = ('drifts: ' + ', '.join(f'{k}×{v}' for k, v in reasons.items())) if reasons else 'no drift — held to ground'
        return (f"laserbrain · {len(a)} steps · {drifts} drift(s)\n"
                f"  goal: {a[0].get('goal', '')!r}\n"
                f"  Φ  {_sparkline(phis, 0.0, max(peak, 0.15))}  peak {peak:.2f}\n"
                f"  {tail}")

    # ── nested recursion: a recursion as a set of recursions ───────────────────
    def sub(self, goal, distance=5) -> 'Harness':
        """Open a CHILD recursion for a subtask — its own ground, nested under this one.

           Each node runs the proven flat detector against its own goal, so a subtask
           is checked on its own terms. What a node cannot see is the tree: every agent
           can be perfectly on-track for its own sub-goal while the whole decomposition
           drifts from the root. That is the same blindness one level up, and it is why
           the set of recursions needs its own fixed reference — the root's ground.

               root = Harness(); root.check("build the parser", "advancing", 8)
               tok  = root.sub("write the tokenizer", distance=4)
               tok.check("write the tokenizer", "advancing", 2)
               root.tree_status()["stalled"]     # did the tree spin without the root closing?
        """
        if self._depth + 1 > MAX_DEPTH:
            # Unbounded nesting is itself a drift signal, and past here the tree can no
            # longer be read. Fail early and legibly rather than deep inside a traversal.
            raise ValueError(
                f'laserbrain: recursion depth {self._depth + 1} exceeds MAX_DEPTH={MAX_DEPTH}. '
                'An agent decomposing this deep has almost certainly lost its goal — which is '
                'the thing being watched for.')
        child = Harness(key=self.key, run_id=f'{self.run_id}/{len(self._children) + 1}', api=self.api,
                        similarity=self.similarity)   # children inherit the grammar
        child._parent, child._root, child._depth = self, self._root, self._depth + 1
        self._children.append(child)
        child.check(goal, 'advancing', distance)        # the child's ground is its sub-goal
        return child

    def tree_status(self) -> dict:
        """The recursion tree as one reading, from the root: how deep it nested, how many
           steps the whole set spent, and whether it spun without the ROOT getting closer.
           TREE_STALL is a modelling choice (6), stated rather than tuned."""
        r = self._root
        nodes, depth = r._count_nodes(), r._max_depth()
        # A tree can only be "spinning without the root closing" if the root has
        # reported its distance more than once. With a single root check there is no
        # evidence either way, and calling that stalled invents alarms on healthy books.
        root_checks = len(r._root_dist)
        return {'depth': depth, 'nodes': nodes, 'steps': len(r._tree_log),
                'since_progress': r._since_progress, 'root_checks': root_checks,
                'stalled': r._since_progress >= 6 and root_checks >= 2,
                'root_goal': r._audit[0]['goal'] if r._audit else None,
                'drifting_nodes': sum(1 for x in r._tree_log if x['drifting'])}

    def _walk(self) -> list:
        """Pre-order traversal, iterative on purpose: a recursive walk would cap the
           readable tree at Python's recursion limit and raise from the MONITOR."""
        out, stack = [], [self]
        while stack:
            n = stack.pop()
            out.append(n)
            stack.extend(reversed(n._children))
        return out

    def _count_nodes(self) -> int:
        return len(self._walk())

    def _max_depth(self) -> int:
        return max(n._depth for n in self._walk())

    def tree_report(self) -> str:
        """The whole recursion tree, indented — each node's goal, steps and drifts, with
           the tree-level verdict the individual nodes cannot see."""
        r, out = self._root, []
        for n in r._walk():
            steps = len(n._audit)
            drifts = sum(1 for x in n._audit if x['drifting'])
            goal = n._audit[0]['goal'] if n._audit else '(no ground)'
            flag = f'  ⚑ {drifts} drift(s)' if drifts else ''
            out.append(f"{'  ' * n._depth}{'└ ' if n._depth else ''}{goal!r} · {steps} steps{flag}")
        s = r.tree_status()
        verdict = (f"⚑ the TREE is spinning — {s['since_progress']} steps across the set "
                   f"since the root got closer" if s['stalled'] else
                   f"tree on track — root closing (last progress {s['since_progress']} steps ago)")
        return (f"laserbrain · recursion tree · depth {s['depth']} · {s['nodes']} recursions · "
                f"{s['steps']} steps\n" + '\n'.join(out) + f"\n  {verdict}")

    def escalate(self, verdict: Verdict, streak: int = None, detail: str = None) -> str:
        """Raise a persisting drift to the hosted human-in-the-loop queue (needs key).
           The local on_escalate hook is the general mechanism; this is the managed
           surface (a review queue + a decision a human makes on the dashboard).
           Returns the escalation id to poll with resolution(), or None offline."""
        if not self.key:
            return None
        body = {'run_id': self.run_id, 'reason': verdict.reason, 'advice': verdict.advice}
        if streak is not None:
            body['streak'] = streak
        if detail:
            body['detail'] = detail
        return (_post(self.api, self.key, '/v1/escalation', body) or {}).get('esc_id')

    def resolution(self, esc_id: str) -> dict:
        """Poll a hosted escalation for the human's decision. Returns
           {'decision': 'return'|'allow'|'stop', 'note': …} once decided, else None."""
        if not self.key or not esc_id:
            return None
        r = _get(self.api, self.key, f'/v1/escalation?id={esc_id}')
        if r and r.get('status') == 'decided':
            return {'decision': r.get('decision'), 'note': r.get('note')}
        return None

    def phronesis(self) -> dict:
        """Judgment on the work, beside the measurement of the state.

        `check` answers how far you are from ground. This answers whether the work is
        worth continuing, and says why — finish, continue, narrow, verify, wrong-problem
        or abandon, with the evidence it judged on. Mirrors the `phronesis` MCP tool; the
        two are one instrument with two front doors.
        """
        return self._run.phronesis()

    def reset(self) -> None:
        self._run = _Run(self.similarity, self.calibration)   # new task run; the audit ledger keeps accumulating

    def run(self, step, max_steps: int = 30, on_return=None, escalate_after: int = None, on_escalate=None) -> dict:
        """The act layer. `step(ctx)` -> dict(goal, progress, distance, tokens?, done?).
           On drift, on_return(verdict, ctx) fires and ctx['return'] = advice so your next
           step can steer back. If the drift *persists* for `escalate_after` steps without
           recovering, on_escalate(verdict, ctx) fires — the human-in-the-loop hook; if it
           returns a decision string, that overrides the auto-return (a human's call is
           injected instead). Returns the final ctx."""
        ctx = {'returns': 0, 'streak': 0}
        for _ in range(max_steps):
            s = step(ctx) or {}
            v = self.check(s.get('goal', ''), s.get('progress', 'advancing'), s.get('distance', 5), s.get('tokens'))
            ctx['verdict'] = v
            if v.drifting:
                ctx['returns'] += 1
                ctx['streak'] += 1
                ctx['return'] = v.advice        # the act: inject the return into the loop
                if on_return:
                    on_return(v, ctx)           # on_return is a notification hook, not the injection
                if escalate_after and ctx['streak'] >= escalate_after and not ctx.get('escalated'):
                    ctx['escalated'] = True      # a self-correcting return didn't take — get a human
                    decision = (on_escalate or (lambda v, c: None))(v, ctx)
                    if decision:                 # a human's decision overrides the auto-return
                        ctx['return'] = ctx['decision'] = decision
            else:
                ctx['streak'] = 0                # recovered — a fresh streak can escalate again
                ctx.pop('return', None)
                ctx.pop('escalated', None)
            if s.get('done') or _asdist(s.get('distance', 5)) == 0:
                break
        return ctx

    async def acheck(self, goal, progress='advancing', distance=5, tokens=None, overhead=False, inferred=False, parent_goal=None, user_turn=False) -> Verdict:
        """Async check for asyncio agent loops. The local check is instant; the
           optional API mirror is dispatched off the event loop, so it never blocks."""
        import asyncio
        v = self._run.step(goal, progress, distance, parent_goal)
        if inferred:
            # Marked so a spelled check and an inferred one are never averaged into one
            # number and reported as the same measurement.
            v = Verdict(v.drifting, v.reason, v.phi, v.advice + ' [inferred: Φ is a lower bound]')
        self._record(goal, progress, distance, v)
        if self.key:
            body = {'run_id': self.run_id, 'goal': goal, 'progress': progress, 'distance': distance}
            if tokens is not None:
                body['tokens'] = tokens
                body['overhead'] = overhead
            asyncio.get_event_loop().run_in_executor(None, _post, self.api, self.key, '/v1/drift', body)
        return v

    async def arun(self, step, max_steps: int = 30, on_return=None, escalate_after: int = None, on_escalate=None) -> dict:
        """The act layer for async agents: `step(ctx)` is awaited each iteration —
           same semantics as run(). on_return / on_escalate may be sync or async."""
        import asyncio

        async def _maybe(cb, *a):
            if cb is None:
                return None
            r = cb(*a)
            return await r if asyncio.iscoroutine(r) else r

        ctx = {'returns': 0, 'streak': 0}
        for _ in range(max_steps):
            s = await step(ctx) or {}
            v = await self.acheck(s.get('goal', ''), s.get('progress', 'advancing'), s.get('distance', 5), s.get('tokens'))
            ctx['verdict'] = v
            if v.drifting:
                ctx['returns'] += 1
                ctx['streak'] += 1
                ctx['return'] = v.advice
                await _maybe(on_return, v, ctx)
                if escalate_after and ctx['streak'] >= escalate_after and not ctx.get('escalated'):
                    ctx['escalated'] = True
                    decision = await _maybe(on_escalate, v, ctx)
                    if decision:
                        ctx['return'] = ctx['decision'] = decision
            else:
                ctx['streak'] = 0
                ctx.pop('return', None)
                ctx.pop('escalated', None)
            if s.get('done') or _asdist(s.get('distance', 5)) == 0:
                break
        return ctx


# ── multi-agent: dialogue + recursion teams (prototype extension) ──────────────
# Kept for callers that imported them; the live values now come from Calibration so a
# team and a single agent cannot disagree about what drift means.
_ECHO_MIN, _PROG_WIN, _GOAL_MIN = PUBLISHED.echo_min, PUBLISHED.dialogue_window, PUBLISHED.goal_min


class _Dialogue:
    """Multi-agent drift. Until v0.4.0 this held its OWN copy of the thresholds, so
    Harness(calibration=...) configured single agents and teams silently ignored it —
    two detectors disagreeing about the same word. One object now feeds both."""

    def __init__(self, goal, cal=None):
        self.goal = norm(goal)
        self.cal = cal or PUBLISHED
        self.dist_hist, self.echo_hist, self.turns = [], [], []

    def step(self, agent, position, distance, restated_goal=None):
        pos = norm(position)
        d = _asdist(distance)

        def emit(reason, drifting, advice, echo=0.0, self_echo=0.0):
            self.turns.append({'agent': agent, 'pos': pos, 'reason': reason, 'drifting': drifting})
            return {'reason': reason, 'drifting': drifting, 'echo': round(echo, 2),
                    'self_echo': round(self_echo, 2), 'dist': d, 'advice': advice}

        if self.goal and not self.turns and not restated_goal and not pos:
            pass
        if not self.goal:
            g = norm(restated_goal or position or '')
            if not g:
                return emit('ungrammatical', True, 'The first turn must spell the shared goal.')
            self.goal = g
            self.dist_hist, self.echo_hist = [d], [0.0]
            return emit('grounded', False, 'Shared goal set — the fixed reference for the group.')
        if not pos:
            return emit('ungrammatical', True, 'This agent cannot spell its position.')
        others = [set(t['pos']) for t in self.turns[-3:] if t['agent'] != agent]
        echo = max((_sim(pos, o) for o in others), default=0.0)
        # ADDITIVE ONLY — reported, never acted on. `echo` compares a speaker to the OTHERS,
        # which is the right question for a team: are these agents converging? It is silent
        # on a different and equally real one — is this speaker going in circles? With a
        # single speaker `others` is empty and echo is 0.00 forever, so echo-spiral cannot
        # fire in a two-party conversation. Building a chatbot on this hit it immediately.
        #
        # It would be easy to feed self_echo into the echo-spiral condition. That is
        # deliberately NOT done: it would change when a published verdict fires, and every
        # reading taken before this version would stop being comparable to every reading
        # after it. The corpus is the asset. A consumer who wants to act on self_echo can
        # threshold it themselves against cal.echo_min — the number is right here.
        mine = [set(t['pos']) for t in self.turns[-3:] if t['agent'] == agent]
        self_echo = max((_sim(pos, m) for m in mine), default=0.0)
        self.echo_hist.append(echo)
        mean_echo = sum(self.echo_hist[-3:]) / len(self.echo_hist[-3:])
        self.dist_hist.append(d)
        dh = self.dist_hist
        w = self.cal.dialogue_window
        stalled = len(dh) > w and dh[-1] >= dh[-1 - w]
        if restated_goal and _sim(norm(restated_goal), self.goal) < self.cal.goal_min:
            return emit('topic-drift', True, 'The dialogue has left the shared goal — return to it.', echo, self_echo)
        last = self.turns[-1]['reason'] if self.turns else None
        if stalled and mean_echo >= self.cal.echo_min:
            return emit('echo-spiral', last == 'echo-spiral', 'The agents agree while the goal gets no closer — break the loop.', echo, self_echo)
        if stalled:
            return emit('deliberation-stall', last == 'deliberation-stall', 'No progress toward the shared goal — return to it.', echo, self_echo)
        return emit('advancing', False, f'On track — closing on the goal (dist {d}).', echo, self_echo)


_ALL_MODES = ['ungrammatical', 'topic-drift', 'echo-spiral', 'deliberation-stall', 'goal-drift', 'stalled', 'self-report:stuck', 'self-report:circling']
_DEPTH = {
    'deep': {'ungrammatical', 'topic-drift', 'goal-drift'},
    'balanced': {'ungrammatical', 'topic-drift', 'goal-drift', 'echo-spiral', 'self-report:stuck', 'self-report:circling'},
    'tight': set(_ALL_MODES),
}
PRESETS = {
    'deep-search': [
        {'role': 'explorer', 'recurse': 'deep'},
        {'role': 'checker', 'recurse': 'tight', 'return': 'Restate the goal and verify the last step against it.'},
    ],
    'iterative-refinement': [
        {'role': 'drafter', 'recurse': 'balanced'},
        {'role': 'critic', 'recurse': 'balanced', 'modes': ['echo-spiral', 'topic-drift', 'ungrammatical'], 'return': 'You are agreeing, not improving. Name one concrete flaw and change it.'},
    ],
    'adversarial-deliberation': [
        {'role': 'advocate-a', 'recurse': 'deep'},
        {'role': 'advocate-b', 'recurse': 'deep'},
        {'role': 'synthesizer', 'recurse': 'tight', 'return': 'The debate is looping. State the single decision that resolves the shared goal.'},
    ],
}


def _style_return(reason, role):
    if reason in ('advancing', 'grounded'):
        return False
    acts = set(role['modes']) if role.get('modes') else _DEPTH.get(role['recurse'], _DEPTH['balanced'])
    return reason in acts



# ── the public name ───────────────────────────────────────────────────────────
# `Team` runs a whole scripted team through `.run()`. There was no public way to drive a
# dialogue TURN BY TURN, which is the shape of the most ordinary conversation there is: one
# person and one agent. The first outside consumer — a chatbot built on this in August 2026
# — had to import `_Dialogue` and `_asdist` by their private names to do it.
#
# The object was always the right one; only its name said otherwise. `Dialogue` is that
# object, unchanged. The underscored name stays as an alias because `Team` and the test
# suite already use it, and renaming a working internal to make a point is how a release
# breaks something for no gain.
Dialogue = _Dialogue
asdist = _asdist    # 0-10 clamp; a consumer feeding Dialogue needs the same one


class Team:
    """Run a styled recursion team and close the loop — detect, then inject the return."""
    def __init__(self, preset, goal, key=None, api=API_DEFAULT, calibration=None):
        if isinstance(preset, str):
            if preset not in PRESETS:
                raise ValueError(f'unknown preset {preset!r}; choose {list(PRESETS)}')
            self.roles = PRESETS[preset]
            self.name = preset
        else:
            self.roles, self.name = list(preset), 'custom'
        self.goal, self.key, self.api = goal, key, api
        self.calibration = calibration or PUBLISHED
        self._dlg = _Dialogue(goal, self.calibration)

    def snapshot(self):
        """Serialize the team's shared ground + dialogue so a later session can resume
           it instead of starting cold — subjective continuity for a group. JSON-safe."""
        d = self._dlg
        return {'name': self.name, 'roles': self.roles, 'goal': self.goal,
                'dlg': {'goal': sorted(d.goal), 'dist_hist': list(d.dist_hist), 'echo_hist': list(d.echo_hist),
                        'turns': [{'agent': t['agent'], 'pos': sorted(t['pos']),
                                   'reason': t['reason'], 'drifting': t['drifting']} for t in d.turns]}}

    @classmethod
    def restore(cls, snap, key=None, api=API_DEFAULT):
        """Resume a team from snapshot(): the shared goal (the fixed reference) and the
           dialogue history carry over, so the group keeps watching the same ground."""
        t = cls(list(snap['roles']), snap['goal'], key=key, api=api)
        t.name = snap['name']
        d = t._dlg
        s = snap['dlg']
        d.goal = set(s['goal'])
        d.dist_hist, d.echo_hist = list(s['dist_hist']), list(s['echo_hist'])
        d.turns = [{'agent': x['agent'], 'pos': set(x['pos']), 'reason': x['reason'],
                    'drifting': x['drifting']} for x in s['turns']]
        return t

    def run(self, agent_fn, max_turns=12, on_return=None, verbose=True):
        """`agent_fn(role, history, injected) -> (position, distance)`. On a role's
           policy firing, its return advice is injected into the NEXT turn. Returns a
           transcript list of dicts."""
        transcript, injected = [], None
        for turn in range(max_turns):
            role = self.roles[turn % len(self.roles)]
            pos, dist = agent_fn(role, transcript, injected)
            injected = None
            r = self._dlg.step(role['role'], pos, dist)
            act = _style_return(r['reason'], role)
            rec = {'turn': turn, 'role': role['role'], 'recurse': role['recurse'],
                   'reason': r['reason'], 'echo': r['echo'], 'dist': r['dist'], 'return': act}
            transcript.append(rec)
            if verbose:
                print(f"  {role['role']:12}({role['recurse']:8}): {r['reason']:18} echo={r['echo']:<4} dist={r['dist']}" + ('  ↩ RETURN' if act else ''))
            if self.key:
                MIRROR.send(self.api, self.key, '/v1/dialogue',
                            {'conv_id': self.name, 'agent': role['role'], 'position': pos, 'distance': dist,
                             'team': self.name, 'role': role['role'], **({'goal': self.goal} if turn == 0 else {})})
            if act:
                injected = role.get('return', 'Return to the shared goal and take the step that most directly resolves it.')
                (on_return or (lambda a, c: None))(injected, rec)
            if _asdist(dist) == 0:
                if verbose:
                    print('  ✓ resolved.')
                break
        return transcript


# framework adapters (LangGraph, CrewAI, generic) — imported last to avoid a cycle
from .adapters import guard, langgraph_node, crewai_step_callback, middleware  # noqa: E402
__all__ += ['guard', 'langgraph_node', 'crewai_step_callback', 'middleware']

# ── the whole toolkit, on the public surface ──────────────────────────────────
# Everything below already existed in the package and none of it was importable from
# `laserbrain` — a user who pip-installed got the harness and the adapters, and had to
# know the submodule names to find the rest. 2026-07-27: if we use it, users get it.
#
# The field is bundled but NOT wired into Φ, and that separation is deliberate. The
# harness stays a pure function of goal, progress and distance, computable with every
# socket blocked. Bundling the field gives you the weather in the same install; it does
# not make the detector depend on a hub being up.
from .field import (                                            # noqa: E402
    read_field, speak_to_field, field_vocabulary, FieldGround, VOCABULARY,
)
from .vocab import embedding_similarity                          # noqa: E402
from .observe import Observer                                    # noqa: E402
# Six catches, not three. `unfalsified`, `instrument_blind` and `unrun` were built
# alongside residue/contaminated/stale_gate on 2026-07-27 and then left out of both the
# import and __all__ — so half of Bugfinder was public API and half was reachable only as
# laserbrain.catches.unfalsified, which nothing documents. Splitting a set of six down the
# middle is the kind of thing no test fails on: every name still resolves, the package
# still imports, and the only symptom is that three of them are invisible.
from .catches import (catches, Catch, Event, residue, contaminated,  # noqa: E402
                      stale_gate, unfalsified, instrument_blind, unrun)
__all__ += ['read_field', 'speak_to_field', 'field_vocabulary', 'FieldGround', 'VOCABULARY',
            'embedding_similarity', 'Observer', 'catches', 'Catch', 'Event', 'Calibration',
            'residue', 'contaminated', 'stale_gate',
            'unfalsified', 'instrument_blind', 'unrun']

# The check-in scheduler. Exported by NAME as well as by module, and the comment above about
# Bugfinder is exactly why: attention.py shipped reachable only as
# laserbrain.attention.risk, which nothing documents and nothing imports. Every name
# resolved, the package imported, the tests passed, and the module was invisible — the same
# shape as parent_goal being received and silently discarded, which held its adoption at
# 0.2% while looking implemented.
from . import attention                                          # noqa: E402
from .attention import risk, next_check_in, advise               # noqa: E402
__all__ += ['attention', 'risk', 'next_check_in', 'advise']

# ── 14 of 14 · every capability, one import ───────────────────────────────────
# The package carried 10 of the 14 things laserbrain can do; the other four were
# reachable only over MCP or only from a local file, so which subset you got depended
# on how you arrived. `link` was `tandem` and was described as two agents — the record
# format always had an `agent` field, so the limit was in the docs, not the data.
from .services import (                                          # noqa: E402
    analyze_language, compare_phrasings, ask_alice,
    remember_self, resume_self, forget_self, ServiceUnavailable, call as service_call,
)
from .link import (                                              # noqa: E402
    link_read, link_write, link_whoami, link_agents,
)
__all__ += ['analyze_language', 'compare_phrasings', 'ask_alice',
            'remember_self', 'resume_self', 'forget_self', 'ServiceUnavailable',
            'service_call', 'link_read', 'link_write', 'link_whoami', 'link_agents']

# ── supercode · an agent for agents ───────────────────────────────────────────
from .supercode import Supercode, AgentView                     # noqa: E402
__all__ += ['Supercode', 'AgentView']

# ── the second instrument · for work whose goal is supposed to move ───────────
from .explore import Search, Reading, trailscore                 # noqa: E402
__all__ += ['Search', 'Reading', 'trailscore']

# ── laserbrain AI · the harness as a decoder ──────────────────────────────────
from .write import Writer
from .reading import (CIRCLING_VARIETY, lexical_variety, read as read_text,  # noqa: F401
                      shape_of)
# nova last: it imports Harness and Supercode from here, so it must load after both.
from .nova import Nova, Skill                                     # noqa: E402                                        # noqa: E402
__all__ += ['fires_first', 'Writer', 'lexical_variety', 'shape_of', 'read_text', 'CIRCLING_VARIETY']
__all__ += ['Nova', 'Skill']

# ── the operator · the sixth layer, the only one that acts ────────────────────
# Last, and after nova: it is a skill nova holds, and supercode reaches it through a
# deferred import so the bar on routing does not make load order load-bearing.
from .operator import Operator, Act, Refused                      # noqa: E402
__all__ += ['Operator', 'Act', 'Refused']

# ── workflows · the ordered process, and the shelf it is kept on ──────────────
# After operator: a step that acts goes through the gate, so this imports it.
from .workflow import Workflow, Step, Store                       # noqa: E402
__all__ += ['Workflow', 'Step', 'Store']
