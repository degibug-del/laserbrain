from .cells import cell_text

_SEP = {
    "l": lambda w: ":" + "-" * (w - 1),
    "r": lambda w: "-" * (w - 1) + ":",
    "c": lambda w: ":" + "-" * (w - 2) + ":",
    None: lambda w: "-" * w,
}
_PAD = {"l": str.ljust, "r": str.rjust, "c": str.center, None: str.ljust}


def _esc(text):
    return text


def render(headers, rows, align=None):
    head = [_esc(cell_text(h)) for h in headers]
    body = [[_esc(cell_text(c)) for c in row] for row in rows]
    n = len(head)
    aligns = list(align) if align else [None] * n
    widths = [max([3, len(head[i])] + [len(r[i]) for r in body]) for i in range(n)]

    def line(cells):
        return "| " + " | ".join(_PAD[aligns[i]](cells[i], widths[i]) for i in range(n)) + " |"

    sep = "| " + " | ".join(_SEP[aligns[i]](widths[i]) for i in range(n)) + " |"
    return "\n".join([line(head), sep] + [line(r) for r in body])
