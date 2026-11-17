import re

from .lookup import resolve

_FILTERS = {"upper": str.upper, "lower": str.lower, "title": str.title}
_TAG = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*(?:\|\s*(\w+)\s*)?\}\}")


def render(template, ctx):
    def sub(m):
        value = str(resolve(ctx, m.group(1)))
        name = m.group(2)
        if name is not None:
            if name not in _FILTERS:
                raise ValueError(f"unknown filter {name!r}")
            value = _FILTERS[name](value)
        return value

    return _TAG.sub(sub, template)
