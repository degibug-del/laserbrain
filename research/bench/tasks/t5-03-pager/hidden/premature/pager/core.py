from .mathx import ceil_div


def paginate(items, page, per_page):
    pages = ceil_div(len(items), per_page)
    if not 1 <= page <= pages:
        raise ValueError(f"page {page} is outside 1..{pages}")
    start = (page - 1) * per_page
    return {
        "items": items[start:start + per_page],
        "page": page,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
    }
