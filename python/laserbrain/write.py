"""laserbrain AI — the harness as a decoder.

    from laserbrain import Writer

    w = Writer().train(documents)
    print(w.write('nothingness is the ground state', words=60))

WHAT THIS IS, EXACTLY. The language model is an n-gram chain — trigram with backoff,
about forty lines, no weights and no dependencies. That part is deliberately the dumbest
thing that works, because it is not the idea. The idea is the decoder: at every word the
candidates are scored by model probability AND by displacement from a fixed ground, and
the one that keeps the text on its goal wins.

That is x = [x, f(x)] as a generator. The next word depends on a measurement of the text
already written, so the state includes the reading of itself. An ordinary chain wanders
because nothing measures where it has got to; this one cannot wander far, because Φ is
computed against a ground that does not move and the sampler pays for distance.

WHAT IT IS NOT. Not a transformer, not trained weights, not a claim about fluency. An
n-gram model produces n-gram prose and no amount of steering fixes that. What is being
demonstrated is that a drift instrument can serve as a decoding constraint — the same
mechanism that stops an agent wandering off a task, applied to a sentence. If that works
on a chain this simple it works on anything, and it can be checked by reading, which is
the point.

STEERING IS OFF BY DEFAULT (`pull=0.0` gives you the plain chain), so the difference the
harness makes is something you can see rather than something you take on trust.
"""
from __future__ import annotations

import random
import re
from collections import Counter, defaultdict

from . import norm

_WORD = re.compile(r"[A-Za-z0-9'’\-]+|[.,;:!?]")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text)


class Writer:
    """An n-gram chain whose sampler is a drift instrument."""

    def __init__(self, order: int = 3, seed: int | None = None):
        self.order = max(2, order)
        self.rnd = random.Random(seed)
        self.model: dict[tuple, Counter] = defaultdict(Counter)
        self.starts: list[tuple] = []
        self.vocab = 0
        self.trained_on = 0

    # ── training ──────────────────────────────────────────────────────────────
    def train(self, documents) -> 'Writer':
        """Count n-grams over any iterable of strings. Idempotent-ish: call it again to add."""
        seen = set()
        for doc in documents:
            toks = _tokens(doc)
            if len(toks) <= self.order:
                continue
            self.trained_on += 1
            seen.update(toks)
            for i in range(len(toks) - self.order):
                ctx = tuple(toks[i:i + self.order - 1])
                self.model[ctx][toks[i + self.order - 1]] += 1
                # A start is any context beginning a sentence, so generation opens
                # somewhere a human would, not mid-clause.
                if i == 0 or toks[i - 1] in '.!?':
                    self.starts.append(ctx)
        self.vocab = len(seen)
        return self

    # ── the decoder ───────────────────────────────────────────────────────────
    def _candidates(self, ctx: tuple) -> Counter:
        """Trigram, backing off to bigram, then to anything. Backoff keeps it unstuck."""
        c = self.model.get(ctx)
        if c:
            return c
        for k in range(1, len(ctx)):
            c = self.model.get(ctx[k:])
            if c:
                return c
        return self.model[self.rnd.choice(list(self.model))] if self.model else Counter()

    def write(self, ground: str, words: int = 60, pull: float = 1.0, top_k: int = 24) -> str:
        """Generate text held to `ground`.

        `pull` is how much the instrument is allowed to steer: 0.0 is the bare chain,
        1.0 weights model probability and groundedness about evenly. The ground is fixed
        for the whole run — it is a reference, and a reference that moved with the text
        would measure nothing, which is the same reason Harness will not revise a goal
        mid-run.
        """
        if not self.model:
            raise RuntimeError('train() first')
        target = norm(ground)
        # Open somewhere the ground actually points. Starting from a random sentence in a
        # 1,028-document corpus discards the goal before the first word, and no amount of
        # per-token steering recovers a passage that began three papers away.
        pool = self.starts or list(self.model)
        if pull > 0 and target:
            near = [c for c in pool if norm(' '.join(c)) & target]
            if near:
                pool = near
        ctx = self.rnd.choice(pool)
        out = list(ctx)

        for _ in range(words):
            cand = self._candidates(ctx)
            if not cand:
                break
            top = cand.most_common(top_k)
            total = sum(n for _, n in top) or 1

            if pull <= 0:
                choice = self.rnd.choices([w for w, _ in top], [n for n, in ((n,) for _, n in top)])[0]
            else:
                # Φ's goal term, computed per candidate: how much of the ground does the
                # text cover once this word is added? Lower displacement scores higher.
                here = norm(' '.join(out[-40:]))
                weights = []
                for w, n in top:
                    after = here | norm(w)
                    overlap = (len(after & target) / len(after | target)) if (after or target) else 0.0
                    prob = n / total
                    weights.append(prob * (1.0 + pull * overlap * 8))
                choice = self.rnd.choices([w for w, _ in top], weights)[0]

            out.append(choice)
            ctx = tuple(out[-(self.order - 1):])
            if choice in '.!?' and len(out) >= words * 0.7:
                break

        return self._detokenise(out)

    @staticmethod
    def _detokenise(toks: list[str]) -> str:
        s = ''
        for t in toks:
            s += t if (t in '.,;:!?' or not s) else ' ' + t
        return s[:1].upper() + s[1:]

    # ── the reading ───────────────────────────────────────────────────────────
    def grounding(self, text: str, ground: str) -> float:
        """How much of the ground the text covers, 0..1.

        Coverage, not Jaccard. Jaccard between a 55-word passage and a five-token ground
        cannot exceed about 0.17 however well it stays on topic, because the union is
        mostly text — so it reads as ~0 for everything and hides the difference it is
        supposed to show. What matters here is how much of the GROUND got touched.
        """
        a, b = norm(text), norm(ground)
        return (len(a & b) / len(b)) if b else 0.0
