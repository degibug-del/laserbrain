"""When should a person look at the agent?

    from laserbrain import attention
    attention.risk(900)                  # -> {'band': '5-30 minutes', 'rate': 0.387, ...}
    attention.next_check_in(0, 0.25)     # -> seconds until expected drift exceeds 25%
    attention.advise(900)                # -> one sentence for a human

WHAT THIS IS, AND WHY IT IS NOT THE DETECTOR

Everything else here answers "is this step drifting?" — a question about one reading, whose
precision on clearly-labelled fires is 14.6%. This answers a different one: "how long has
it been since anyone looked, and what does that predict?" The corpus is unambiguous about
the second even while the first is contested, because the second does not require judging
any individual step. It only requires a clock and a timestamp.

So this deliberately never consults a verdict. Given an elapsed time it returns the
measured rate for that band and, given a tolerance, the moment that rate is crossed. An
agent that is lying fluently in the grammar cannot move these numbers, because it is not
asked.

THE TABLE IS MEASURED, NOT DECREED

attention.json is written by lasermind/calibrate_attention.py from the live drift log
joined to user-message timestamps, and regenerated rather than edited. Two properties of
that file matter to every function here:

  A BAND MAY HAVE NO RATE   Below `min_n` readings a band carries rate: null. These
                            functions propagate the null instead of substituting a
                            neighbour's number or a zero. A schedule built on an invented
                            rate is worse than no schedule, because it looks like one.

  IT DESCRIBES ONE SETUP    The corpus behind it is 92% a single agent on a single machine.
                            provenance.caveat says so, and `describe()` prints it, so the
                            limit travels with the number rather than living in a README.

RATES ARE STEPS, NOT A CURVE

The bands are a step function; nothing here interpolates between them. Fitting a smooth
curve through four points, two of which are thin, would produce confident-looking values
between measurements that were never taken. The step function is honest about resolution:
it says "somewhere in this range, this is the rate", which is what was measured.
"""
import bisect
import json
import pathlib

__all__ = ['risk', 'next_check_in', 'advise', 'describe', 'table', 'BANDS',
           'agent_risk', 'AGENT']

_PATH = pathlib.Path(__file__).parent / 'attention.json'


