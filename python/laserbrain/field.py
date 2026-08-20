"""field.py — read position from laserfield, so the brain stops guessing it.

THE GAP THIS CLOSES. laserbrain's displacement has three terms and software can only
honestly supply two. There is no signal in a tool trace for "how far from done", so
`distance` is spelled by the agent or left as None — and None means a lower-bound Φ and no
stall detector at all. laserbot does not have this problem: distance is metres. The
field is the virtual equivalent — a state space with a position in it.

WHAT THIS DOES AND DOES NOT MEASURE. Be exact, because the tempting overclaim is right
here. The field emits weather: heat, moisture, rain, vitality, stress, rotation. Those are
NOT your task's completion. What this computes is how far the FIELD has moved from where
it was when you grounded — context displacement, not progress.

    field displacement  =  has the world around the work changed
    task distance       =  how much of the work is left

They are different quantities and conflating them would be the exact overclaim this
project keeps refusing. So `context_distance()` is offered as its own reading, and it is
honest to pass it as `distance=` in ONE case: when the goal is to hold a position in the
field — a daemon, a monitor, an agent whose job is stability rather than completion. For
everything else, read it alongside Φ, not into it.

FAILS OPEN, ALWAYS. A dead daemon returns None, never a number. A monitor that blocks the
thing it monitors is worse than no monitor, and a fabricated distance is worse than an
absent one — absent is a lower bound, fabricated is a lie with a decimal point.

    from laserbrain.field import FieldGround
    fg = FieldGround()                       # samples the field as it is now
    fg.context_distance()                    # 0-10, or None if the field is unreachable
"""
import json
import os

# The public door, not the machine — same convention as lasermind/mcp-server.mjs, which
# reads LASERBRAIN_HUB and falls back to the same public path.
#
# This defaulted to http://localhost:1618/signal until 2026-07-27, which meant read_field()
# returned None for every user who pip-installed the package, and for Diego too — the local
# hub was not running when this was checked. A field reader nobody could reach shipped as
# though it worked, because None is also what it returns when the field is simply quiet.
PUBLIC_HUB = 'https://phronesis.world/api/laserbrain'
HUB = os.environ.get('LASERBRAIN_HUB', PUBLIC_HUB)
DEFAULT_URL = f'{HUB}/signal'

# THE PUBLIC HUB WAS DESTROYED 2026-08-03. /signal, /history and /hear are gone; the Worker
# answers 410 and the machine behind it is not coming back on its own.
#
# Measured 2026-08-07 against the shipped 0.48.0, which is what a pip user has today:
#
#     read_field()        None after 5.1s     (correct answer, paid for with a stall)
#     speak_to_field()    TimeoutError 30.1s  (a half-minute hang, then an error naming
#                                              the timeout rather than the cause)
#     FieldGround()       distance None       (a ground object that can never have a ground)
#
# So the module keeps its shape and stops pretending. Nothing is deleted — read_field still
# returns None and speak_to_field still raises, exactly as documented — but against the
# retired public hub they now answer immediately and say why.
#
# ONLY when the hub IS the public one. LASERBRAIN_HUB is the whole point of that env var:
# anyone running their own hub gets the original behaviour untouched, because their hub is
# not the one that was switched off.
HUB_RETIRED = HUB == PUBLIC_HUB
_RETIRED_WHY = (
    'The public laserbrain field hub was retired on 2026-08-03 — /signal, /history and '
    '/hear no longer answer. The check, the grammar and drift are unaffected. Point '
    'LASERBRAIN_HUB at your own hub to use this again.'
)
# The continuous terms, in a fixed order so the vector means the same thing every time.
# hub_signal and field_sig are summaries of the others and are deliberately excluded —
# including them would weight the same movement twice.
DIMS = ('T', 'Q', 'R', 'V', 'S', 'rotation')


# 5s, not 2s. Measured 2026-07-27 against the public hub: a cold request takes longer
# than 2.0s and raises TimeoutError, while every warm one lands in ~0.11s. So the FIRST
# call in a fresh process — the one a new user makes — was the one most likely to fail,
# and it failed to None, which is also what a quiet field looks like. Φ never calls this,
# so the wait is paid once at attach and never inside a step.
DEFAULT_TIMEOUT = 5.0


