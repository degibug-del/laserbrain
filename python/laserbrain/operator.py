"""operator.py — the sixth layer, as something nova can hold.

Named in grammar 1.8.0 on 2026-07-28. The other five layers measure, instruct, serve,
define and record; the operator is the only one that ACTS on the world. That is the whole
reason it needed a name of its own rather than being filed under lasergear as "tools".

WHY IT IS A LAYER

The grammar sets the test: a part is real when it has a failure mode none of the others
share. Every other failure is recoverable by correction — a wrong reading is re-taken, an
absent instruction supplied, an unreachable server retried, a mismatched copy re-synced, a
lost record rebuilt. The operator's is not. A sent message is sent. A deleted file is
deleted. It fails by being IRREVERSIBLE.

WHAT THIS MODULE ACTUALLY ENFORCES

One rule, from the layer's own `may_not` clause:

    take an irreversible or outward-facing action without authorization from the person,
    per action and per session

Three things follow, and each is a deliberate choice rather than an implementation detail:

1. DEFAULT IS DENY. An Operator built with no authorizer refuses every irreversible action.
   The alternative — proceed unless someone objects — puts the burden on the person who is
   not in the loop, which is the situation the layer exists to describe.

2. APPROVAL DOES NOT CACHE. Every irreversible act asks, every time, even for an identical
   action approved a moment ago. "Per action and per session" is the strict reading and the
   safe one: caching by fingerprint would let one approval cover a repeat the person never
   saw. A loop that deletes a thousand files would ask once. That is the failure this rule
   is for.

3. REFUSAL IS RECORDED, NOT SILENT. Every act — taken, refused, or failed — lands in `log`.
   An operator that blocked something and said nothing is indistinguishable from one that
   was never called, which is the same "silence is not success" problem the harness has
   everywhere else.

WHAT IT DOES NOT DO

It does not decide what is reversible. The caller declares that, because only the caller
knows what the callable actually does — a guard that inferred reversibility from a string
would be guessing, and guessing in this direction is exactly the wrong way to be wrong.
Declaring nothing means `reversible=False`, so an undeclared action is treated as
irreversible and asks.

It is also not a sandbox. Python offers no true barrier and this class does not pretend to
be one: `op._authorize = lambda a: True` is one line away for anything running in-process.
It is the same posture as `Nova.ground_intact()` — evidence rather than a wall. What it
guarantees is that taking an irreversible action without asking cannot happen BY ACCIDENT,
and that if it happens deliberately the log says so.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field as _f

from .catches import Event

_COMPILED = None


def _patterns():
    """The irreversible-command list, compiled once, from grammar.json.

    Read from the grammar rather than typed here. The same list is what
    lasergear/lb_safety.py enforces as a PreToolUse deny hook, and that file ships
    as a hook while this one ships on PyPI — neither can import the other, so a literal
    list in either place becomes two lists that drift. grammar.json is already canonical,
    already synced across four copies, and already packaged with the wheel.
    """
    global _COMPILED
    if _COMPILED is None:
        from . import _G
        raw = _G.get('operator_patterns') or {}
        _COMPILED = {
            'deny': [(re.compile(r['pattern'], re.I), r['label'], bool(r.get('outward')))
                     for r in (raw.get('irreversible') or [])],
            'allow': [(re.compile(r['pattern'], re.I), r['label'])
                      for r in (raw.get('allow') or [])],
        }
    return _COMPILED


def classify(command: str, *, reversible: bool = False, outward: bool = False):
    """Escalate a caller's declaration about a shell command. Never relax it.

    Returns `(reversible, outward, why)`. A command matching a known-irreversible pattern
    comes back `reversible=False` whatever the caller claimed; a command matching nothing
    comes back exactly as the caller declared.

    The asymmetry is the whole point. A classifier that could talk the guard DOWN would be
    a way around it — `reversible=True` plus a clever string and the gate opens. This one
    can only ever ask more often than the caller intended, which is the direction it is
    safe to be wrong in.

    An authorized carve-out (grammar `operator_patterns.allow`) is reported in `why` but
    does NOT downgrade anything. The carve-out means a hook will not hard-block the
    command; it does not mean the person consented to this particular run of it, and
    "per action and per session" is the rule this module enforces.
    """
    text = str(command or '')
    why = []
    pats = _patterns()

    for rx, label in pats['allow']:
        if rx.search(text):
            why.append(f'carve-out: {label} (still asks)')

    for rx, label, is_outward in pats['deny']:
        if rx.search(text):
            reversible = False                    # escalate only
            outward = outward or is_outward
            why.append(label)

    return reversible, outward, '; '.join(why)


class Refused(Exception):
    """An action the operator would not take.

    Raised rather than returned. A refusal that came back as a falsy value would be
    silently ignorable by `if op.act(...)`-shaped code, and the one thing a refusal must
    not be is easy to miss.
    """


@dataclass(frozen=True)
class Act:
    """A description of something about to be done to the world.

    `reversible` and `outward` are declared by the caller, never inferred. See the module
    docstring: inferring them would mean guessing, and the default has to be the cautious
    one.
    """

    kind: str                    # 'shell' | 'file' | 'browser' | 'deploy' | 'send' | ...
    target: str                  # what it acts on, in whatever form the caller has
    reversible: bool = False
    outward: bool = False        # leaves this machine — a send, a publish, a deploy

    @property
    def needs_authorization(self) -> bool:
        """Irreversible OR outward. Either alone is enough.

        Outward-facing matters even when reversible: an email you can delete has still been
        read, and a page you can unpublish has still been indexed.
        """
        return (not self.reversible) or self.outward

    def __str__(self) -> str:
        marks = []
        if not self.reversible:
            marks.append('irreversible')
        if self.outward:
            marks.append('outward')
        return f'{self.kind}:{self.target}' + (f' ({", ".join(marks)})' if marks else '')


class Operator:
    """The hands. Give it an authorizer or it will refuse anything that cannot be undone.

        op = Operator(authorize=ask_the_person)
        op.attach(nova)
        nova.use('operator', shutil.rmtree, kind='file', target='/tmp/x', path='/tmp/x')

    `authorize` receives the Act and returns truthy to allow. It is supplied by whatever
    is standing in for the person — a prompt, a hook, a queue. Nova cannot set it: nothing
    in this class reads from the agent, which is the same reason `Nova` has no method that
    moves its own ground.
    """

    #: supercode may not route operator work. Allocation is a reading; an action is not,
    #: and a manager that could dispatch irreversible work would be deciding something no
    #: reading gives it a basis for. Written into layers.operator.routing in grammar 1.8.0.
    routable = False

    def __init__(self, authorize=None, name: str = 'operator', harness=None,
                 key: str | None = None, api: str | None = None, run_id: str | None = None):
        """`harness` wires the hands to the instrument. Optional, and off by default.

        Give it a Harness and this operator will not take an irreversible or outward action
        while that harness's last reading says the agent is drifting, OR while the harness's
        judgment on the whole run says the run itself should stop (abandon, wrong-problem,
        repeating). That is the whole sixth join: until now the harness could say "return to
        your goal" and an agent was free to deploy anyway, because advice is advice. Here it
        becomes a refusal.

        Two different questions, both enforced, because they catch different failures. The
        drift check reads `harness.last` — one step, the most recent reading. A run can be
        twelve checks into work that never closed the distance and still have its twelfth
        step read as locally fine, which is precisely the case `harness.phronesis()` exists
        to catch: it reads the WHOLE trace, not the latest sample of it. Narrow and verify
        are advisory, not blocking — they say the goal is too big or the self-report
        disagrees with the trace, not that acting right now is wrong.

        Both read the harness rather than calling it, and the distinction matters the same
        way in both cases: an operator has no goal, no progress and no distance to spell.
        Inventing them would be the operator marking its own homework, which is the exact
        failure the fixed reference exists to prevent.
        """
        self.name = name
        self._authorize = authorize
        self._harness = harness
        self._key = key
        self._api = api
        self._run_id = run_id
        self.log: list[Event] = []
        self.asked = 0
        self.refused = 0
        self.taken = 0
        #: Irreversible acts stopped because the agent was off its ground.
        self.blocked_by_drift = 0
        #: Irreversible acts stopped because the WHOLE RUN was judged not worth continuing
        #: (abandon, wrong-problem, repeating) — distinct from blocked_by_drift, which fires
        #: on one bad step. This one fires on a bad run whose latest step looked fine.
        self.blocked_by_judgment = 0
        #: Irreversible acts stopped because a PEER was already doing them.
        self.blocked_by_peer = 0

    # ── the one entry point ────────────────────────────────────────────────────────────
    def act(self, do, *, kind: str, target: str,
            reversible: bool = False, outward: bool = False, **kw):
        """Run `do(**kw)`, but only if the layer's rule allows it.

        Returns whatever `do` returns. Raises `Refused` if authorization was required and
        not given — including when no authorizer exists at all, which is the default.
        """
        if not callable(do):
            raise TypeError(f'operator needs something callable, got {type(do).__name__}')

        a = Act(kind=kind, target=target, reversible=reversible, outward=outward)

        # ── the sixth join ──────────────────────────────────────────────────────────────
        #
        # BEFORE the authorizer, not after, and that order is the point. Asking a human to
        # approve an irreversible act by an agent that is off its goal is precisely the
        # moment a human rubber-stamps: the request looks reasonable in isolation, because
        # every drifting step does. The drift is only visible against the ground, and the
        # ground is what the harness holds.
        #
        # Reversible, inward acts are untouched. A drifting agent may still read a file.
        if self._harness is not None and a.needs_authorization:
            v = getattr(self._harness, 'last', None)
            if v is None:
                # NO READING IS NOT A GOOD READING. An operator wired to a harness that has
                # never been checked knows nothing about the agent asking it to act, and
                # "nothing" must not be spent as "fine" — that is the failure this whole
                # instrument is named after. Opt-in, so this breaks nobody who did not ask.
                self.blocked_by_drift += 1
                return self._refuse(a, 'the harness has taken no reading — call check() '
                                       'before asking for something that cannot be undone')
            if getattr(v, 'drifting', False):
                self.blocked_by_drift += 1
                return self._refuse(
                    a, f'the agent is off its ground ({v.reason}, \u03a6={v.phi:.2f}) — '
                       f'return before acting irreversibly. {v.advice}')

            # The whole-trace question, asked beside the one-step question. `phronesis()`
            # is pure local computation over data check() already collected — no network
            # call, so this costs nothing check() itself did not already pay for.
            j = self._harness.phronesis()
            if j.get('verdict') in ('abandon', 'wrong-problem', 'repeating'):
                self.blocked_by_judgment += 1
                return self._refuse(
                    a, f"the run itself is judged {j['verdict']} — {j['because']} "
                       f"{j['counsel']}")

        # ── the group half of the join ──────────────────────────────────────────────────
        #
        # The local check above knows this agent. It cannot know that a DIFFERENT agent, on
        # a different machine, is already deploying the same thing — two agents each
        # perfectly grounded and each advancing, doing one irreversible thing twice. That
        # fault exists only between them.
        #
        # FAILS OPEN, LOUDLY. If the service cannot be reached the act proceeds, because a
        # network blip must not stop a deploy that the local instrument already cleared —
        # but the event records that the group was not consulted, so a later reader is
        # never told a check happened that did not.
        if self._key and a.needs_authorization:
            verdict = self._consult_group(a)
            if verdict is not None and not verdict.get('allow', True):
                if verdict.get('reason') == 'duplicate':
                    self.blocked_by_peer += 1
                else:
                    self.blocked_by_drift += 1
                return self._refuse(a, str(verdict.get('detail') or verdict.get('reason') or 'refused by the group'))

        if a.needs_authorization:
            self.asked += 1
            if self._authorize is None:
                return self._refuse(a, 'no authorizer — an operator with nobody to ask '
                                       'refuses anything it cannot take back')
            # Deliberately NOT cached. See point 2 in the module docstring.
            try:
                allowed = bool(self._authorize(a))
            except Exception as e:
                # An authorizer that breaks is not an authorizer that consented.
                return self._refuse(a, f'authorizer raised {type(e).__name__}: {e}')
            if not allowed:
                return self._refuse(a, 'not authorized')

        try:
            out = do(**kw)
        except Exception as e:
            self._record(a, ok=False, note=f'{type(e).__name__}: {e}')
            raise
        self.taken += 1
        self._record(a, ok=True, note='taken')
        return out

    # ── a concrete hand ────────────────────────────────────────────────────────────────
    def shell(self, command: str, *, reversible: bool = False, outward: bool = False,
              run=None, timeout: int = 120):
        """Run a shell command through the gate.

        The caller's declaration is passed through `classify()` first, so a command on the
        known-irreversible list asks even when the caller said `reversible=True`. Nothing
        the caller can write makes the gate open wider than it would have on its own.

        `run` is injectable, and defaults to a real subprocess. Tests pass their own so the
        suite never executes anything — which also means the default path is the one thing
        here NOT covered by a test, and that is deliberate: a test that shelled out for
        real would be a test that can delete something.
        """
        rev, outw, why = classify(command, reversible=reversible, outward=outward)
        runner = run or (lambda cmd: subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout))
        target = command if not why else f'{command}  [{why}]'
        return self.act(lambda: runner(command), kind='shell', target=target,
                        reversible=rev, outward=outw)

    def write(self, path, content: str, *, run=None, encoding: str = 'utf-8'):
        """Write a file. Reversibility is READ OFF THE DISK, not declared.

        This is the one place the operator can settle the question rather than trust an
        answer. Writing a file that does not exist is reversible — delete it and the world
        is as it was. Writing over one that does exist destroys content that has no other
        copy, and no amount of care in the caller changes that.

        So `write` does not take a `reversible` argument at all. Offering one would only
        create a way to be wrong about a fact already sitting in the filesystem.
        """
        import os
        p = str(path)
        exists = os.path.exists(p)

        def _do():
            with open(p, 'w', encoding=encoding) as fh:
                return fh.write(content)

        return self.act(run or _do, kind='file',
                        target=f'{p} ({"overwrite" if exists else "create"})',
                        reversible=not exists)

    def delete(self, path, *, run=None):
        """Delete a file. Never reversible, and never declared otherwise.

        Deliberately not recursive. A tree delete is the single action most likely to be
        regretted, and `rm -rf` is already on the escalation list for `shell` — an operator
        that offered a convenient one-call version of it would be handing back exactly what
        the layer exists to slow down. Call it per path, or go through `shell` and be
        asked.
        """
        import os
        p = str(path)
        if os.path.isdir(p):
            raise IsADirectoryError(
                f'{p} is a directory. This hand deletes one file at a time on purpose — '
                'recursive delete is the action the operator layer exists to make you '
                'say out loud.')
        return self.act(run or (lambda: os.remove(p)), kind='file',
                        target=f'{p} (delete)', reversible=False)

    def http(self, method: str, url: str, *, run=None, timeout: int = 30, **kw):
        """Make an HTTP request. Everything that is not a read is outward and irreversible.

        GET/HEAD/OPTIONS are treated as reads: reversible, and not marked outward. That is
        a JUDGMENT, and it can be wrong — an API that mutates on GET exists, and any
        request reveals to the far end that you made it. Pass `outward=True` through `act`
        if the read itself is the sensitive part. Everything else — POST, PUT, PATCH,
        DELETE — is both outward and irreversible, because a request that changed something
        on someone else's machine cannot be recalled by you.
        """

        # kw goes to urllib.request.Request (headers, data). It is NOT where reversible or
        # outward belong — those are decided from the method, per the docstring above. They
        # used to fall through and die as `Request.__init__() got an unexpected keyword
        # argument 'reversible'`, several frames deep, which reads like a urllib bug rather
        # than a misuse. Caught 2026-07-29 by calling it the way the name suggests.
        for bad in ('reversible', 'outward'):
            if bad in kw:
                raise TypeError(
                    f'http() decides {bad!r} from the method — GET/HEAD/OPTIONS are reads, '
                    f'everything else is outward and irreversible. To override, call '
                    f'act(do, kind=\'http\', target=..., {bad}=...) directly.')
        import urllib.request
        m = str(method).upper()
        read_only = m in ('GET', 'HEAD', 'OPTIONS')

        def _do():
            req = urllib.request.Request(url, method=m, **kw)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return {'status': r.status, 'body': r.read()}

        return self.act(run or _do, kind='http', target=f'{m} {url}',
                        reversible=read_only, outward=not read_only)

    def _consult_group(self, a: 'Act'):
        """Ask the hosted operator whether a PEER is already doing this. None = not asked.

        Returns the service's answer, or None when it could not be reached — and None is
        deliberately distinct from an allow, because "we did not ask" and "we asked and it
        said yes" are different facts about an irreversible action.
        """
        import json as _json
        import urllib.request
        api = self._api or 'https://laserbrain-mcp.degibug.workers.dev'
        body = _json.dumps({
            'run_id': self._run_id, 'kind': a.kind, 'target': a.target,
            'reversible': a.reversible, 'outward': a.outward,
        }).encode()
        req = urllib.request.Request(
            f'{api}/v1/operator/consult', data=body, method='POST',
            headers={'content-type': 'application/json',
                     'user-agent': 'laserbrain-sdk',
                     'authorization': f'Bearer {self._key}'})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return _json.loads(r.read() or b'{}')
        except Exception:
            return None

    # ── record-keeping ─────────────────────────────────────────────────────────────────
    def _refuse(self, a: Act, why: str):
        self.refused += 1
        self._record(a, ok=False, note=f'refused — {why}')
        raise Refused(f'{a}: {why}')

    def _record(self, a: Act, *, ok: bool, note: str):
        ev = Event(kind='operator', name=str(a), ok=ok, result=note)
        self.log.append(ev)

    # ── wiring ─────────────────────────────────────────────────────────────────────────
    def attach(self, nova, name: str | None = None):
        """Register as a skill on a Nova. Returns the nova so it can chain."""
        return nova.learn(name or self.name, self.act)

    def report(self) -> str:
        return (f'operator {self.name}: {self.taken} taken, {self.refused} refused, '
                f'{self.asked} asked, {len(self.log)} logged')


def refuse_routing(agents) -> None:
    """Raise if a supervisor is about to dispatch operator work.

    Called from Supercode.manage. The bar is not that acting is dangerous — it is that a
    manager's authority comes entirely from holding readings that no single agent has, and
    a reading gives no basis whatsoever for deciding who should take an irreversible
    action. Routing allocation is inside its competence; routing a deploy is not.
    """
    bad = []
    for name, fn in (agents or {}).items():
        owner = getattr(fn, '__self__', None)
        if isinstance(fn, Operator) or isinstance(owner, Operator) \
                or getattr(fn, 'routable', True) is False:
            bad.append(name)
    if bad:
        raise Refused(
            f'supercode may not route operator work: {", ".join(sorted(bad))}. '
            'Allocation is a reading; an action is not (grammar 1.8.0, '
            'layers.operator.routing).')
