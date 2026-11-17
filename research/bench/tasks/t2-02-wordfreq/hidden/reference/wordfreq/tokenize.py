import re

_WORD = re.compile(r"(?:[^\W_]|')+")


def split_words(text):
    """Lowercase words: runs of letters, digits and apostrophes; leading/trailing apostrophes stripped."""
    words = (w.strip("'") for w in _WORD.findall(text.lower()))
    return [w for w in words if w]
