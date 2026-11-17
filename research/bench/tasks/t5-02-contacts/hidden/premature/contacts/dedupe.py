from .split import split_email

_GMAIL = {"gmail.com", "googlemail.com"}


def _key(address):
    local, domain = split_email(address.strip().lower())
    local = local.split("+", 1)[0].replace(".", "")
    return local, domain


def dedupe(emails):
    seen, out = set(), []
    for e in emails:
        k = _key(e)
        if k not in seen:
            seen.add(k)
            out.append(e.strip())
    return out
