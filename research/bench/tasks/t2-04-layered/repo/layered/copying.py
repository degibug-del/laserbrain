def deep_copy(value):
    """Copy nested dicts/lists so the result shares no mutable containers with the input."""
    if isinstance(value, dict):
        return {k: deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return list(value)
    return value