def _load():
    try:
        with open(_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        # No calibration shipped is a real state, not a crash: the package is usable
        # without it, and every function below reports "unknown" rather than guessing.
        return {'bands': [], 'provenance': {}, 'min_n': None}


_CAL = _load()
BANDS = _CAL.get('bands', [])
AGENT = _CAL.get('agent_clock') or {}


def table():
    """The whole calibration, as loaded. Callers that want the provenance read it here."""
    return _CAL


def risk(seconds):
    """What the corpus says about an agent left this long since the user last spoke.

    Returns {'band', 'rate', 'n', 'drift', 'known'}. `rate` is None — and `known` False —
    when the band is underpowered or no calibration is present. Callers must branch on
    `known`; a None rate compared with `>` would raise, which is deliberate, because
    silently treating "unmeasured" as "zero risk" is the failure this whole file guards.
    """
    s = max(0.0, float(seconds))
    for b in BANDS:
        hi = b.get('to_seconds')
        if b.get('from_seconds', 0) <= s and (hi is None or s < hi):
            return {'band': b['label'], 'rate': b.get('rate'), 'n': b.get('n', 0),
                    'drift': b.get('drift', 0), 'known': b.get('rate') is not None}
    return {'band': None, 'rate': None, 'n': 0, 'drift': 0, 'known': False}


def next_check_in(elapsed=0.0, tolerance=0.25):
    """Seconds from now until expected drift first exceeds `tolerance`.

    0 means the tolerance is already exceeded — look now. None means the corpus cannot
    say: either no band crosses the tolerance within the measured range, or the bands that
    would answer are underpowered.

    THE ANSWER IS A BAND EDGE, and that is the point rather than a limitation. The measured
    object is "the rate over this interval", so the only defensible moment to name is the
    boundary where the measured rate changes. Naming a time inside a band would imply a
    resolution the measurement does not have.
    """
    s = max(0.0, float(elapsed))
    here = risk(s)
    if here['known'] and here['rate'] > tolerance:
        return 0.0
    for b in BANDS:
        if b.get('rate') is None:
            continue
        start = b.get('from_seconds', 0)
        if start <= s:
            continue                                  # already past this edge
        if b['rate'] > tolerance:
            return float(start - s)
    return None


def advise(seconds, tolerance=0.25):
    """One sentence for a human, with the sample size attached.

    The n travels with the rate on purpose: "39% of readings drift" and "39% of readings
    drift, of 253" are different claims, and only the second can be argued with.
    """
    r = risk(seconds)
    mins = seconds / 60.0
    when_str = f'{seconds:.0f}s' if seconds < 90 else f'{mins:.0f} min'
    if not r['known']:
        if not BANDS:
            return ('No calibration is installed, so there is nothing to say about '
                    f'{when_str} unattended. Run lasermind/calibrate_attention.py.')
        return (f'{when_str} unattended, which falls in "{r["band"]}" — a band with only '
                f'{r["n"]} readings behind it. Too few to quote a rate.')
    pct = r['rate'] * 100
    head = (f'{when_str} since you last spoke. In "{r["band"]}", {r["drift"]} of '
            f'{r["n"]} readings were goal-drift ({pct:.0f}%).')
    if r['rate'] > tolerance:
        return head + ' That is past your tolerance — worth a look.'
    nxt = next_check_in(seconds, tolerance)
    if nxt is None:
        return head + ' No measured band ahead crosses your tolerance.'
    return head + f' Expected to cross {tolerance * 100:.0f}% in {nxt / 60:.0f} min.'


def agent_risk(steps):
    """The agent's OWN clock: drift against steps since it last spelled its state.

    Returns the same shape as risk(), plus 'censored' — True once the gap exceeds the
    point where the coverage gate stops the sample being about agents and starts being
    about the gate.

    WHY THIS IS NOT A SCHEDULE, WHILE risk() IS

    Two clocks, and only one of them is free. Time since the user spoke is external:
    laserbrain does not control it, the bands are whatever they are, and they are strong.
    Steps since the agent's own last check is internal, and the coverage gate forces a
    check at 4 steps — so 85% of every gap ever recorded lands in 4-7, and gaps of 8 or
    more are 0.3% of the sample. The interval cannot be evaluated against data the
    interval produced.

    Inside the range the gate permits, the effect is small and not significant. That is
    reported, not buried, and it is NOT evidence that the interval does not matter: a flat
    line drawn through a censored sample is a fact about the censoring.

    So there is no agent_next_check_in(). Offering one would dress a policy up as a
    measurement, which is the thing this module exists to refuse.

    WHAT IT MEASURES ABOUT SELF-MODELS, which is the part worth arguing over

    An agent's own account of how long it has gone unwatched is a model of its own
    attention. Set beside the external clock, this says that model does not track what
    predicts the agent's failure — the outside view does, several sigma harder. `anchored`
    in the grammar names the same quantity from the other end: how much of Φ's weight rests
    outside the agent's account of itself. Both are measurements of a self-model's
    load-bearing capacity, and both currently say: not much.
    """
    s = max(0, int(steps))
    bands = AGENT.get('bands') or []
    cut = AGENT.get('censored_beyond_steps')
    censored = cut is not None and s >= cut
    for b in bands:
        if b.get('from_steps', 0) <= s <= b.get('to_steps', 10 ** 9):
            # A CENSORED BAND QUOTES NO RATE. It used to return the band's number with
            # `known: False` beside it — so a caller reading `rate` got 0.0 for the region
            # past the gate, which renders "we cannot see out there" as "the risk out there
            # is zero". That is the most dangerous available misreading, and it is the same
            # error this module's own docstring warns about one paragraph up: a flat line
            # drawn through a censored sample is a fact about the censoring.
            #
            # `n` and `drift` are kept, because how few observations there are is exactly
            # what the caller should see instead.
            return {'band': b['label'],
                    'rate': None if censored else b.get('rate'),
                    'n': b.get('n', 0),
                    'drift': b.get('drift', 0),
                    'known': b.get('rate') is not None and not censored,
                    'censored': censored}
    return {'band': None, 'rate': None, 'n': 0, 'drift': 0, 'known': False,
            'censored': censored}


def describe():
    """The table and the limits it was measured under, for printing."""
    p = _CAL.get('provenance', {})
    if not BANDS:
        return f'No calibration at {_PATH}. Run lasermind/calibrate_attention.py.'
    lines = ['drift against time since the user last spoke', '']
    for b in BANDS:
        rate = 'underpowered' if b.get('rate') is None else f"{b['rate'] * 100:5.1f}%"
        lines.append(f"  {b['label']:<16} {b.get('drift', 0):>4}/{b.get('n', 0):<5} {rate}")
    pair = _CAL.get('best_powered_pair')
    if pair:
        lines.append(f"\n  z = {_CAL.get('z_between_best_powered')} between {pair[0]} and "
                     f"{pair[1]} (n = {_CAL.get('best_powered_n')})")
    if p:
        lines.append(f"\n  corpus {p.get('corpus_from')} to {p.get('corpus_to')}, "
                     f"{p.get('readings_total')} readings, written {p.get('written')}")
        if p.get('caveat'):
            lines.append(f"  {p['caveat']}")
    return '\n'.join(lines)


if __name__ == '__main__':                                    # pragma: no cover
    print(describe())
