"""workflow.py — an ordered process an agent runs, measured the whole way down.

WHAT WAS MISSING

laserbrain could already watch one agent on one goal (`Nova.run`) and N agents at once
(`compose`, `Supercode.manage`). It had nothing for the shape most actual work takes: an
ORDERED sequence of steps toward a single goal. That is not a third kind of loop, it is the
one shape where a specific failure lives — and the failure is the reason this file exists.

THE FAILURE IT CATCHES

A step that did something other than what the method declared it was for.

    goal: "ship the release"
      test    declared "the test suite passes"
              reported "the test suite passes"      ⟨pass|suite|test⟩ ⊂ ⟨releas|ship⟩   ok
      build   declared "build the release wheel"
              reported "refactoring the parser"     goal-drift, Φ 0.50                  caught

The step was declared FOR something, it reported doing something else, and the harness
scored the second against the first. That is a fact about this execution rather than an
inference — which matters, because the obvious-looking alternative does not work.

WHAT WAS TRIED FIRST, AND WHY IT WAS DROPPED

The first design compared each step's goal to the WORKFLOW's goal lexically, and reported
steps with little overlap as having wandered. The intended catch was four locally-green
steps that collectively abandoned the goal.

It cannot work, and no threshold rescues it. "the test suite passes" shares no words with
"ship the release" — and neither does "rewrite the documentation index". A legitimate step
and a wandering one are indistinguishable to word overlap, because a step SHOULD be phrased
differently from the goal it serves; restating the goal is what a step that does nothing
looks like. The first run flagged a healthy two-step release as wandering.

There is also a harder point underneath. If a workflow DECLARES a docs-rewrite step, that
step is the method — the author put it there. Nothing about the run is wrong; the method is.
Catching that is a question about a spec, not about an execution, and this file measures
executions.

HOW IT IS MEASURED

Each step gets its OWN harness, grounded on its DECLARED goal, and what the step reports is
scored against that. `parent_goal` carries the workflow's goal into every reading, so the
containment stays visible in the score:

    ⟨pass|suite|test⟩ advancing d1 ⊂ ⟨releas|ship⟩

One harness for the whole sequence does not work either, and that was also measured rather
than assumed: it grounds on step one, so a four-step release reads grounded · goal-drift ·
goal-drift · goal-drift, and the second step was "build the wheel". Per-step grounding is
the same resolution supercode uses for agents.


WHAT MAKES IT AGENT-NATIVE RATHER THAN A PIPELINE

1. A step declares a GOAL, not just a command. Something with no goal cannot be scored, and
   a step that cannot be scored is one the workflow cannot tell you about.
2. It halts on drift instead of running to the end and reporting. A process that keeps
   spending after it has left its goal is the exact thing the instrument is for.
3. Irreversible steps go through the Operator, so "deploy" and "run the tests" are not the
   same kind of thing. A pipeline treats them identically; the sixth layer does not.
4. The workflow is itself measured, so it can be asked whether IT drifted — the same
   discipline `Supercode.self_check()` applies to the supervisor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as _f
from pathlib import Path

from . import Harness
from .operator import Refused


def _unbound(name: str):
    """The placeholder for a step with no implementation.

    Raises rather than doing nothing. A workflow that quietly skipped its unbound steps
    would report a clean run of a process that never happened, which is the exact failure
    this package exists to catch, reproduced by its own convenience.
    """
    def step_fn(ctx, _n=name):
        raise NotImplementedError(
            f'step {_n!r} is unbound — bind it with .bind({_n!r}, fn) before running. '
            'A method carries the steps and their goals, not the code.')
    return step_fn


@dataclass
class Step:
    """One step: a name, a goal it is for, and how it must be treated if it acts."""

    name: str
    goal: str
    fn: object
    irreversible: bool = False
    outward: bool = False
    verdict: object = None
    ran: bool = False
    result: object = None
    # False only for a step rebuilt from a vended spec and not yet bound to code.
    bound: bool = True
    # Each step carries its OWN harness, grounded on the DECLARED goal. See run().
    harness: object = None
    # What the step said it was doing, when it reported a goal of its own.
    reported: str = ''


class Workflow:
    """An ordered process, grounded at the top and at every step.

        w = Workflow(goal='ship the release')
        w.step('test',    run_tests,  goal='the suite passes')
        w.step('build',   build_whl,  goal='a wheel exists')
        w.step('publish', upload,     goal='it is on PyPI', irreversible=True, outward=True)

        out = w.run(operator=op)     # op only needed if a step is irreversible
        w.wandered()                 # steps that did other than what they were declared for

    Step functions take the running context dict and return a dict shaped like the harness
    contract — `progress`, `distance`, optionally `goal` and `done`. A step that returns
    nothing is treated as having advanced, because a step that ran and said nothing is not
    evidence of drift; it is only evidence of a step that does not report.
    """

    def __init__(self, goal: str, calibration=None):
        if not goal or not str(goal).strip():
            raise ValueError('a workflow needs a goal — an ungrounded process cannot be '
                             'measured, and the whole point is the measurement')
        self.goal = goal
        self.steps: list[Step] = []
        self._cal = calibration
        # The workflow's own harness, for self_check only. Step verdicts never come from
        # here — see the note in run() about why a shared ground is the wrong instrument.
        self._hz = Harness(calibration=calibration)
        # From grammar.json, not a literal. goal_min is the threshold for "this agent has
        # left its own ground", which is exactly the question asked of one step.
        from . import _G
        self.phi_min = float((_G.get('calibration') or {}).get('goal_min', 0.30))

    def _departed(self, v) -> bool:
        """Whether one step reading counts as having left what it was declared for.

        NOT simply `v.drifting`. Two of the nine verdicts — `stalled` and `self-report` —
        warn before they interrupt, and escalating a warning needs history. Every step
        here gets a fresh harness, so it has none, and a warn can never become an
        interrupt however bad the reading is.

        Measured, not supposed: a step reporting `circling` at distance 9 comes back
        `self-report:circling` with **Φ=0.82 and drifting=False**. Halting on `drifting`
        alone would sail past the loudest signal the instrument can produce. Φ against
        goal_min is the reading that survives having no history behind it.
        """
        if v is None:
            return False
        if getattr(v, 'drifting', False):
            return True
        return float(getattr(v, 'phi', 0.0) or 0.0) >= self.phi_min

    def step(self, name: str, fn=None, goal: str | None = None,
             irreversible: bool = False, outward: bool = False) -> 'Workflow':
        """Add a step. Returns self so definitions can chain.

        `fn` is OPTIONAL, and that is the point of the whole file rather than a
        convenience. A stored method carries no code, so authoring one means writing down
        the steps and their goals with nothing behind them — and until this argument was
        made optional you could vend an unbound workflow but not write one, which is an
        asymmetry that only shows up the first time someone actually authors a method
        instead of testing the machinery. It showed up on the first real use.

        A step left unbound raises when reached, and `unbound()` lists them, so an
        unimplemented method fails loudly rather than reporting a clean run of a process
        that did not happen.
        """
        if fn is not None and not callable(fn):
            raise TypeError(f'step {name!r} must be callable, or None to leave it unbound')
        if any(s.name == name for s in self.steps):
            raise ValueError(f'step {name!r} is already defined — names are how steps are '
                             'reported, so duplicates make the report ambiguous')
        self.steps.append(Step(name=name, goal=goal or name, fn=fn or _unbound(name),
                               irreversible=irreversible, outward=outward,
                               bound=fn is not None))
        return self

    # ── running ────────────────────────────────────────────────────────────────────────
    def run(self, operator=None, ctx: dict | None = None, halt_on_drift: bool = True) -> dict:
        """Run the steps in order, checking each against its own goal AND the workflow's.

        Halts at the first drifting verdict unless `halt_on_drift=False`. Halting is the
        default because the alternative — finish everything, report at the end — is what a
        pipeline already does, and it means paying for every step after the one that left
        the goal.

        An irreversible step with no operator is refused rather than run. That is the
        layer's rule and it is not softened here just because a workflow is convenient.
        """
        ctx = dict(ctx or {})
        ran, halted_at, refused_at = [], None, None

        for s in self.steps:
            if s.irreversible or s.outward:
                if operator is None:
                    refused_at = s.name
                    break
                try:
                    out = operator.act(lambda: s.fn(ctx), kind='workflow-step',
                                       target=f'{self.goal} :: {s.name}',
                                       reversible=not s.irreversible, outward=s.outward)
                except Refused:
                    refused_at = s.name
                    break
            else:
                out = s.fn(ctx)

            s.ran, s.result = True, out
            ran.append(s.name)
            rep = out if isinstance(out, dict) else {}

            # EACH STEP GETS ITS OWN HARNESS, so its ground is its own goal.
            #
            # The first version shared one harness across the sequence, which grounds on
            # step one and then reports goal-drift for every honest step after it. Measured
            # rather than assumed: a four-step release read grounded · goal-drift ·
            # goal-drift · goal-drift, and the second step was "build the wheel". An
            # instrument that calls the normal shape of the thing it measures a spiral is
            # not strict, it is wrong.
            #
            # Same resolution supercode already uses: every agent gets its own harness, and
            # the cross-agent reading is a separate method. Here the step verdict says
            # whether the step did what it was DECLARED for, and wandered() collects them
            # to the workflow's. parent_goal keeps the containment visible in the score.
            # ...and it is GROUNDED ON THE DECLARED GOAL — what the method says this step
            # is for — before anything the step reports is scored against it. That makes
            # the step verdict mean something specific and checkable: did this step do the
            # thing it was declared to do.
            #
            # This replaced a lexical comparison between each step's goal and the
            # workflow's, which did not work and could not be made to work by tuning. "the
            # test suite passes" shares no words with "ship the release" — and neither does
            # "rewrite the documentation index". A legitimate step and a wandering one were
            # indistinguishable to it, because a step SHOULD be phrased differently from
            # the goal; restating the goal is what a step that does nothing looks like.
            #
            # Grounding on the declaration is the reading the vending story needs anyway:
            # a stored method says what each step is for, and a run is measured against
            # the method. That is a fact about this execution, not a guess about wording.
            s.harness = Harness(calibration=self._cal)
            s.harness.check(goal=s.goal, progress='advancing', parent_goal=self.goal)

            s.reported = str(rep.get('goal') or s.goal)
            s.verdict = s.harness.check(goal=s.reported,
                                        progress=rep.get('progress', 'advancing'),
                                        distance=rep.get('distance'),
                                        parent_goal=self.goal)
            if self._departed(s.verdict) and halt_on_drift:
                halted_at = s.name
                break
            if rep.get('done'):
                break

        return {
            'goal': self.goal,
            'ran': ran,
            'completed': halted_at is None and refused_at is None and len(ran) == len(self.steps),
            'halted_at': halted_at,
            'refused_at': refused_at,
            'wandered': self.wandered(),
            'ctx': ctx,
        }

    # ── reading ────────────────────────────────────────────────────────────────────────
    def wandered(self) -> list[dict]:
        """Steps that did something other than what the method declared them for.

        The reading that justifies the file, and it is a fact rather than an inference:
        the step was declared to be for X, it reported doing Y, and the harness scored Y
        against X. A task runner cannot produce this because it never knew what the step
        was FOR — only whether it exited zero.

        Run with `halt_on_drift=False` to see every one of them instead of stopping at the
        first, which is what you want when reading a finished run rather than guarding a
        live one.
        """
        out = []
        for s in self.steps:
            if s.ran and self._departed(s.verdict):
                out.append({'step': s.name,
                            'declared': s.goal,
                            'reported': s.reported,
                            'reason': getattr(s.verdict, 'reason', None),
                            'drifting': bool(getattr(s.verdict, 'drifting', False)),
                            'phi': getattr(s.verdict, 'phi', None),
                            'laserscore': getattr(s.verdict, 'laserscore', None)})
        return out

    def self_check(self):
        """The workflow's own verdict — the discipline supercode applies to itself."""
        done = sum(1 for s in self.steps if s.ran)
        return self._hz.check(goal=self.goal,
                              progress='advancing' if done else 'stuck',
                              distance=max(0, 10 - int(10 * done / max(1, len(self.steps)))))

    def report(self) -> str:
        lines = [f'workflow: {self.goal}']
        for s in self.steps:
            mark = '·' if not s.ran else ('!' if self._departed(s.verdict) else '+')
            far = '  ← departed' if s.ran and self._departed(s.verdict) else ''
            lines.append(f'  {mark} {s.name:<14} {getattr(s.verdict, "laserscore", "") or ""}{far}')
        return '\n'.join(lines)

    # ── checking a method before it is ever run ────────────────────────────────────────
    def lint(self) -> list[dict]:
        """Check this method against the grammar's dictionary. Reports; never overrides.

        A method is a design, and a design can be wrong before anything executes. The
        dictionary records, for each step verb, its DEFAULT position on the operator's two
        axes — so `publish` declared reversible is catchable while writing the method
        rather than while uploading.

        Findings, in the order they matter:

        `under-declared`  the verb is normally irreversible or outward and this step is not
                          marked so. The dangerous direction: at run time the Operator will
                          wave it through without asking anyone.
        `over-declared`   marked stricter than the verb's default. Harmless — it only asks
                          more often — and reported so the disagreement is visible, not
                          because it is wrong.
        `unknown-verb`    the leading word is not in the dictionary. Not an error; it is how
                          the dictionary learns it is incomplete. But two methods using
                          different words for one step cannot be compared, which is the
                          whole reason the vocabulary exists.
        `goal-restates-name`
                          the step's goal adds nothing to its name. A goal is what the step
                          is FOR, and a step whose goal restates its name cannot be scored
                          against anything — the harness would be comparing a phrase to
                          itself.

        Deliberately advisory. Only the author knows what a step actually does, so a linter
        that refused to store a method it disagreed with would be substituting a default for
        a fact.
        """
        from . import _G, norm
        table = ((_G.get('dictionary') or {}).get('steps') or {})
        out = []
        for s in self.steps:
            verb = re.split(r'[-_ ]', s.name.strip().lower())[0]
            spec = table.get(verb)

            if spec is None:
                out.append({'step': s.name, 'finding': 'unknown-verb', 'verb': verb,
                            'note': 'not in the dictionary — methods using different words '
                                    'for one step cannot be compared'})
            else:
                want_irrev = not spec['reversible']
                if want_irrev and not s.irreversible:
                    out.append({'step': s.name, 'finding': 'under-declared', 'verb': verb,
                                'note': f'{verb!r} is normally irreversible ({spec["gloss"]}) '
                                        'but this step is not declared so — the operator '
                                        'will not ask before running it'})
                if spec['outward'] and not s.outward:
                    out.append({'step': s.name, 'finding': 'under-declared', 'verb': verb,
                                'note': f'{verb!r} normally leaves this machine but this '
                                        'step is not declared outward'})
                if s.irreversible and not want_irrev:
                    out.append({'step': s.name, 'finding': 'over-declared', 'verb': verb,
                                'note': f'{verb!r} is normally reversible; this asks more '
                                        'often than the default, which is not a fault'})

            if norm(s.goal) == norm(s.name):
                out.append({'step': s.name, 'finding': 'goal-restates-name', 'verb': verb,
                            'note': 'the goal adds nothing to the name, so there is nothing '
                                    'for the step to be scored against'})

        out.extend(self._phase_findings())
        return out

    def phases(self) -> list[tuple]:
        """This method as a sequence of (step, phase). Unmapped verbs give phase None."""
        from . import _G
        of_verb = (((_G.get('dictionary') or {}).get('phases') or {}).get('of_verb') or {})
        seq = []
        for s in self.steps:
            verb = re.split(r'[-_ ]', s.name.strip().lower())[0]
            seq.append((s.name, of_verb.get(verb)))
        return seq

    def _phase_findings(self) -> list[dict]:
        """Check the method's SHAPE, not its individual steps.

        Every method eventually has the same backbone — change · verify · record · act ·
        confirm — and that was derived rather than designed: three methods written
        independently for unrelated jobs produced it. The ordering rules below are each a
        real failure from 2026-07-28/29, which is why they are rules:

        a commit and push went out on a red build (verify-before-record); 0.12.0 was
        published against a wheel built before the code existed (record/verify then act);
        a grammar sync was left uncommitted and a rewrite discarded it (change-is-recorded).

        Advisory, like the rest of lint. grammar-bump legitimately has no `act` at all, and
        a read-only method needs no `record` — the linter says what is missing and the
        author decides whether it matters.
        """
        from . import _G
        spec = ((_G.get('dictionary') or {}).get('phases') or {})
        if not spec:
            return []
        seq = [(n, p) for n, p in self.phases() if p]
        order = [p for _, p in seq]
        out = []

        def before(a, b):
            """Is there an `a` phase anywhere before the first `b`?"""
            if b not in order:
                return True
            return a in order[:order.index(b)]

        if 'record' in order and not before('verify', 'record'):
            out.append({'step': next(n for n, p in seq if p == 'record'),
                        'finding': 'verify-before-record', 'verb': None,
                        'note': 'nothing verifies this method before it records — a commit '
                                'on an unchecked change is how a red build reached the '
                                'remote'})
        if 'act' in order and not before('record', 'act'):
            out.append({'step': next(n for n, p in seq if p == 'act'),
                        'finding': 'record-before-act', 'verb': None,
                        'note': 'the irreversible step comes before anything is recorded, '
                                'so a bad outcome cannot be reproduced from source'})
        if 'act' in order:
            i = order.index('act')
            if 'verify' not in order[i + 1:]:
                out.append({'step': next(n for n, p in seq if p == 'act'),
                            'finding': 'confirm-after-act', 'verb': None,
                            'note': 'nothing confirms the irreversible step landed — an act '
                                    'nobody checked is an assumption'})
        # stale-verify: a change falling between the last verify and a record or act means
        # whatever that change produced is committed or shipped unchecked. grammar-bump
        # passes all four rules above — it has a verify, it has a record, the verify comes
        # first — and still syncs AFTER verifying, which is how two grammar copies were
        # recorded sitting at 1.7.0 while canonical was 1.9.0.
        if 'verify' in order:
            last_verify = len(order) - 1 - order[::-1].index('verify')
            for j in range(last_verify + 1, len(order)):
                if order[j] == 'change' and any(p in order[j + 1:] for p in ('record', 'act')):
                    out.append({'step': seq[j][0], 'finding': 'stale-verify', 'verb': None,
                                'note': 'this change happens after the last verify and '
                                        'before a record or act — what it produced is '
                                        'committed or shipped without anything checking it'})
                    break

        # The shape language, grammar 1.13.0. The rules above ask whether the steps are in
        # a defensible ORDER; this asks whether the shape as a whole is one the language
        # admits. A method can satisfy every ordering rule and still have a shape nothing
        # else has — which is worth saying, because an unusual shape is either a new kind
        # of work or a mistake, and the author is the only one who can tell which.
        # Matched against the PATTERN, not against a list of shapes.
        #
        # The language is infinite — `cycle+` and `act_block*` are unbounded — so any
        # enumeration is a sample, and testing membership against a sample rejects
        # legitimate methods for being long. It did: a four-cycle method was flagged with
        # nothing wrong with it, purely because the enumeration stopped at three.
        #
        # The language is REGULAR, so it has a finite description and membership is
        # decidable at any length. That is the whole reason "every possible workflow" is
        # answerable rather than merely sampled.
        lang = (spec.get('shape_language') or {})
        pattern = lang.get('pattern')
        if pattern and seq:
            shape = []
            for _, p in seq:
                if not shape or shape[-1] != p:
                    shape.append(p)
            if not re.match(pattern, ' '.join(shape)):
                out.append({'step': seq[0][0], 'finding': 'shape-unknown', 'verb': None,
                            'note': f'the shape {" → ".join(shape)} is not in the language — '
                                    'either a new kind of work, or a step in the wrong place'})

        if 'change' in order and 'record' not in order:
            out.append({'step': next(n for n, p in seq if p == 'change'),
                        'finding': 'change-is-recorded', 'verb': None,
                        'note': 'this method changes things and records none of them; a '
                                'generated file that is not committed is not synced, only '
                                'currently correct'})
        return out

    # ── storing and vending ────────────────────────────────────────────────────────────
    #
    # A workflow that can be stored and handed to someone else cannot carry its callables:
    # a function is not data, and a store that shipped executable steps would be a package
    # registry with a worse security model than the ones that already exist.
    #
    # So what travels is the METHOD, not the code. The spec carries the ordered steps, the
    # goal each one is for, and which of them act on the world — everything needed to
    # MEASURE the process — and the consumer binds their own implementations. That split
    # is not a limitation worked around; it is the correct seam. The valuable, transferable
    # part of a workflow was never the shell commands. It is knowing that releasing has
    # four steps in this order, that the third is irreversible, and what each one is FOR.
    #
    # It also means a vended workflow is safe to read: nothing in a spec can execute.

    SPEC_VERSION = 1

    def spec(self) -> dict:
        """The workflow as data — ordered, grounded, and carrying no code."""
        return {
            'spec_version': self.SPEC_VERSION,
            'goal': self.goal,
            'steps': [{'name': s.name, 'goal': s.goal,
                       'irreversible': s.irreversible, 'outward': s.outward}
                      for s in self.steps],
        }

    @classmethod
    def from_spec(cls, spec: dict, calibration=None) -> 'Workflow':
        """Rebuild a workflow from a spec. Every step comes back UNBOUND.

        Unbound steps raise if run, rather than defaulting to a no-op. A workflow that
        quietly skipped the steps nobody implemented would report a clean run of a process
        that did not happen — which is the failure this whole package exists to catch,
        reproduced by its own convenience method.
        """
        v = spec.get('spec_version')
        if v != cls.SPEC_VERSION:
            raise ValueError(f'spec_version {v!r} — this laserbrain reads '
                             f'{cls.SPEC_VERSION}. Refusing to guess at a shape it does '
                             'not know rather than silently mis-reading it.')
        w = cls(goal=spec['goal'], calibration=calibration)
        for s in spec.get('steps') or []:
            # fn=None leaves it unbound — the same path authoring a method uses, so
            # a vended workflow and a hand-written one are the same object.
            w.step(s['name'], None, goal=s.get('goal') or s['name'],
                   irreversible=bool(s.get('irreversible')),
                   outward=bool(s.get('outward')))
        return w

    def bind(self, name: str, fn) -> 'Workflow':
        """Supply the implementation for one step of a vended workflow."""
        if not callable(fn):
            raise TypeError(f'step {name!r} must be bound to something callable')
        for s in self.steps:
            if s.name == name:
                s.fn = fn
                s.bound = True
                return self
        raise KeyError(f'no step named {name!r} — this workflow has '
                       f'{[s.name for s in self.steps]}')

    def unbound(self) -> list[str]:
        """Steps still without an implementation. Check before running a vended workflow."""
        return [s.name for s in self.steps if s.bound is False]


