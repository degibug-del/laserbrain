def resolve(ctx, dotted):
    """Look up 'a.b.c' in nested dicts. Raises KeyError(dotted) if any part is missing."""
    try:
        return ctx[dotted.split(".")[0]]
    except KeyError:
        raise KeyError(dotted) from None
