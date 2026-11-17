from .fold import fold


def search(books, query):
    words = fold(query).split()
    if not words:
        return []
    hits = [b for b in books
            if any(w in fold(b["title"]) or w in fold(b["author"]) for w in words)]
    return sorted(hits, key=lambda b: -b["year"])
