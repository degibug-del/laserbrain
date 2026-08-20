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
        # supercode is preloaded because supervision is something an agent does. It is a
        # skill nova calls, not a thing nova is.
        self.learn('supercode', self._supercode)

    # ── skills ──────────────────────────────────────────────────────────────────
    def learn(self, name: str, fn, replace: bool = False) -> 'Nova':
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
        self.skills[name] = Skill(name, fn)
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
            s = act(ctx) or {}
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
                break
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
                lines.append(f'  {name}: {s.calls} call(s), {s.failures} failed')
        intact = self.ground_intact()
        if intact is False:
            lines.append('  GROUND TAMPERED — the reference was changed after it was frozen; '
                         'every reading since is measured against something nova chose')
        for c in self.catches():
            lines.append(f'  catch · {c["signature"]}: {c["detail"][:72]}')
        return '\n'.join(lines)
