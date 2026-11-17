import re


def slugify(s):
    s = re.sub(r"[^\w\s-]", '', s.lower())
    return re.sub(r'[\s_-]+', '-', s).strip('-')
