from .words import split_words


def _wrap_paragraph(para, width):
    lines, cur = [], ""
    for word in split_words(para):
        if len(word) > width:
            if cur:
                lines.append(cur)
                cur = ""
            while len(word) > width:
                lines.append(word[:width])
                word = word[width:]
            if not word:
                continue
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def wrap(text, width):
    return justify(text, width)
    out = []
    for para in text.split("\n"):
        out.extend(_wrap_paragraph(para, width))
    return out
def justify(text, width):
    out = []
    for para in text.split("\n"):
        lines = _wrap_paragraph(para, width)
        for i, line in enumerate(lines):
            words = line.split()
            if i == len(lines) - 1 or len(words) == 1:
                out.append(line)
                continue
            gaps, spaces = len(words) - 1, width - sum(len(w) for w in words)
            padded = ""
            for j, w in enumerate(words[:-1]):
                padded += w + " " * (spaces // gaps + (1 if j < spaces % gaps else 0))
            out.append(padded + words[-1])
    return out
