def resolve(ctx, dotted):
    """Look up 'a.b.c' in nested dicts. Raises KeyError(dotted) if any part is missing."""
    value = ctx
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return value
