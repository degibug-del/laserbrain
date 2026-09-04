"""nova — the laserbrain agent.

    from laserbrain import Nova

    n = Nova(goal='ship the parser and the benchmark')
    n.learn('search', my_search_fn)
    n.run(act)                      # act(ctx) -> {goal, progress, distance, done?}

    n.use('supercode', observations=[...])   # the supervision skill, preloaded

WHAT NOVA IS, AND IS NOT
------------------------
nova is the thing that DOES work. Everything else in this package measures work, manages
it, records it or proves things about it — laserbrain is a reference, lasergear is
instructions, laserstore is the record. None of them act. nova is the actor, and it is the
only object here with agency.

It is a scaffold, not an intelligence. The thinking arrives as `act` — a callable that is
usually a model. What nova supplies is the loop, the skills, and the instrumentation: an
agent that wears the harness natively instead of being asked to remember it. Coverage on
hand-instrumented runs sits near 12%; an agent that cannot skip the check has coverage 1.

WHY IT DOES NOT GROUND ITSELF — AND WHAT THAT CLAIM IS WORTH
------------------------------------------------------------
No method here sets, moves or clears the ground. `Harness` freezes it at the first check
and nova offers no way to touch it. An agent that can revise the reference it is measured
against is measuring itself, which PROOF rules out and which every self-referential monitor
gets wrong the same way.

But the first version of this file said nova "holds no handle to it", and that was false.
`nova._hz._run.ground` is reachable and writable — the check behind the claim had been
`dir()` for method names containing "ground", which tests the vocabulary and not the
object. In Python nothing is truly private, so a barrier is not on offer.

What IS on offer is detection. The ground is fingerprinted at the first check and verified
whenever nova reports. Tampering does not raise — it is recorded, because a monitor that
crashes gets removed and a monitor that tells you gets read. `ground_intact()` answers it
directly, and `report()` says so in the open.

nova is measured BY laserbrain. It never measures itself. `self_check()` returns the
harness's verdict, unmodified — nova is not permitted to have an opinion about it.

SKILLS, AND WHY supercode IS ONE
--------------------------------
A skill is a capability nova can invoke. supercode is preloaded because supervising other
agents is a thing an agent DOES, not a thing an instrument is — it reads across agents,
finds collisions, and recommends who yields. nova calls it; nova is not it.

Every skill call is recorded as an Event. That matters beyond bookkeeping: the events feed
`catches`, so nova's claims can be checked against nova's actions by something that is not
nova.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _f

from . import Harness, _asdist, _canon
from hashlib import sha256 as _s256


def _sha(t):
    return _s256(t.encode()).hexdigest()[:16]

from .catches import Event, catches
from .supercode import Supercode

__all__ = ['Nova', 'Skill']


@dataclass
class Skill:
    """One capability, and the record of it having been used."""
    name: str
    fn: object
    calls: int = 0
    failures: int = 0
    events: list = _f(default_factory=list)
    #: Conditions that must hold before this skill can run, and what holds after it does.
    #: Empty by default, which means "runnable any time, changes nothing a planner can see"
    #: — the behaviour every skill had before planning existed.
    needs: frozenset = frozenset()
    gives: frozenset = frozenset()
    #: Times this skill ran without producing what `gives` claims. Not the same as `failures`,
    #: which counts raising. A skill that returns cleanly and delivers nothing is the harder
    #: case and the one a plan cannot survive.
    broken: int = 0


@dataclass(frozen=True)
class Plan:
    """A sequence of skills, and the search that found it — or did not.

    `steps` is None when nothing reaches the goal. `why` then says what was missing, because
    a planner that answers "no" without saying which condition was unreachable has told you
    the least useful true thing it knows.
    """
    steps: tuple | None
    #: Every skill considered at every depth, with whether it applied and why not. The audit
    #: record — the same shape the Logic Engine's `considered` has, for the same reason.
    considered: tuple
    expansions: int
    why: str | None

    def __bool__(self) -> bool:
        return self.steps is not None


class Nova:
    """The agent. Does work, holds skills, is measured — never measures itself."""

    def __init__(self, goal: str, calibration=None, key: str | None = None):
        if not goal or not str(goal).strip():
            raise ValueError('nova needs a goal — the ground is set from it and frozen')
        self.goal = str(goal).strip()
        # The harness is nova's, but the GROUND inside it is not nova's to touch. There is
        # no accessor for it here on purpose.
        self._hz = Harness(key=key, calibration=calibration) if key else Harness(calibration=calibration)
        self.skills: dict[str, Skill] = {}
        self.events: list[Event] = []
        self.steps = 0
        self.returns = 0
        # The last verdict, held so self_check() can report without taking a
        # new reading. None until the first real step.
        self._last = None
        # Fingerprint of the ground, taken at the first check. Prevention is impossible in
        # Python; evidence is not.
        self._ground_fp = None
        # Set by teach(). None means nova cannot choose and decide() says so.
        self._rules = None
        # supercode is preloaded because supervision is something an agent does. It is a
        # skill nova calls, not a thing nova is.
        self.learn('supercode', self._supercode)

    # ── planning ────────────────────────────────────────────────────────────────
    def plan(self, want, have=(), max_depth: int = 12):
        """Find a sequence of skills that makes `want` true, starting from `have`.

        THE DIFFERENCE BETWEEN THIS AND decide(). decide() maps a context to ONE skill by a
        rule somebody wrote — a reflex. This constructs a sequence nobody wrote, by searching
        over what the skills say they need and give. It is the first thing in nova that
        produces behaviour which was not enumerated in advance.

            nv.learn('run_tests', f, needs={'tests'},      gives={'tests_pass'})
            nv.learn('build',     f, needs={'tests_pass'}, gives={'wheel'})
            nv.plan(want={'wheel'})        ->  ['write_tests', 'run_tests', 'build']

        BREADTH-FIRST, so the plan is the SHORTEST one and the search is deterministic.
        Skills are tried in registration order, states are visited once, and the same request
        returns the same plan every time. A planner that searched greedily would be faster and
        would make the audit record a story about one path rather than a proof about all
        shorter ones.

        Returns a Plan. `Plan.steps` is None when no sequence exists, and `Plan.why` then
        names the conditions that no skill produces — which is the planning form of "why did
        you NOT do X", and the same question the Logic Engine answers for classification. An
        unreachable goal is usually a missing skill, and saying which condition was never
        produced points straight at it.
        """
        want, have = frozenset(want), frozenset(have)
        # Answered before searching: a condition no skill can ever produce makes the goal
        # unreachable from any state, and reporting that beats exhausting the space to
        # discover it. This is the cheap half of `why`.
        trusted = [sk for sk in self.skills.values() if not sk.broken]
        producible = frozenset().union(*(sk.gives for sk in trusted)) if trusted else frozenset()
        impossible = want - have - producible
        if impossible:
            # NAMES THE DISTRUST when that is the reason. "no skill produces: wheel" is true
            # and misleading if a skill produces it and is no longer believed — the fix is a
            # working build, not a new skill, and the message has to point at the right one.
            lost = {c for c in impossible
                    for sk in self.skills.values() if sk.broken and c in sk.gives}
            why = f'no skill produces: {", ".join(sorted(impossible))}'
            if lost:
                names = sorted(sk.name for sk in self.skills.values()
                               if sk.broken and sk.gives & lost)
                why += (f' — {", ".join(names)} would, and is no longer trusted after '
                        f'breaking its promise')
            return Plan(None, tuple(), 0, why)

        from collections import deque
        start = have
        seen = {start}
        q = deque([(start, ())])
        expanded = []
        while q:
            state, path = q.popleft()
            if want <= state:
                return Plan(path, tuple(expanded), len(expanded), None)
            if len(path) >= max_depth:
                continue
            for name, sk in self.skills.items():       # registration order — determinism
                if sk.broken:
                    # NOT TRUSTED TO DELIVER. Planning through a skill that has already
                    # promised and not delivered is how pursue() looped three times on one
                    # lie. This is the whole of nova's learning: one observation, remembered,
                    # changing what it will plan.
                    expanded.append((name, len(path),
                                     f'excluded: broke its promise {sk.broken}x'))
                    continue
                if not sk.needs <= state:
                    expanded.append((name, len(path), f'needs {", ".join(sorted(sk.needs - state))}'))
                    continue
                nxt = state | sk.gives
                if nxt in seen:
                    expanded.append((name, len(path), 'reaches a state already seen'))
                    continue
                seen.add(nxt)
                expanded.append((name, len(path), 'applied'))
                q.append((nxt, path + (name,)))
        # THE EXHAUSTION MESSAGE HAS TO NAME THE DISTRUST TOO. The cheap check above only
        # sees conditions in `want`; a skill excluded for breaking its promise usually
        # produces an INTERMEDIATE one — `wheel` on the way to `published` — so the search
        # runs and fails, and "never reached: published" points at the wrong thing. The fix
        # is a working build, not a new publish step.
        excluded = sorted({sk.name for sk in self.skills.values() if sk.broken})
        why = (f'searched {len(seen)} states to depth {max_depth} and never reached: '
               f'{", ".join(sorted(want - start))}')
        if excluded:
            why += (f' — with {", ".join(excluded)} excluded for breaking a promise'
                    f' (nova.trust(name) to believe it again)')
        return Plan(None, tuple(expanded), len(expanded), why)

    def pursue(self, want, have=(), sense=None, max_replans: int = 3, on_return=None):
        """Plan, run the steps, and re-plan when the world disagrees with the plan.

        plan() says what SHOULD work. This finds out. A skill declares `gives`, and a
        declaration is a promise about the world that the world is free to break: the build
        succeeds and produces no wheel, the publish returns 200 and nothing appears.

        SENSE IS THE DIFFERENCE BETWEEN BELIEVING AND CHECKING. Pass `sense()` returning the
        set of conditions currently true and nova compares what it predicted against what is
        there. Pass nothing and it carries on from what the skills promised, which is a
        legitimate mode and a weaker one — so the result says which it was, per step, rather
        than presenting both as knowledge. That distinction is the same one `anchored`
        returning 0.5 forever got wrong: a value nobody measured, reported on the same scale
        as one that was.

        Every step is checked by laserbrain, and the check is not optional here either.

        Returns a dict: done, state, taken, plans, divergences, why.
        """
        state = frozenset(sense() if sense else have)
        want = frozenset(want)
        taken, plans, divergences = [], [], []
        for _ in range(max_replans + 1):
            p = self.plan(want, state)
            plans.append(p)
            if not p:
                return {'done': False, 'state': state, 'taken': tuple(taken),
                        'plans': tuple(plans), 'divergences': tuple(divergences),
                        'why': p.why}
            for name in p.steps:
                sk = self.skills[name]
                try:
                    self.use(name)
                except Exception as e:
                    divergences.append({'step': name, 'kind': 'raised',
                                        'detail': f'{type(e).__name__}: {e}'})
                    break
                self.steps += 1
                v = self._hz.check(goal=self.goal, progress='advancing',
                                   distance=max(0, len(want - state)))
                self._last = v
                if self._ground_fp is None:
                    self._ground_fp = self._fingerprint()
                if v.drifting:
                    self.returns += 1
                    if on_return:
                        on_return(v, {'step': name, 'state': state})
                predicted = state | sk.gives
                if sense is None:
                    # ASSUMED, and recorded as such. The plan continues on the skill's word.
                    taken.append({'skill': name, 'state': 'assumed'})
                    state = predicted
                    continue
                observed = frozenset(sense())
                taken.append({'skill': name, 'state': 'observed'})
                if observed != predicted:
                    # THE INTERESTING CASE. The declaration and the world disagree, and the
                    # gap is named both ways: what was promised and did not appear, and what
                    # appeared and was not promised. Both are defects in the declaration.
                    if predicted - observed:
                        # Only a MISSING promise breaks trust. Unexpected extras mean the
                        # declaration is incomplete, which is worth reporting and is not a
                        # reason to stop believing the skill does what it says.
                        sk.broken += 1
                    divergences.append({
                        'step': name, 'kind': 'diverged',
                        'promised_missing': tuple(sorted(predicted - observed)),
                        'unexpected': tuple(sorted(observed - predicted)),
                    })
                    state = observed
                    break
                state = observed
            if want <= state:
                return {'done': True, 'state': state, 'taken': tuple(taken),
                        'plans': tuple(plans), 'divergences': tuple(divergences), 'why': None}
        return {'done': False, 'state': state, 'taken': tuple(taken),
                'plans': tuple(plans), 'divergences': tuple(divergences),
                'why': f're-planned {max_replans} times and never reached: '
                       f'{", ".join(sorted(want - state))}'}

    def trust(self, name: str) -> 'Nova':
        """Believe a skill again after it broke a promise.

        nova cannot tell a transient failure from a permanent one — the same reason run()
        does not retry a failing act. So distrust is recorded and never expires, and undoing
        it is a decision somebody makes rather than a timer. `report()` shows which skills
        are distrusted so the decision has something to stand on.
        """
        if name not in self.skills:
            raise KeyError(f'nova has no skill {name!r}')
        self.skills[name].broken = 0
        return self

    # ── choosing ────────────────────────────────────────────────────────────────
    def teach(self, ruleset) -> 'Nova':
        """Give nova rules for choosing a skill. Rule names ARE skill names.

        That identity is the design. A ruleset for choosing is not a separate vocabulary
        mapped onto skills — the category a context falls into IS the skill to run, so
        there is nothing to keep in sync.

        REFUSES UP FRONT if a rule names a skill nova does not have, the same reason
        follow(strict=True) does: discovering that the rule which fired names nothing at
        step four, after steps one to three have run, is the expensive way to find out.
        """
        from .rules import Ruleset
        if not isinstance(ruleset, Ruleset):
            raise TypeError('teach() takes a laserbrain.rules.Ruleset')
        unknown = [r.name for r in ruleset.rules if r.name not in self.skills]
        if unknown:
            raise ValueError(
                f'rules name skills nova does not have: {", ".join(sorted(unknown))} — '
                f'known: {sorted(self.skills)}')
        self._rules = ruleset
        return self

    def decide(self, ctx: dict | None = None):
        """Choose the next skill from the context. Returns the laserbrain Verdict.

        THIS IS THE ORGAN THAT WAS MISSING. nova could hold skills, run one by name and
        follow a stored method. It could not choose, and choosing was `act` — external and
        "usually a model". With a ruleset it chooses deterministically, and `.considered`
        carries why every skill was not chosen, which is the thing a model cannot supply.

        Returns a Verdict whose `category` is the skill name, or None when nothing cleared
        the threshold. None is a real answer: no rule matched this context, and inventing a
        choice there would be the guess this whole engine exists to avoid.
        """
        from .rules import classify
        if getattr(self, '_rules', None) is None:
            raise RuntimeError('nova has no rules — call teach(ruleset) first')
        return classify(self._describe(ctx or {}), self._rules)

    def _describe(self, ctx: dict) -> str:
        """The context as text for the matcher to read.

        THE GOAL IS DELIBERATELY NOT IN HERE, and the first version had it. Caught by running
        it rather than reading it: with goal='ship the parser and the benchmark', rules cued
        on `parser` and `benchmark` fired on EVERY step including the first, before anything
        had happened, and tied at margin 0. The goal is constant for the life of the run, so
        including it can only add a fixed bias to every decision. A chooser whose input does
        not change is not choosing.

        What goes in is what VARIES:

            observation   the caller's report of what is true now. The only channel for the
                          world, because nova cannot see it — a skill returning a string is
                          the caller's to pass on.
            return        the harness's advice when it says to come back. A rule can then
                          say "when told to return, reground".
            reason        the verdict's NAME, not its numbers. A keyword matcher cannot read
                          a float, and putting one here would be an unusable term in every
                          ruleset.
        """
        v = ctx.get('verdict') or self._last
        parts = [str(ctx.get('observation') or ''), str(ctx.get('return') or '')]
        if v is not None:
            parts.append(str(getattr(v, 'reason', '') or ''))
        return ' '.join(p for p in parts if p)

    # ── skills ──────────────────────────────────────────────────────────────────
    def learn(self, name: str, fn, replace: bool = False,
              needs=(), gives=()) -> 'Nova':
        """Register a capability. Returns self so registrations can chain.

        Replacing an existing skill has to be asked for. The first version overwrote
        silently, which means a second `learn('search', ...)` anywhere in a codebase
        quietly swaps what every later `use('search')` calls — and the call sites look
        identical either way. A skill that changes underneath its own name is the same
        failure as a version string that stops describing its content.
        """
        if not callable(fn):
            raise TypeError(f'skill {name!r} must be callable')
        if name in self.skills and not replace:
            raise ValueError(
                f'nova already has a skill named {name!r} with {self.skills[name].calls} '
                f'call(s) on it. Pass replace=True if you mean to swap it.')
        self.skills[name] = Skill(name, fn, needs=frozenset(needs), gives=frozenset(gives))
        return self

    def use(self, name: str, *a, **kw):
        """Invoke a skill, recording that it ran and whether it worked.

        The record is the point. A skill that is claimed and never called, or called and
        always green, is exactly what `catches` exists to notice — and it can only notice
        it because using a skill leaves a trace that nova did not author.
        """
        s = self.skills.get(name)
        if s is None:
            raise KeyError(f'nova has no skill {name!r} — known: {sorted(self.skills)}')
        s.calls += 1
        try:
            out = s.fn(*a, **kw)
            ev = Event(kind='tool', name=name, ok=True, result=out)
        except Exception as e:
            s.failures += 1
            ev = Event(kind='tool', name=name, ok=False, result=f'{type(e).__name__}: {e}')
            s.events.append(ev)
            self.events.append(ev)
            raise
        s.events.append(ev)
        self.events.append(ev)
        return out

    def _supercode(self, observations=None, goal: str | None = None):
        """The supervision skill: read across other agents and report."""
        sc = Supercode(goal) if goal else Supercode()
        for o in observations or []:
            sc.observe(agent=o.get('agent', 'agent'), goal=o.get('goal', ''),
                       progress=o.get('progress', 'advancing'), distance=o.get('distance'),
                       parent_goal=o.get('parent_goal'))
        return {'report': sc.report(), 'findings': sc.findings(),
                'collisions': sc.collisions(), 'route': sc.route(),
                'fleet_catches': sc.fleet_catches()}

    # ── the work ────────────────────────────────────────────────────────────────
    def run(self, act, max_steps: int = 30, on_return=None) -> dict:
        """Do the work. `act(ctx)` -> dict(goal, progress, distance, done?).

        The check is not optional and there is no flag to skip it. That is the difference
        between this and instrumenting an agent by hand: hand-instrumented coverage on real
        sessions runs around 12%, because remembering to call something every step is not
        an interface. Here the loop calls it, so coverage is 1 by construction.

        On drift the harness's own advice lands in ctx['return'] for the next act() to see.
        nova does not compose that advice and cannot suppress it.
        """
        ctx: dict = {'returns': 0, 'steps': 0}
        for _ in range(max_steps):
            # THE THINKING IS ALLOWED TO FAIL, and until 2026-09-01 it was not. `act` is
            # "usually a model" by this class's own description, so it calls a network, and a
            # network failure was killing the loop: the caller got an exception instead of a
            # ctx and lost every step that had already run. use() has recorded a failing skill
            # as an Event since it shipped; the act function — the one thing in nova most
            # likely to fail — was the only call site with no such record.
            #
            # RECORDED, THEN STOPPED, NOT RETRIED. nova cannot tell a transient failure from a
            # deterministic one, and retrying an act that raises on every call would burn
            # max_steps against the same exception. Stopping with the reason named is the
            # answer nova can stand behind.
            try:
                s = act(ctx) or {}
            except Exception as e:
                ev = Event(kind='act', name='act', ok=False,
                           result=f'{type(e).__name__}: {e}')
                self.events.append(ev)
                ctx['stopped'] = 'error'
                ctx['error'] = f'{type(e).__name__}: {e}'
                return ctx
            self.steps += 1
            ctx['steps'] = self.steps
            v = self._hz.check(goal=s.get('goal', self.goal),
                               progress=s.get('progress', 'advancing'),
                               distance=s.get('distance'))
            ctx['verdict'] = v
            self._last = v
            if self._ground_fp is None:
                self._ground_fp = self._fingerprint()
            if v.drifting:
                self.returns += 1
                ctx['returns'] = self.returns
                ctx['return'] = v.advice
                if on_return:
                    on_return(v, ctx)
            else:
                ctx.pop('return', None)
            if s.get('done') or _asdist(s.get('distance')) == 0:
                ctx['finished'] = True
                ctx['stopped'] = 'done'
                break
        else:
            # WHY A for/else. Running out of steps used to be reported by the ABSENCE of
            # `finished`, which is the same shape as read_field() returning None for a dead
            # hub and a quiet one alike — three different endings distinguished by what is
            # missing. `stopped` names which one it was, and `finished` is kept because
            # callers read it.
            ctx['stopped'] = 'max_steps'
        return ctx

    def compose(self, agents: dict, max_steps: int = 30, on_return=None,
                escalate_after: int | None = None, on_escalate=None) -> dict:
        """Run a fleet. nova acts as the manager; supercode is the skill it manages with.

        This is where capability stops coming from the size of any one mind. Two agents
        handed the same job are both perfectly grounded, both advancing, and both correct
        at every step — the duplication exists only as a relation, and no member of the
        fleet can see it however capable it is. A composed system sees it because it holds
        a view none of its parts hold.

        That is the whole of what "more than one agent" buys, stated without inflation:
        not better thinking, a different vantage. The thinking is still whatever `act` is.

        nova stays measured throughout. It runs the fleet under laserbrain's reference,
        never its own, and `compose` cannot set any member's ground — supercode may halt a
        duplicating agent and escalate to a person, and that is the end of its authority.
        Returns {name: ctx} plus nova's own record under '_nova'.
        """
        sc = Supercode(goal=self.goal)
        # Registered as a skill so the composition is on the record like any other use —
        # a manager whose supervision leaves no trace is unauditable by construction.
        ev = Event(kind='tool', name='compose', ok=True, result=f'{len(agents)} agent(s)')
        self.events.append(ev)

        ctxs = sc.manage(agents, max_steps=max_steps, on_return=on_return,
                         escalate_after=escalate_after, on_escalate=on_escalate)

        # nova reports on ITS OWN goal against ITS OWN ground while the fleet runs — the
        # manager is not exempt from the instrument it manages with.
        v = self._hz.check(goal=self.goal, progress='advancing',
                           distance=sum(1 for c in ctxs.values()
                                        if c.get('halted') or c.get('collision_unresolved')))
        self._last = v
        if self._ground_fp is None:
            self._ground_fp = self._fingerprint()

        ctxs['_nova'] = {
            'verdict': v,
            'collisions': sc.collisions(),
            'route': sc.route(),
            'fleet_catches': sc.fleet_catches(),
            'report': sc.report(),
            # The number that says whether composition bought anything: findings no
            # individual agent could have produced.
            'seen_only_from_above': len(sc.collisions()) + len(sc.fleet_catches()),
        }
        return ctxs

    # ── what can be asked of it ─────────────────────────────────────────────────
    def follow(self, workflow, operator=None, ctx: dict | None = None,
               strict: bool = True) -> dict:
        """Adopt a method and run it.

            w = Store().get('release')      # vended: steps, goals, no code
            nova.learn('test', run_tests).learn('build', build_wheel)
            nova.follow(w, operator=op)

        THIS IS THE SEAM the rest of the package was missing. A stored workflow says WHAT
        the steps are, in what order, and which of them cannot be taken back. It cannot say
        HOW, because a spec carries no code — that was the point of vending it. nova is what
        supplies the how: each unbound step binds to the skill of the same name.

        So a method travels between people while the doing stays local. Two agents can
        follow the same released method with completely different implementations, and both
        runs are measured against the same declared goals — which is what makes the two runs
        comparable at all.

        Binding goes through `use()`, so following a workflow leaves the same trace on nova
        as any other skill call, and `catches` can read it. A step with no matching skill
        stays unbound and raises when reached; with `strict` it raises up front instead,
        because discovering step four is missing after steps one to three have run is the
        expensive way to find out.
        """
        from .workflow import Workflow           # deferred: __init__ loads nova first
        if not isinstance(workflow, Workflow):
            raise TypeError('follow() takes a Workflow')

        bound, missing = [], []
        for s in workflow.steps:
            if s.bound:
                continue
            if s.name in self.skills:
                workflow.bind(s.name, lambda c, _n=s.name: self.use(_n, c))
                bound.append(s.name)
            else:
                missing.append(s.name)

        if missing and strict:
            raise KeyError(
                f'cannot follow this method: no skill for {missing}. '
                f'nova knows {sorted(self.skills)}. Teach it with learn(name, fn), or pass '
                'strict=False to run up to the first unbound step.')

        out = workflow.run(operator=operator, ctx=ctx)
        out['bound'] = bound
        out['unbound'] = missing
        # The workflow's readings are the workflow's; nova records that it followed one.
        ev = Event(kind='tool', name='follow', ok=bool(out.get('completed')),
                   result=f"{workflow.goal} — ran {len(out.get('ran') or [])} step(s)")
        self.events.append(ev)
        return out

    def _fingerprint(self):
        g = getattr(getattr(self._hz, '_run', None), 'ground', None)
        return None if g is None else _sha(_canon(g))

    def ground_intact(self) -> bool | None:
        """Is the ground still the one laserbrain froze? None before the first step.

        Not a guard — a witness. Anything that can reach `_hz._run.ground` can change it,
        so the honest offering is evidence that it happened rather than a promise it
        cannot.
        """
        if self._ground_fp is None:
            return None
        return self._fingerprint() == self._ground_fp

    def self_check(self):
        """The LAST verdict laserbrain gave, unmodified. Takes no new reading.

        The first version called check() here, and that was a real defect: six calls to
        self_check grew the trace from four entries to ten. Those synthetic readings feed
        the stall window and the cycle detector, so asking nova how it was doing could
        manufacture `stalled` or `oscillating` out of nothing but the asking. An observer
        that changes what it observes is not reporting, it is participating.

        So this reads the record and never writes to it. Returns None before the first
        real step, because there is genuinely nothing to report yet — which is a truthful
        answer and better than a reading invented to fill the slot.

        Named self_check and deliberately not self-assessment: nova returns what laserbrain
        said and is not permitted an opinion about it.
        """
        return self._last

    def catches(self):
        """What nova's own actions say about nova's claims, computed by something else."""
        return [{'signature': c.signature, 'detail': c.detail} for c in catches(self.events)]

    def report(self) -> str:
        v = self.self_check()
        lines = [f'nova · {self.steps} step(s) · {self.returns} return(s) · '
                 f'{len(self.skills)} skill(s)',
                 f'  ground: {self.goal}',
                 (f'  laserbrain says: {v.reason} Φ={v.phi:.2f} (anchored {v.anchored})'
                  if v else '  laserbrain says: nothing yet — no step has been taken')]
        for name, s in sorted(self.skills.items()):
            if s.calls:
                # BROKEN IS NOT FAILED. `failures` counts raising; `broken` counts running
                # cleanly and not producing what `gives` claims. The second is the one that
                # takes a skill out of planning, so a reader deciding whether to trust() it
                # again needs to see it here. The commit that added distrust said this line
                # existed. It did not, until now.
                mark = f', {s.broken} broken promise(s) — excluded from planning' if s.broken else ''
                lines.append(f'  {name}: {s.calls} call(s), {s.failures} failed{mark}')
        intact = self.ground_intact()
        if intact is False:
            lines.append('  GROUND TAMPERED — the reference was changed after it was frozen; '
                         'every reading since is measured against something nova chose')
        for c in self.catches():
            lines.append(f'  catch · {c["signature"]}: {c["detail"][:72]}')
        return '\n'.join(lines)
