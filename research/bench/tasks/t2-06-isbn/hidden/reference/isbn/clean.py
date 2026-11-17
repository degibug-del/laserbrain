def normalize(text):
    """Remove hyphens and spaces and uppercase a trailing x: '0-306-40615-2' -> '0306406152'."""
    return text.replace("-", "").replace(" ", "").upper()
