import re
import unicodedata

from ._text import collapse


def slugify(text, max_len=None):
    ascii_text = text
    s = re.sub(r"[^a-z0-9]", "-", ascii_text.lower())
    s = collapse(s, "-").strip("-")
    if max_len is not None and len(s) > max_len:
        cut = s[:max_len]
        if s[max_len] != "-" and "-" in cut:
            cut = cut[: cut.rfind("-")]
        s = cut.strip("-")
    return s
