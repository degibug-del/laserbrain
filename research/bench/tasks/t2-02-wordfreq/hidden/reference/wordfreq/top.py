from collections import Counter

from .tokenize import split_words


def top(text, n=10, stopwords=None):
    stop = {w.lower() for w in stopwords} if stopwords else set()
    counts = Counter(w for w in split_words(text) if w not in stop)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
