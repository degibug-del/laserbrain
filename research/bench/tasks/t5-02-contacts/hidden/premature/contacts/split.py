def split_email(address):
    """'Ann@Example.com' -> ('Ann', 'Example.com'); raises ValueError without exactly one '@'."""
    if address.count("@") != 1:
        raise ValueError(f"bad address {address!r}")
    local, domain = address.split("@")
    return local, domain
