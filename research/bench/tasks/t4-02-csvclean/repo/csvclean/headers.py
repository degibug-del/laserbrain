def normalize_header(name):
    """'  Unit Price ' -> 'unit_price': trim, lowercase, runs of spaces to one underscore."""
    return name.strip().lower().replace(" ", "_", 1)
