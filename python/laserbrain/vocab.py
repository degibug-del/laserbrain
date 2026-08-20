"""vocab.py — an optional grammar for the goal term.

PROOF blesses *a* fixed reference, never a particular vocabulary. The default is
`norm()`: lowercase, strip stopwords, stem anything over four characters, then Jaccard.
That is already more than raw word overlap — inflections and function words collapse, so
"building billboards" and "build a billboard" score 1.0 and do not trip anything.

The gap that remains is SYNONYMS. "build the sky billboard" and "construct the aerial
hoarding" share no stem and score 0.0, so the default calls a faithful restatement drift.
No amount of stemming fixes that; it needs meaning, which needs a model.

(An earlier draft of this file also shipped a `stemmed_similarity`. It was removed on
sight of the numbers: it duplicated what `norm()` already does and would have implied an
improvement it did not deliver.)

Nothing here is the default. The published instrument is `norm()`; this is opt-in, so
the frozen path stays byte-identical for anyone who does not ask for something else.

    from laserbrain import Harness
    from laserbrain.vocab import embedding_similarity

    Harness(similarity=embedding_similarity())      # needs the `semantic` extra
"""


def embedding_similarity(model='all-MiniLM-L6-v2', _cache={}):
    """Cosine over sentence embeddings. Returns a `sim(a, b)` callable.

    Requires the optional extra:  pip install 'laserbrain[semantic]'

    The model loads once, on first call rather than at import, so importing laserbrain
    stays fast and offline for everyone who never uses this.
    """
    def sim(a, b):
        st = _cache.get('st')
        if st is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError(
                    "embedding_similarity needs sentence-transformers. Install the extra:\n"
                    "    pip install 'laserbrain[semantic]'\n"
                    "The default grammar needs no dependency and handles inflections already;\n"
                    "reach for this when your agents restate goals in different WORDS."
                ) from e
            st = _cache['st'] = SentenceTransformer(model)
        va, vb = st.encode([str(a or ''), str(b or '')])
        num = float(sum(p * q for p, q in zip(va, vb)))
        na = float(sum(p * p for p in va)) ** 0.5
        nb = float(sum(q * q for q in vb)) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        # cosine is -1..1; the goal term wants 0..1, and a negative cosine means
        # "unrelated" here rather than "opposite", so it floors at 0.
        return max(0.0, num / (na * nb))

    return sim
