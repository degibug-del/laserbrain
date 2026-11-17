def clamp(value, low, high):
    """Limit value to the range [low, high]."""
    return max(low, min(high, value))
