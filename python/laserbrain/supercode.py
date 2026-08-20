"""supercode — an agent for agents. It watches, scores, and writes. It never acts.

    from laserbrain import Supercode

    sc = Supercode(goal='ship the parser and the benchmark')
    sc.observe('writer',  goal='write a JSON parser', progress='advancing', distance=4)
    sc.observe('builder', goal='benchmark the cache',  progress='stuck',     distance=7)
    print(sc.report())        # what every agent is doing, scored
    sc.publish()              # the same findings, written into the link

WHY IT ONLY ADVISES. laserbrain's whole claim is that it is a monitor, not a planner —
an outside reference an agent cannot fool, which never tells it what to do next. A
supervisor with authority to reground would break that in the one place it matters most,
because the supervisor cannot see the work either. It sees the same three fields the
agent spelled. Handing that reading command authority makes it a planner with less
information than the planner it overrides.

So supercode writes to the link and the agents read it. An agent told it is oscillating
knows something it could not know alone — the shape of its own sequence — and decides
for itself what that means.

TWO THINGS THAT MAKE IT LASERBRAIN RATHER THAN AN ORCHESTRATOR.

One: it runs under its own instrument. Its goal is "keep N agents on their grounds",
which is a goal the harness can score, so the supervisor is measured by the thing it
applies. `sc.self_check()` returns supercode's own verdict. A supervisor that has drifted
is worse than none, and this is the only way it can find out.

Two: it judges on OBSERVED events, not on self-report. Each agent gets its own Harness —
so its ground is its own first goal, not the supervisor's — and `catches` reads what an
agent's tools actually returned. laserbrain's own docs call self-report the weak signal;
a supervisor built on self-report inherits that weakness N times over.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _f

from . import _G, norm, _asdist
from .catches import Catch, Event, catches


@dataclass
class AgentView:
    """One agent as supercode sees it: its own ground, its own trace, its own events."""
    name: str
    harness: object
    last: object = None
    events: list = _f(default_factory=list)
    steps: int = 0
    # The ground goal as text, captured on the FIRST observation. The Harness holds it too,
    # inside a private _run, but reaching in there would couple this to an internal shape —
    # and collisions() needs the words, not the object.
    ground: str = ''


class Supercode:
    """Watches N agents against their own grounds. Writes findings; never acts."""

    def __init__(self, goal: str = 'keep every agent on its own ground', calibration=None):
        from . import Harness
        self.goal = goal
        self._cal = calibration
        self._mk = Harness
        self.agents: dict[str, AgentView] = {}
        # The supervisor, under the instrument — and GROUNDED HERE, at construction.
        #
        # This grounded lazily on the first self_check(), which made that call return
        # 'grounded' Φ=0.00 unconditionally: the supervisor's self-assessment was true by
        # construction and therefore worth nothing. That is precisely the self-report
        # weakness this class exists to avoid in the agents it watches, reproduced in the
        # one place nothing else was checking.
        #
        # Grounding now, with no agents yet, means the first real self_check is measured
        # against a reference that already existed — so it can come back stalled, or
        # self-report, or drifting, rather than always agreeing with itself.
        self._self = Harness(calibration=calibration)
        # From grammar.json, not a literal. Higher than goal_min (0.30) on purpose: that
        # threshold asks whether ONE agent has left its ground, a weaker claim than two
        # agents occupying the same one.
        self._collision_min = float(
            (_G.get('calibration') or {}).get('collision_min', 0.60))
        self._self.check(goal=self.goal, progress='advancing', distance=0)

    # ── watching ──────────────────────────────────────────────────────────────
    def observe(self, agent: str, goal: str, progress: str = 'advancing',
                distance=None, parent_goal: str | None = None, user_turn: bool = False):
        """Score one step of one agent against THAT agent's ground, not the supervisor's."""
        v = self.agents.get(agent)
        if v is None:
            v = self.agents[agent] = AgentView(agent, self._mk(calibration=self._cal))
        if not v.ground:
            v.ground = str(goal or '')
        v.last = v.harness.check(goal=goal, progress=progress, distance=distance,
                                 parent_goal=parent_goal, user_turn=user_turn)
        v.steps += 1
        return v.last

    def saw(self, agent: str, event: Event):
        """Record an observed event — a tool result, a check, a claim — for `catches`."""
        v = self.agents.get(agent)
        if v is None:
            v = self.agents[agent] = AgentView(agent, self._mk(calibration=self._cal))
        v.events.append(event)

    # ── reading ───────────────────────────────────────────────────────────────
    def findings(self) -> list[dict]:
        """Everything worth saying, one row per agent. Empty when all is well."""
        out = []
        for name, v in sorted(self.agents.items()):
            row = {'agent': name, 'steps': v.steps,
                   'reason': getattr(v.last, 'reason', None),
                   'phi': getattr(v.last, 'phi', None),
                   'drifting': bool(getattr(v.last, 'drifting', False)),
                   'laserscore': getattr(v.last, 'laserscore', None),
                   'catches': [c.signature for c in catches(v.events)]}
            if row['drifting'] or row['catches']:
                out.append(row)
        return out

    def collisions(self) -> list[dict]:
        """Pairs of agents working the same job.

        THE reading only a supervisor can take. Every single-agent verdict is about one
        agent against one ground, so two agents handed the same task are both perfectly
        grounded, both advancing, and both correct at every step — the duplication is
        invisible from inside either one. It is not a drift, and no threshold on Φ will
        ever surface it. It exists only as a relation.

        Deliberately NOT a tenth verdict. The nine describe one agent against one ground
        and should keep meaning exactly that. This describes a relation between two, which
        is a different kind of object. Reported like every other supercode finding, and
        nothing is interrupted — the supervisor advises and does not act.

        Compared on GROUNDS, not current goals. A ground is fixed for the run, so a
        collision is a fact about how the work was divided; two current goals that touch
        for one step are just two agents in the same file.
        """
        names = sorted(self.agents)
        out = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ga, gb = self.agents[a].ground, self.agents[b].ground
                if not ga or not gb:
                    continue
                wa, wb = norm(ga), norm(gb)
                if not wa or not wb:
                    continue
                overlap = len(wa & wb) / len(wa | wb)
                if overlap >= self._collision_min:
                    out.append({'agents': [a, b], 'overlap': round(overlap, 2),
                                'grounds': [ga, gb]})
        return sorted(out, key=lambda r: -r['overlap'])

    def fleet_catches(self) -> list[dict]:
        """Bugfinder across agents — only what a per-agent Bugfinder CANNOT reach.

        findings() already runs the six catches over each agent's own events. The first
        version of this method re-ran three of them over the pooled log and reported the
        results as fleet findings, which was mostly duplication: a test showed per-agent
        `unfalsified` and `unrun` had already fired on the same evidence. Two of the three
        "supervisor-only" catches were the supervisor repeating what everyone already knew.

        So this reports only where fleet evidence CHANGES the per-agent answer, and it does
        so in both directions — because more evidence can exonerate as easily as accuse:

        blind_fleet     one tool returning an identical result to agents doing DIFFERENT
                        work. instrument_blind sees repetition within one log and cannot
                        tell whether the input repeated too; across agents the inputs are
                        known to differ, so an identical answer means the tool is not
                        reading its input. No single agent can compute this.

        thin_evidence   a check green everywhere and red nowhere, where NO agent has seen
                        enough of it to trigger unfalsified alone. Three passes is a weak
                        sample; thirty across six agents with no red is a gate that cannot
                        fail. Suppressed when a per-agent catch already fired — that is
                        already reported and does not need saying twice.

        unrun_cleared   the useful inversion. Per-agent `unrun` fires when the claiming
                        agent never executed what it claimed. If ANOTHER agent did execute
                        it, the claim is backed and the per-agent catch is a false positive
                        that only the fleet can clear. An instrument that can only add
                        accusations gets switched off.
        """
        by_check: dict[str, list[tuple[str, bool]]] = {}
        by_tool: dict[str, dict[str, set]] = {}
        claims: list[tuple[str, str]] = []
        ran: dict[str, set] = {}
        per_agent: dict[str, set] = {}

        for name, v in sorted(self.agents.items()):
            per_agent[name] = {c.signature for c in catches(v.events)}
            for e in v.events:
                if e.kind == 'check' and e.ok is not None:
                    by_check.setdefault(e.name, []).append((name, bool(e.ok)))
                elif e.kind == 'tool':
                    d = by_tool.setdefault(e.name, {'agents': set(), 'results': set()})
                    d['agents'].add(name)
                    d['results'].add(repr(e.result))
                    ran.setdefault(e.name, set()).add(name)
                elif e.kind == 'claim':
                    claims.append((name, e.name))

        out = []
        for tool, d in sorted(by_tool.items()):
            if len(d['agents']) > 1 and len(d['results']) == 1:
                out.append({'signature': 'blind_fleet', 'subject': tool,
                            'agents': sorted(d['agents']),
                            'detail': (f"'{tool}' returned an identical result to "
                                       f"{len(d['agents'])} agents doing different work — "
                                       f"it is not reading its input")})

        for check, rows in sorted(by_check.items()):
            agents = sorted({a for a, _ in rows})
            if len(agents) < 2 or not all(ok for _, ok in rows):
                continue
            # Only when nobody could have concluded this alone. If a per-agent unfalsified
            # already fired, findings() is carrying it and repeating it here is noise.
            if any('unfalsified' in per_agent[a] for a in agents):
                continue
            if len(rows) >= 3:
                out.append({'signature': 'thin_evidence', 'subject': check,
                            'agents': agents,
                            'detail': (f"'{check}' passed {len(rows)}x across {len(agents)} "
                                       f"agents and never failed, and no single agent saw "
                                       f"enough of it to notice")})

        for agent, subject in claims:
            others = ran.get(subject, set()) - {agent}
            if others and 'unrun' in per_agent.get(agent, set()):
                out.append({'signature': 'unrun_cleared', 'subject': subject,
                            'agents': sorted({agent} | others),
                            'detail': (f"'{agent}' was flagged for claiming '{subject}' "
                                       f"without running it, but {', '.join(sorted(others))} "
                                       f"did — the claim is backed and the per-agent catch "
                                       f"is a false positive")})
        return out

    def route(self) -> list[dict]:
        """For each collision, which agent should continue — and which should yield.

        THE ONE PLACE A SUPERVISOR MAY DECIDE ANYTHING, and it is worth being exact about
        why. Everywhere else this class refuses to act, because it sees three spelled
        fields and the agent sees the work: a supervisor that regrounds mid-run is a
        planner with less information than the planner it overrides.

        Allocation inverts that. Which agents are on which grounds is a fact NO individual
        agent can observe — each one is perfectly on its own ground and correct at every
        step. Here the supervisor holds strictly more information than anyone it advises,
        which is the only condition under which advising is honest.

        The boundary is therefore: route WORK, never route EXECUTION. This says who should
        yield. It does not say what the yielding agent should do instead, because supercode
        has no basis for that — inventing a replacement goal would be exactly the overreach
        the rest of the class exists to avoid.

        Ranked on what is observable: catches first (an agent whose evidence is questioned
        has the weaker claim), then steps invested, then proximity to its own ground. When
        those are equal the answer is NO RECOMMENDATION rather than a coin-flip dressed as
        a decision — a supervisor that manufactures a preference it cannot support is worse
        than one that admits the tie.
        """
        out = []
        for c in self.collisions():
            a, b = c['agents']
            va, vb = self.agents[a], self.agents[b]

            def rank(v):
                return (len(catches(v.events)),                       # fewer catches first
                        -v.steps,                                     # more steps first
                        getattr(v.last, 'phi', 0.0) or 0.0)           # closer to ground first

            ra, rb = rank(va), rank(vb)
            row = {'agents': [a, b], 'overlap': c['overlap'], 'ground': c['grounds'][0]}
            if ra == rb:
                row.update(keep=None, yield_=None,
                           why='no basis to choose — equal catches, steps and displacement')
            else:
                keep, drop = (a, b) if ra < rb else (b, a)
                vk, vd = self.agents[keep], self.agents[drop]
                row.update(keep=keep, yield_=drop, why=(
                    f'{keep} has {len(catches(vk.events))} catch(es) over {vk.steps} step(s); '
                    f'{drop} has {len(catches(vd.events))} over {vd.steps}'))
            out.append(row)
        return out

    def manage(self, agents: dict, max_steps: int = 30, on_return=None,
               escalate_after: int | None = None, on_escalate=None) -> dict:
        """Run N agents under supervision. `agents` is {name: step_fn}.

        Each step_fn(ctx) returns dict(goal, progress, distance, tokens?, done?) — the same
        contract Harness.run uses, because this IS that loop widened to N. Returns
        {name: ctx} when every agent is finished, halted or the ceiling is hit.

        WHAT MANAGING MEANS HERE, EXACTLY
        ---------------------------------
        Three powers, each with a reason it is allowed:

        1. ASSIGN and HALT on collision. Two agents on one ground is a fact no agent can
           observe — each is perfectly grounded and correct at every step. The supervisor
           holds strictly more information than either, so it may stop the duplication. It
           halts the yielding agent and says why; it does NOT hand it a new goal, because
           it has no basis for one.

        2. INJECT the agent's own verdict. On drift, ctx['return'] carries the advice the
           agent's OWN harness produced against its OWN frozen ground. Supercode is the
           courier, not the author — it is not substituting its judgment for the agent's,
           it is delivering a reading the agent cannot take from inside.

        3. ESCALATE to a human. When drift persists for `escalate_after` steps, the human
           decides and their decision overrides. Authority goes UP to a person, never
           sideways to the supervisor.

        WHAT IT STILL WILL NOT DO
        -------------------------
        Reground a running agent — tell it what its goal now is. Supercode sees three
        spelled fields; the agent sees the work. A supervisor that regrounds mid-run is a
        planner overriding a better-informed planner, and every reading it makes afterward
        is measured against a reference it chose itself, which is the self-referential
        monitor PROOF forbids. Halting is not regrounding: stopping an agent leaves the
        decision about what happens next with whoever reads the report.
        """
        # The operator bar, grammar 1.8.0. Checked before anything runs rather than at
        # dispatch, so a fleet containing operator work fails whole instead of half-done —
        # a supervisor that halted midway would have already taken some of the actions it
        # had no basis to route.
        _refuse_routing(agents)

        ctxs = {n: {'returns': 0, 'streak': 0, 'steps': 0} for n in agents}
        live = dict(agents)
        for _ in range(max_steps):
            if not live:
                break
            for name in list(live):
                ctx = ctxs[name]
                s_ = live[name](ctx) or {}
                ctx['steps'] += 1
                v = self.observe(agent=name, goal=s_.get('goal', ''),
                                 progress=s_.get('progress', 'advancing'),
                                 distance=s_.get('distance'))
                ctx['verdict'] = v
                if getattr(v, 'drifting', False):
                    ctx['returns'] += 1
                    ctx['streak'] += 1
                    ctx['return'] = v.advice          # the agent's own reading, delivered
                    if on_return:
                        on_return(name, v, ctx)
                    if (escalate_after and ctx['streak'] >= escalate_after
                            and not ctx.get('escalated')):
                        ctx['escalated'] = True
                        decision = (on_escalate or (lambda n, v, c: None))(name, v, ctx)
                        if decision:                  # a person's call outranks the monitor
                            ctx['return'] = ctx['decision'] = decision
                else:
                    ctx['streak'] = 0
                    ctx.pop('return', None)
                    ctx.pop('escalated', None)
                if s_.get('done') or _asdist(s_.get('distance')) == 0:
                    ctx['finished'] = True
                    live.pop(name, None)

            # Allocation, checked after every agent has moved: the supervisor's one power
            # over execution, and only to STOP duplicated work.
            for r in self.route():
                y = r['yield_']
                if y and y in live:
                    ctxs[y].update(halted=True, halted_why=(
                        f"shares a ground with {r['keep']} (overlap {r['overlap']:.2f}) — "
                        f"halted to stop duplicate work. Choosing what {y} does next is "
                        f"not supercode's call."))
                    live.pop(y, None)
                elif not r['keep']:
                    # A collision with no basis to choose. Declining to pick is right —
                    # the observable state genuinely does not favour either — but letting
                    # the duplication run on is not, and picking one at random would be a
                    # coin-flip wearing a decision's clothes.
                    #
                    # So it goes UP. Same rule as persistent drift: when the monitor cannot
                    # honestly decide, a person does. Recorded on both contexts either way,
                    # so a caller with no escalation hook still sees it rather than losing
                    # an agent's work to silence.
                    a, b = r['agents']
                    # Once per PAIR, not once per step. A collision is a standing fact
                    # about how the work was divided, not an event that recurs — appending
                    # every step turns one finding into a count of how long nobody looked
                    # at it.
                    for n in (a, b):
                        seen = ctxs[n].setdefault('collision_unresolved', [])
                        other = b if n == a else a
                        if not any(x['with'] == other for x in seen):
                            seen.append({'with': other, 'overlap': r['overlap'],
                                         'why': r['why']})
                    if on_escalate and not ctxs[a].get('collision_escalated'):
                        ctxs[a]['collision_escalated'] = True
                        ctxs[b]['collision_escalated'] = True
                        decision = on_escalate(f'{a}+{b}', None, {'collision': r})
                        # A person naming who yields is the one authority that can settle
                        # this. Supercode carries it out; it did not choose it.
                        if decision in (a, b) and decision in live:
                            ctxs[decision].update(halted=True, halted_why=(
                                f'human decision: yield to '
                                f'{b if decision == a else a}'))
                            live.pop(decision, None)
        return ctxs

    def self_check(self):
        """Supercode's own verdict. The supervisor is not exempt from the instrument.

        distance is how many agents are currently drifting — the supervisor's own
        distance-to-done, and the one number it can honestly report about itself.
        """
        drifting = sum(1 for v in self.agents.values()
                       if getattr(v.last, 'drifting', False))
        n = len(self.agents) or 1
        return self._self.check(goal=self.goal,
                                progress='advancing' if drifting < n else 'stuck',
                                distance=min(10, drifting))

    def report(self) -> str:
        """The whole picture as text — what to print, log, or hand to a human."""
        rows = self.findings()
        me = self.self_check()
        lines = [f'supercode · {len(self.agents)} agent(s) · {len(rows)} finding(s)',
                 f'  self: {me.reason} Φ={me.phi:.2f}']
        cols = self.collisions()
        if not rows and not cols:
            lines.append('  every agent on its own ground')
        elif not rows and cols:
            # Worth saying plainly: nothing is drifting AND something is wrong. That
            # combination is the whole reason this method exists.
            lines.append('  every agent on its own ground — and two of them share it')
        for c in cols:
            lines.append(f"  {' + '.join(c['agents'])}  same job (overlap {c['overlap']:.2f})")
        for f in self.fleet_catches():
            lines.append(f"  {f['signature']}  {f['subject']} · {', '.join(f['agents'])}")
        for r in rows:
            c = (' · ' + ', '.join(r['catches'])) if r['catches'] else ''
            lines.append(f"  {r['agent']:12} {r['reason'] or '-':16} Φ={r['phi']:.2f}"
                         f" step {r['steps']}{c}")
        return '\n'.join(lines)

    # ── writing · the only thing it does to the world ─────────────────────────
    def publish(self, kind: str = 'supervision') -> list[dict]:
        """Write each finding into the link, where the agents can read it.

        This is the whole action surface. Nothing here regrounds, halts or reassigns —
        an agent reads that it is oscillating with period 2, which is a fact about its
        sequence it could not observe from inside, and decides for itself.
        """
        from .link import link_write
        written = []
        for r in self.route():
            if not r['keep']:
                continue
            # Written as a recommendation into the link, exactly like every other finding.
            # The agents read it and decide; nothing here reassigns anyone.
            written.append(link_write(
                f"{r['yield_']} and {r['keep']} share a ground (overlap {r['overlap']:.2f}) — "
                f"suggest {r['yield_']} yields", kind=kind, goal=self.goal,
                payload=r, agent='supercode'))
        for r in self.findings():
            note = f"{r['agent']}: {r['reason']}"
            if r['catches']:
                note += f" · {', '.join(r['catches'])}"
            written.append(link_write(note, kind=kind, goal=self.goal, payload=r,
                                      agent='supercode'))
        return written


def _refuse_routing(agents):
    """Deferred import: operator.py is a peer and nova imports both, so binding it at
    module scope would make the package's import order load-bearing for no benefit."""
    from .operator import refuse_routing
    return refuse_routing(agents)
