from .fold import fold


def search(books, query):
    words = fold(query).split()
    if not words:
        return []
    hits = []
    for book in books:
        title, author = fold(book["title"]), fold(book["author"])
        if all(w in title or w in author for w in words):
            rank = 0 if any(w in title for w in words) else 1
            hits.append((rank, title, book))
    hits.sort(key=lambda h: (h[0], h[1]))
    return [h[2] for h in hits]
