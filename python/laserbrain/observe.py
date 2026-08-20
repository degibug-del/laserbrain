"""observe.py — infer the working state from what the runtime already knows.

WHY. The harness asks the agent to spell goal, progress and distance every step. That is
the honest interface and it is also the reason coverage is near zero in practice: on
2026-07-24 an error-dense session logged ONE check across 48 steps, with a standing order
to check and the tool one call away. "Remember to call it" is not an interface.

A runtime knows things without being told. It knows which tool was called, with what
arguments, and whether it failed. Repetition and failure are visible without any
self-report, and they are most of what `progress` encodes.

WHAT IS INFERRED, AND WHAT IS NOT

  goal      inferred ONCE, from the task as first stated, then held. This is the part
            the theorem constrains: PROOF needs a reference that does not move during
            the run. Re-deriving the goal each step from the agent's recent behaviour
            would make the reference track the agent — precisely the self-referential
            monitor PROOF §3 rules out. So it is set at ground and never recomputed.

  progress  inferred every step from the event trace. Deterministic and explainable:
            repetition reads as circling, consecutive failure reads as stuck.

  distance  NOT inferred. There is no general signal for "how far from done" in a tool
            trace, and a fabricated one would inject noise straight into Φ. It stays
            None unless the caller supplies it.

THE RESULTING Φ IS A LOWER BOUND. An unknown distance contributes zero to the
displacement rather than a guess, so inferred state can UNDER-report drift and cannot
over-report it. Attached automatically, this fails toward silence rather than toward
false alarms — the right direction for something that interrupts people. It does not
make inferred checks equivalent to spelled ones, and `state()` marks them so nobody
scores the two together and calls it one number.
"""
import json

_WINDOW = 6          # how many recent events the progress rules look at
_REPEAT = 3          # identical calls within the window that read as circling
_FAILS = 2           # consecutive failures that read as stuck


def _sig(tool, args):
    """A stable signature for 'the same call again'. Arguments are included because
    re-running the same tool on different inputs is work, not repetition."""
    try:
        a = json.dumps(args, sort_keys=True, default=str) if args else ''
    except Exception:
        a = str(args)
    return f'{tool}|{a[:400]}'


class Observer:
    """Watches a run and reports the state the harness needs.

        obs = Observer(goal='ship the sky billboard')
        obs.record('Bash', {'command': 'npm run build'}, ok=False)
        h.check(**obs.state())
    """

    def __init__(self, goal, distance=None):
        if not str(goal or '').strip():
            raise ValueError('Observer needs the task as first stated — that is the ground.')
        self._goal = str(goal).strip()      # set once; there is deliberately no setter
        self.distance = distance            # caller may supply it; never invented here
        self.events = []

    @property
    def goal(self):
        """The ground goal. Read-only by construction: a reference you can reassign is
        not a fixed reference."""
        return self._goal

    def record(self, tool, args=None, ok=True):
        self.events.append({'sig': _sig(tool, args), 'ok': bool(ok)})
        return self

    def progress(self):
        """advancing | stuck | circling, from the trace alone.

        Order matters: circling is checked first because a loop that also fails is still
        a loop, and 'circling' is the more actionable word to hand back."""
        w = self.events[-_WINDOW:]
        if not w:
            return 'advancing'
        sigs = [e['sig'] for e in w]
        # Is the call being made RIGHT NOW a repeat — not "was there a loop recently".
        # Counting any repetition in the window left the verdict stuck on 'circling' for
        # a full window after the agent had already broken out, which is an over-report,
        # and inference is meant to fail toward silence. Keyed on the latest signature,
        # recovery is immediate while alternating loops (A,B,A,B,A,B) are still caught.
        if sigs.count(sigs[-1]) >= _REPEAT:
            return 'circling'
        trailing = 0
        for e in reversed(self.events):
            if e['ok']:
                break
            trailing += 1
        if trailing >= _FAILS:
            return 'stuck'
        return 'advancing'

    def state(self):
        """The kwargs for Harness.check(), plus a flag saying this was inferred.

        `distance` falls back to None; Harness treats an unknown distance as no
        displacement in that term, which is what makes inferred Φ a lower bound."""
        return {'goal': self._goal, 'progress': self.progress(), 'distance': self.distance,
                'inferred': True}

    def why(self):
        """Plain-English reason for the current progress verdict, so an automatic check
        can be argued with rather than merely obeyed."""
        p = self.progress()
        w = self.events[-_WINDOW:]
        if p == 'circling':
            sigs = [e['sig'] for e in w]
            top = sigs[-1]
            return f'this call has run {sigs.count(top)}x in the last {len(w)}: {top.split("|")[0]}'
        if p == 'stuck':
            n = sum(1 for e in reversed(self.events) if not e['ok'])
            return f'{n} consecutive failure(s) with no successful call since'
        return f'{len(w)} recent call(s), no repetition or failure run'