class Store:
    """laserstore for methods — where workflows are kept and handed out.

        store = Store()
        store.put(release_workflow, 'release')      # keep it
        w = store.get('release')                    # someone else takes it, unbound
        w.bind('test', my_tests).bind('build', my_build)
        w.run()

    This is the records layer doing what the records layer is for. A method that lives in
    one person's head, or in one repo's Makefile, is not a method anyone can adopt — and
    the transferable part was never the commands. It is the shape: that releasing has these
    steps, in this order, that this one cannot be taken back, and what each is FOR.

    Nothing in a stored workflow can execute. Specs are data, steps come back unbound, and
    a step nobody binds raises rather than passing silently. So reading a vended workflow
    from someone you do not know is safe in a way that installing their package is not.
    """

    #: Methods that ship WITH laserbrain, inside the package. An agent that pip-installs
    #: gets these without knowing anything about whoever wrote them. They are the valid
    #: subsequences of the phase backbone — 19 of 63 combinations satisfy the five rules,
    #: and the ones where `confirm` appears without an `act` are dropped as degenerate.
    #: Local methods shadow shipped ones of the same name, because your release process is
    #: more specific than the generic one.
    SHIPPED = Path(__file__).parent / 'workflows'

    def __init__(self, root=None, shipped: bool = True):
        self.root = Path(root) if root else Path.home() / '.laserbrain' / 'workflows'
        self._shipped = self.SHIPPED if shipped else None

    def _paths(self) -> dict:
        """name -> path, local shadowing shipped."""
        out = {}
        if self._shipped and self._shipped.exists():
            for p in sorted(self._shipped.glob('*.json')):
                out[p.stem] = p
        if self.root.exists():
            for p in sorted(self.root.glob('*.json')):
                out[p.stem] = p
        return out

    def find(self, task: str, top: int = 3) -> list[dict]:
        """Given a task in words, which stored methods are for it.

        This is what makes a store more than a folder. Without it an agent must already
        know a method's name, which means it must already know the method exists — and an
        agent handed a task it has never seen is exactly the case a library is for.

        Matched with `norm` and Jaccard, the same normaliser Φ uses on goals and
        `collisions()` uses on grounds. Nothing new is introduced: if two texts describe the
        same work, the instrument already has an opinion about that, and this asks it.

        A task is compared against the method's goal AND its step goals, because the goal
        alone is short. "upload the wheel to PyPI" shares little with "publish a verified
        laserbrain release" but a great deal with that method's `upload-pypi` step.

        Returns rows ranked by score, best first. The caller decides what is good enough —
        deliberately, because a threshold that silently returned nothing would look
        identical to an empty store.
        """
        from . import norm
        want = norm(task)
        if not want:
            return []
        rows = []
        for name in self._paths():
            spec = self.vend(name)
            goal_words = norm(spec.get('goal') or '')
            step_words = set()
            for s in spec.get('steps') or []:
                step_words |= norm(s.get('goal') or '') | norm(s.get('name') or '')

            def jac(a, b):
                return len(a & b) / len(a | b) if (a or b) else 0.0

            # The goal carries more weight than the steps: a method whose GOAL matches is
            # for this task, one whose steps merely mention the words may just share
            # vocabulary.
            score = 0.7 * jac(want, goal_words) + 0.3 * jac(want, step_words)
            if score > 0:
                rows.append({'name': name, 'score': round(score, 3),
                             'goal': spec.get('goal'),
                             'steps': len(spec.get('steps') or []),
                             'gated': [s['name'] for s in (spec.get('steps') or [])
                                       if s.get('irreversible') or s.get('outward')],
                             'shipped': name not in
                                        {p.stem for p in self.root.glob('*.json')}
                                        if self.root.exists() else True})
        rows.sort(key=lambda r: -r['score'])
        return rows[:top]

    def put(self, workflow: 'Workflow', name: str) -> str:
        """Store a workflow's spec. Returns the path written."""
        import json
        if not name or '/' in name or name.startswith('.'):
            raise ValueError(f'{name!r} is not a usable name — it becomes a filename')
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.root / f'{name}.json'
        p.write_text(json.dumps(workflow.spec(), indent=2) + '\n', encoding='utf-8')
        return str(p)

    def vend(self, name: str) -> dict:
        """The raw spec, as data. Readable without building or running anything."""
        import json
        p = self._paths().get(name)
        if p is None:
            raise KeyError(f'no workflow {name!r} — have {self.list()}')
        return json.loads(p.read_text(encoding='utf-8'))

    def get(self, name: str, calibration=None) -> 'Workflow':
        """Vend a workflow, rebuilt and ready to bind. Every step arrives unbound."""
        return Workflow.from_spec(self.vend(name), calibration=calibration)

    def list(self) -> list[str]:
        """Every method available: shipped with laserbrain plus anything stored locally."""
        return sorted(self._paths())

    def catalogue(self) -> list[dict]:
        """What is on the shelf, with enough to choose by and nothing that runs."""
        out = []
        for n in self.list():
            try:
                s = self.vend(n)
            except Exception as e:
                out.append({'name': n, 'error': f'{type(e).__name__}: {e}'})
                continue
            steps = s.get('steps') or []
            out.append({'name': n, 'goal': s.get('goal'), 'steps': len(steps),
                        'irreversible': [x['name'] for x in steps if x.get('irreversible')],
                        'outward': [x['name'] for x in steps if x.get('outward')]})
        return out

    # ── team presets — the other thing the store vends ──────────────────────────────────
    #
    # A Workflow is one agent's process, in order, toward one goal. A preset is different in
    # kind: several agents in a styled rotation, no fixed finish, escalating a `return` when
    # they agree without moving. Forcing it into the same spec as a Workflow was tried and
    # reverted — role names like `explorer` and `synthesizer` fail lint()'s verb dictionary
    # (built for build/verify/deploy-shaped work), and even where a name could be coerced to
    # pass, `Workflow.run()` executes once through in order while a team cycles until it
    # converges or is returned — the same container would vend something that lints clean
    # and lies about what happens when it runs. So presets get their own four methods here,
    # named to match get()/vend()/find()/catalogue() — one door, two shapes behind it.
    #
    # PRESETS (this package's root) is the canonical source — synced ONE-WAY into
    # grammar.json's modulation.presets for the protocol document, never the reverse. These
    # methods read PRESETS directly, live, on every call: duplicating the roles into a
    # second file here would recreate the exact failure this project spent 2026-07-30 fixing
    # three times over — a hand-written copy of something with a canonical source, silently
    # falling behind it. Only `task` — descriptive text PRESETS itself does not carry — comes
    # from the grammar's copy, and only to make find_team() searchable; it is prose, not the
    # executable roles, so reading it from the documentation copy risks nothing load-bearing.

    def list_teams(self) -> list[str]:
        """Every recursion-team preset the package ships."""
        from . import PRESETS
        return sorted(PRESETS)

    def vend_team(self, name: str) -> dict:
        """A preset as data: its task, if the grammar documents one, and its roles — each
        carrying a recurse depth and, where it has one, a return policy. Nothing here can
        execute; roles are not code, the same guarantee vend() makes for workflows."""
        from . import PRESETS, _G
        if name not in PRESETS:
            raise KeyError(f'no team preset {name!r} — have {self.list_teams()}')
        task = next((p.get('task') for p in
                     (_G.get('modulation') or {}).get('presets') or []
                     if p.get('name') == name), None)
        return {'name': name, 'task': task, 'roles': PRESETS[name]}

    def get_team(self, name: str, goal: str, key=None, api=None, calibration=None) -> 'Team':
        """Vend a preset, built and ready to run — the same door as get() for workflows.
        `Team(name, goal)` already does exactly this; this only names it to match."""
        from . import Team
        kw = {'key': key, 'calibration': calibration}
        if api is not None:
            kw['api'] = api
        return Team(name, goal, **kw)

    def find_team(self, task: str, top: int = 3) -> list[dict]:
        """Given a task in words, which team presets are for it — the same normaliser and
        scoring find() uses for workflows, matched against each preset's task and role
        names instead of a workflow's steps."""
        from . import norm
        want = norm(task)
        if not want:
            return []
        rows = []
        for name in self.list_teams():
            spec = self.vend_team(name)
            task_words = norm(spec.get('task') or '')
            role_words = set()
            for r in spec['roles']:
                role_words |= norm(r.get('role') or '')

            def jac(a, b):
                return len(a & b) / len(a | b) if (a or b) else 0.0

            score = 0.7 * jac(want, task_words) + 0.3 * jac(want, role_words)
            if score > 0:
                rows.append({'name': name, 'score': round(score, 3), 'task': spec.get('task'),
                             'roles': [r['role'] for r in spec['roles']]})
        rows.sort(key=lambda r: -r['score'])
        return rows[:top]

    def catalogue_teams(self) -> list[dict]:
        """What team presets are on the shelf, with enough to choose by."""
        return [{'name': n, 'task': self.vend_team(n).get('task'),
                 'roles': [r['role'] for r in self.vend_team(n)['roles']]}
                for n in self.list_teams()]
