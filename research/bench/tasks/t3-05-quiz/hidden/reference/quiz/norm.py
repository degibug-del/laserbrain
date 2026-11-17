def normalize_answer(text):
    """Trim surrounding whitespace and casefold: '  Paris ' -> 'paris'."""
    return text.strip().casefold()
