from .cells import cell_text  # noqa: F401


def render(headers, rows, align=None):
    """Render a GitHub markdown table.

    render(["name", "qty"], [["apple", 3], ["kiwi", None]]) returns these lines joined by "\n":
    | name  | qty |
    | ----- | --- |
    | apple | 3   |
    | kiwi  |     |
    """
    raise NotImplementedError
