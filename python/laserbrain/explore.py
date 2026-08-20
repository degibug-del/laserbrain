"""The second instrument — for work whose goal is supposed to move.

    from laserbrain import Search

    s = Search()
    s.ground('design phronesis.world in the mode of the 1950s New Look')
    s.ground('show laserbrain modes chosen for how fast they teach')
    print(s.reading())        # searching · novelty 0.86 · 2 grounds

laserbrain measures displacement from a reference that cannot move. That is the right
measure for execution and the wrong one for exploration, where moving the goal IS the
work — which is why a productive day of redirection scores Φ 0.55 and the reading is
worth nothing. This measures the other mode.

WHAT IS INVARIANT WHEN THE GOAL IS NOT. Four things, none of which need a fixed ground:

    novelty      is this ground new, or somewhere you have already been?
    commitment   was the last ground worked, or abandoned on sight?
    revisiting   does this ground overlap one you already left?
    narrowing    is novelty falling — is the search closing in?
    temperature  how energetically is the path moving, taken across the window?

The last is the only one that is not a property of a ground. It is a property of the
PATH — undefined for a single ground the way temperature is undefined for a single
molecule — and it is reported rather than thresholded. No verdict depends on it.

A search is not failing because it changed direction. It is failing when it returns to
ground it already abandoned, when it abandons ground faster than it can learn anything,
or when it never narrows. Those are measurable and none of them is displacement.

THE SEAM. `settled` is the terminal reading: novelty near zero and commitment rising
means the exploration has become a task, and a task is what laserbrain is for. The two
instruments hand off to each other — `reground` is the seam from the execution side and
`settled` is the seam from this one.

Deliberately no valence, like the harness. `revisiting` is not bad, it is a fact about
the path. What to do about it is yours.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _f

from . import _G, norm


@dataclass
class Reading:
    reason: str
    novelty: float
    commitment: float
    revisit: float
    grounds: int
    advice: str
    trail: str | None = None
    # Mean novelty across the window — the ENSEMBLE reading. None until an ensemble
    # exists, which is the whole content of the measure: a single ground has no
    # temperature for the same reason a single molecule has none. Not 'too small to
    # measure' — undefined. See Search.temperature.
    temperature: float | None = None

    def __str__(self) -> str:                       # pragma: no cover - display only
        t = '' if self.temperature is None else f' · T {self.temperature:.2f}'
        return f'{self.reason} · novelty {self.novelty:.2f} · {self.grounds} grounds{t}'


def trailscore(goals) -> str | None:
    """The written form: the accumulated territory, sorted, with the ground count.

    The harness's laserscore writes ONE state. A search has no one state — it has a path,
    so what gets written is the union of everywhere it has been. Null before the first
    ground, for the same reason a laserscore is null when nothing can be spelled.
    """
    if not goals:
        return None
    seen = set()
    for g in goals:
        seen |= norm(g)
    return f'⟨{"|".join(sorted(seen))}⟩ ×{len(goals)}'


def _frame(window) -> int:
    """Validate a window, refusing silent truncation.

    The frame moves the reading — the same trail reads 0.28 to 0.65 depending on it — so
    a window quietly rounded to something the caller did not ask for is a wrong answer
    with no symptom. `Search(window=n/2)` truncating 2.9 to 2 was accepted before this
    existed, and the caller would never learn the frame was not the one they computed.

    A float that IS a whole number (4.0) is fine — that is the same frame written
    differently, not a different one.
    """
    if isinstance(window, bool) or not isinstance(window, (int, float)):
        raise TypeError(
            f'window must be a whole number of grounds, got {type(window).__name__} '
            f'({window!r}). It is a count of grounds, not a label.')
    if isinstance(window, float) and not window.is_integer():
        raise ValueError(
            f'window must be a whole number of grounds, got {window}. Truncating it here '
            f'would silently read a frame you did not ask for, and the frame moves the '
            f'reading — pass {int(window)} or {int(window) + 1} explicitly.')
    w = int(window)
    if w < 2:
        raise ValueError(
            f'window must be at least 2, got {w}. A window of 1 would make temperature '
            'the novelty of one ground — a property of a component, which is the thing '
            'an ensemble reading is not.')
    return w


class Search:
    """A moving reference, measured. The counterpart to Harness."""

    # From grammar.calibration.explore, with the literals as last-known-good fallbacks —
    # the same pattern Harness uses. Written down there rather than here because three of
    # these four share a value with a harness constant and only TWO share the meaning:
    # revisit_min IS collision_min's idea across time, window IS stall_window's idea, and
    # settled_max merely happens to equal self_report_min. The grammar says which is which
    # so nobody unifies the third.
    _E = (_G.get('calibration') or {}).get('explore') or {}
    # A ground abandoned in fewer steps than this was not worked, it was glanced at.
    MIN_COMMITMENT = int(_E.get('min_commitment', 2))
    # Overlap with an already-abandoned ground that counts as being back where you were.
    REVISIT_MIN = float(_E.get('revisit_min', 0.60))
    # Novelty below this means the search has stopped finding new territory.
    SETTLED_MAX = float(_E.get('settled_max', 0.15))
    WINDOW = int(_E.get('window', 4))

    def __init__(self, window: int | None = None):
        """`window` is the FRAME every windowed reading is taken in.

        Left alone it is the published calibration (grammar.calibration.explore.window),
        and that is the number the thresholds below were tuned against. Setting it is a
        CALIBRATION CHANGE, not a display option: `settled`, `narrowing` and `thrashing`
        all read this window, so a different one moves when they fire. That is allowed
        and it is deliberate — the frame is a choice and pretending otherwise would hide
        it — but it means a run at window 8 and a run at window 4 are not comparable,
        and neither is comparable to the corpus.

        To read ANOTHER frame without moving this one, pass a window to temperature()
        instead. An observer can compute what a different frame would see without
        changing frames.

        Below 2 is refused. A window of 1 makes `temperature` the novelty of a single
        ground, which is precisely the category error the measure exists to refuse: one
        ground has a novelty and does not have a temperature.
        """
        if window is not None:
            window = _frame(window)
            # Shadows the class attribute, so every existing self.WINDOW reference —
            # settled, narrowing, thrashing, temperature — picks this up with no other
            # change. One frame for the whole instrument, never a mix.
            self.WINDOW = window
        self.goals: list[str] = []
        self.tokens: list[set] = []
        self.steps: list[int] = []          # steps spent on each ground
        self.novelty: list[float] = []
        self._seen: set = set()

    # ── the two calls ─────────────────────────────────────────────────────────
    def step(self):
        """One unit of work on the current ground. Optional, but commitment needs it."""
        if self.steps:
            self.steps[-1] += 1

    def ground(self, goal: str) -> Reading:
        """Declare a new ground. This is the move laserbrain calls drift."""
        t = norm(goal)
        # novelty is measured against everywhere the search has been, not against the
        # last ground — returning to step 2 from step 9 is not novel just because step 9
        # was different.
        new = t - self._seen
        novelty = (len(new) / len(t)) if t else 0.0

        # Overlap with the ground you are LEAVING is not revisiting — it is staying, or
        # restating. Only ground you already walked away from counts, which is why the
        # immediately previous one is excluded from this loop. Without that exclusion,
        # holding one goal reads as returning to it, and `settled` can never fire because
        # `revisiting` always wins first.
        staying = 0.0
        if self.tokens:
            last = self.tokens[-1]
            if t or last:
                staying = len(t & last) / len(t | last)
        revisit = 0.0
        if staying < self.REVISIT_MIN:              # you actually left before coming back
            for prev in self.tokens[:-1]:           # everything already ABANDONED
                if t or prev:
                    j = len(t & prev) / len(t | prev)
                    revisit = max(revisit, j)

        prev_commit = self.steps[-1] if self.steps else 0
        self.goals.append(goal)
        self.tokens.append(t)
        self.steps.append(1)
        self.novelty.append(novelty)
        self._seen |= t
        return self._read(novelty, revisit, prev_commit)

    # ── the reading ───────────────────────────────────────────────────────────
    def _read(self, novelty: float, revisit: float, prev_commit: float) -> Reading:
        n = len(self.goals)
        score = trailscore(self.goals)
        # Attached to every reading and decisive in none of them. The verdicts below
        # are identical to what they were before temperature existed.
        temp = self.temperature()
        mk = lambda r, a: Reading(r, novelty, prev_commit, revisit, n, a, score, temp)

        if n == 1:
            return mk('opened', 'First ground. Everything from here is measured against the path, not against this.')

        # Order matters and is the definition. Revisiting is checked first because it is
        # the one failure that looks like progress from inside: a new goal, freshly
        # spelled, that you have already explored and left.
        if revisit >= self.REVISIT_MIN:
            return mk('revisiting', f'This ground overlaps one you already left ({revisit:.0%}). '
                                    'You have been here. Either finish it or say why it is different.')

        recent = self.steps[-(self.WINDOW + 1):-1]
        if len(recent) >= self.WINDOW and all(s < self.MIN_COMMITMENT for s in recent):
            return mk('thrashing', f'{len(recent)} grounds in a row abandoned after one step. '
                                   'Nothing was worked long enough to learn whether it was wrong.')

        window = self.novelty[-self.WINDOW:]
        if len(window) >= self.WINDOW and max(window) <= self.SETTLED_MAX:
            return mk('settled', 'Novelty has gone. The search has become a task — '
                                 'ground it in Harness and let laserbrain hold it.')

        if len(window) >= self.WINDOW and window[-1] < window[0]:
            return mk('narrowing', f'Novelty falling ({window[0]:.2f} → {window[-1]:.2f}). '
                                   'The search is closing in.')

        return mk('searching', f'New ground, {novelty:.0%} of it unvisited. The path is still opening.')

    def reading(self) -> Reading:
        """The current reading without declaring a new ground."""
        if not self.goals:
            return Reading('unopened', 0.0, 0.0, 0.0, 0, 'No ground yet.', None)
        return self._read(self.novelty[-1], 0.0, self.steps[-1])

    def temperature(self, window: int | None = None) -> float | None:
        """How energetically the search is moving — mean novelty across the window.

        AN ENSEMBLE PROPERTY, AND THAT IS THE POINT. Temperature is not a property a
        component can have: no single molecule has one, and asking for it is a category
        error rather than a hard measurement. The same holds here. One ground has a
        novelty; it does not have a temperature. Only a path does. So this returns None
        until the window is full, and None means undefined rather than zero — the same
        distinction claims['grounded'] draws, for the same reason.

        Novelty is the per-ground analogue of a particle's kinetic energy, so the mean
        over the window is the honest mapping. 0.0 is frozen — the search has stopped
        finding new territory. 1.0 is every ground entirely unvisited.

        FRAME-DEPENDENT, AND THERE IS NO TRANSFORMATION LAW. The same trail read at
        windows 2, 3, 4, 6, 8 and 9 gives 0.42, 0.28, 0.46, 0.64, 0.60, 0.65 — a 2.3x
        spread, and NOT monotonic in the window. Narrower is not colder: the reading
        depends on the window's width and on where it lands relative to the structure of
        the trail, so there is no single parameter to transform between frames with. What
        every frame agrees on is the novelty sequence itself, the ground count and the
        territory — territory() reports those, and reports this number's frame beside it,
        because a temperature without its window does not mean anything.

        Pass `window` to read another frame without moving this instrument's own.

        WHY IT IS NOT ANOTHER VERDICT. The existing readings threshold this distribution
        at its EXTREMES: settled fires on max(window) <= SETTLED_MAX, narrowing on the
        first and last values. Neither reports the middle, and the middle is a different
        fact — a window can hold one very hot ground among cold ones and read neither
        settled nor narrowing while its temperature is low. Reported, never folded into
        a verdict: no reading below changes because this exists.
        """
        w = self.WINDOW if window is None else _frame(window)
        recent = self.novelty[-w:]
        if len(recent) < w:
            return None
        return round(sum(recent) / len(recent), 2)

    def territory(self) -> dict:
        """What the search has covered, for logging beside a Verdict rather than inside it."""
        return {'grounds': len(self.goals), 'tokens': len(self._seen),
                'trailscore': trailscore(self.goals),
                'novelty': [round(x, 2) for x in self.novelty],
                # The frame, beside the number. A temperature quoted without its window
                # is not a reading anyone can reproduce or compare.
                'temperature': self.temperature(),
                'window': self.WINDOW,
                'steps': list(self.steps)}
