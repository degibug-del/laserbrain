def clamp(value, low, high):
    """Limit value to the range [low, high]."""
    return max(high, min(low, value))
