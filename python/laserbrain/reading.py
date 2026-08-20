"""The second term for a spectral reading — what shape a piece of text is in.

    from laserbrain import lexical_variety, shape_of

    lexical_variety('the same thought the same thought the same thought')  -> 0.33
    shape_of(connectivity=0.16, variety=0.33, word_count=40)               -> 'circling'

WHY A SECOND TERM AT ALL

The spectral score phronesis computes is algebraic connectivity of a discourse graph. It is
not coherence in the everyday sense, and REPETITION RAISES IT. Measured against the live
analyzer:

    a clear, considered question ......... 21
    deliberately circling text ........... 16
    "the the the the the the" ............ 36
    word salad ........................... 99

Reported as "coherence", that tells someone circling one thought that their writing is
perfect — backwards, and worst for exactly the person most likely to be writing that way.

Variety separates the two cases. A tight argument reuses its key terms deliberately: high
connectivity, high variety. Circling reuses everything: high connectivity or low, but
always low variety. Neither number means much alone; the pair does.

WHY THIS FILE EXISTS, WHICH IS THE PART WORTH READING

The definition lived in ONE place — phronesis-world/lib/reading.ts — where /studio,
/clarity and /api/ai all share it, and its own docstring says three private copies is how
definitions drift apart. It was right about that and it did not go far enough: the harness
had no copy at all. `laserbrain` could tell you a run was circling and could not tell you
a paragraph was, which is the same measurement on a different subject.

So this is a port, and a port is a second copy. The repo already knows what that costs —
the normaliser is four copies with a parity gate, the drift rule is four with another. This
one gets scripts/check-reading-parity.mjs, which drives both implementations over shared
vectors and fails if they disagree on a single one. A rule kept in two places diverges; the
only question is whether anything notices.

WHAT IS DELIBERATELY NOT HERE

Connectivity. That is a spectral computation over a discourse graph and it belongs to the
analyzer that serves /api/spectral/analyze. This file takes it as an argument and does not
pretend to compute it, which is also why `shape_of` cannot be called with text alone.
"""
import re

# Kept byte-identical to the set in lib/reading.ts. Ordered as written there so a diff
# between the two files is readable, not alphabetised into a different-looking list.
STOPWORDS = frozenset([
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'of', 'is', 'are', 'it', 'i',
    'my', 'me', 'that', 'this', 'so', 'for', 'be', 'was', 'were', 'has', 'have', 'had', 'not',
    'no', 'do', 'does', 'did', 'if', 'then', 'than', 'they', 'them', 'their', 'you', 'your', 'we',
    'our', 'he', 'she', 'his', 'her', 'as', 'with', 'by', 'from', 'about', 'into', 'more', 'most',
    'some', 'any', 'all', 'can', 'will', 'would', 'should', 'could', 'been', 'being', 'which',
    'when', 'where', 'what', 'how', 'why', 'there', 'here',
])

#: Below this, the same handful of words is doing all the work.
CIRCLING_VARIETY = 0.55

#: Under this many words there is not enough text to read a shape from.
SHORT_WORDS = 12

_WORD = re.compile(r"[a-z']+")


def lexical_variety(text: str) -> float:
    """Distinct content words as a fraction of content words.

    Stopwords are dropped because "the" recurring says nothing about whether someone is
    circling, and tokens of three characters or fewer go with them for the same reason.

    Returns 1.0 for empty input — nothing written is not evidence of repetition. That is a
    real case, not a guard: an empty ask arrives at /studio every day.
    """
    words = [w for w in _WORD.findall((text or '').lower())
             if w not in STOPWORDS and len(w) > 2]
    return (len(set(words)) / len(words)) if words else 1.0


def shape_of(connectivity: float, variety: float, word_count: int) -> str:
    """What a connectivity/variety pair actually supports saying.

    One of 'short', 'circling', 'connected', 'loose'. Deliberately narrow: these describe
    the text's shape, not its quality, because the underlying number does not carry quality.

    CIRCLING IS DETECTED ON VARIETY ALONE, and the first version of this got it wrong in an
    instructive way. It also required high connectivity, a condition lifted from a note
    about `analyzeWindowed` — a DIFFERENT analyzer from the one serving
    /api/spectral/analyze. Against the live one, circling scores LOW connectivity (16
    against a clear question's 21), so the extra condition meant the rule never fired on
    the one thing it existed to catch.

    Connectivity is still taken and still reported, because it is what the endpoint
    measures. It simply is not load-bearing for this judgement.
    """
    if word_count < SHORT_WORDS:
        return 'short'
    if variety < CIRCLING_VARIETY:
        return 'circling'
    if connectivity > 0.7:
        return 'connected'
    return 'loose'


def read(text: str, connectivity: float = 0.0) -> dict:
    """The whole reading of one piece of text, as the CLI and the MCP tool return it.

    `connectivity` defaults to 0 rather than being required: the spectral term needs the
    analyzer endpoint, and the variety term — the one that catches circling — needs nothing
    but the text. A reading with no connectivity is honest and useful; refusing to give one
    without a network call would not be.
    """
    words = _WORD.findall((text or '').lower())
    variety = lexical_variety(text)
    return {
        'words': len(words),
        'variety': round(variety, 4),
        'connectivity': connectivity,
        'shape': shape_of(connectivity, variety, len(words)),
        'circling': variety < CIRCLING_VARIETY and len(words) >= SHORT_WORDS,
    }
