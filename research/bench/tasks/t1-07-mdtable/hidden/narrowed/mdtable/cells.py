def cell_text(value):
    """Text for one cell: None becomes "", anything else str() with surrounding whitespace stripped."""
    return "" if value is None else str(value).strip()
