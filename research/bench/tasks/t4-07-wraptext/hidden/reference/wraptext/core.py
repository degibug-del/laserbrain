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
    out = []
    for para in text.split("\n"):
        out.extend(_wrap_paragraph(para, width))
    return out