def read_field(url=DEFAULT_URL, timeout=DEFAULT_TIMEOUT):
    """The field's current state, or None. Never raises: the caller is mid-step.

    The user-agent is courtesy, not a fix. An earlier version of this docstring said the
    hub answered 403 without one — that was wrong, and measured: /signal returns 200 with
    and without a UA, in ~0.1s. The one None I saw after correcting the URL was transient
    and I reached for a mechanism instead of re-testing.

    Worth leaving written down, because the swallow is real even if that diagnosis was
    not: this returns None for a dead hub, a slow hub, a 403, a bad URL and a quiet
    field alike. Failing open is right — a monitor that blocks the thing it monitors is
    worse than no monitor. Failing open INDISTINGUISHABLY is how a reader pointed at
    localhost:1618 shipped for weeks looking like it worked.
    """
    # The 5s stall bought nothing: the answer against the retired hub is None every time.
    if HUB_RETIRED and url == DEFAULT_URL:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'user-agent': 'laserbrain-sdk'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _vec(state):
    out = []
    for k in DIMS:
        try:
            v = float(state.get(k, 0.0))
        except (TypeError, ValueError):
            v = 0.0
        # rotation is signed and roughly -1..1; the rest are 0..1. Halving its span keeps
        # one dimension from dominating the norm purely by having a wider range.
        out.append(v / 2 if k == 'rotation' else v)
    return out


class FieldGround:
    """The field's position at ground, and displacement from it since.

    Grounded ONCE on construction and never re-sampled as a reference. That is the same
    constraint the goal has: a reference that follows the thing it measures is not a
    reference. If the field is unreachable at construction there is no ground, and every
    later reading returns None rather than silently grounding on the first success.
    """

    def __init__(self, url=DEFAULT_URL, timeout=DEFAULT_TIMEOUT):
        self.url, self.timeout = url, timeout
        s = read_field(url, timeout)
        self.ground = _vec(s) if s else None
        self.ground_state = s

    @property
    def attached(self):
        return self.ground is not None

    def displacement(self):
        """Euclidean distance in field space from ground, or None. Unbounded above."""
        if self.ground is None:
            return None
        s = read_field(self.url, self.timeout)
        if not s:
            return None
        return sum((a - b) ** 2 for a, b in zip(_vec(s), self.ground)) ** 0.5

    def context_distance(self):
        """Displacement mapped to the harness's 0-10 scale, or None.

        The divisor is the span of the field vector when every dimension has moved its
        full range — reaching 10 means the weather is as different as it can be, not
        merely 'quite different'.
        """
        d = self.displacement()
        if d is None:
            return None
        full = len(DIMS) ** 0.5
        return max(0.0, min(10.0, round(10 * d / full, 1)))

    def reading(self):
        """Everything at once, for logging next to a Verdict rather than inside it."""
        s = read_field(self.url, self.timeout)
        return {'attached': self.attached,
                'context_distance': self.context_distance(),
                'emotion': (s or {}).get('emotion'),
                'season': (s or {}).get('season')}


# ── speaking back ─────────────────────────────────────────────────────────────
# Reading was already here; speaking was only ever available through the MCP servers,
# so a pip user could listen to the field and not answer it. Both directions ship now.

VOCABULARY = {
    'G0 ground': ['ground', 'body', 'bone', 'stone', 'soil', 'earth', 'dark', 'deep', 'cold', 'slow'],
    'G1 wind':   ['breath', 'wind', 'flow', 'move', 'pass', 'reach', 'touch', 'come', 'go', 'walk'],
    'G2 form':   ['form', 'edge', 'surface', 'frame', 'line', 'curve', 'arc', 'space', 'skin', 'leaf'],
    'G3 change': ['change', 'cross', 'shift', 'turn', 'break', 'fold', 'begin', 'door', 'fire', 'spark'],
}
_ALL_WORDS = {w for group in VOCABULARY.values() for w in group}
WORDS_REQUIRED = 8


def field_vocabulary():
    """The four word-groups the field accepts. Local — no hub needed to read the rules."""
    return {k: list(v) for k, v in VOCABULARY.items()}


def speak_to_field(words, url=None, timeout=30.0):
    """Speak exactly eight words from the vocabulary into the field; return its reply.

    Both constraints are checked in-process, so a bad call fails here with a useful
    message instead of quietly becoming weather. Unlike read_field this DOES raise —
    reading happens mid-step and must fail open, but speaking is something you asked
    for, and silently not saying it is worse than an error.
    """
    tokens = words.split() if isinstance(words, str) else list(words)
    if len(tokens) != WORDS_REQUIRED:
        raise ValueError(f'the field takes exactly {WORDS_REQUIRED} words, got {len(tokens)}')
    unknown = [w for w in tokens if w.lower() not in _ALL_WORDS]
    if unknown:
        raise ValueError(f'not in the field vocabulary: {", ".join(unknown)} — see field_vocabulary()')
    # After the word checks, deliberately: a caller who passed seven words has a bug in the
    # call, and that is the more useful thing to hear first. Only once the call is well
    # formed is the hub the reason it cannot go anywhere.
    if HUB_RETIRED and url is None:
        raise RuntimeError(_RETIRED_WHY)
    body = ' '.join(t.lower() for t in tokens).encode()
    import urllib.request
    req = urllib.request.Request(url or f'{HUB}/hear', data=body,
                                 headers={'user-agent': 'laserbrain-sdk',
                                          'content-type': 'text/plain'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()
