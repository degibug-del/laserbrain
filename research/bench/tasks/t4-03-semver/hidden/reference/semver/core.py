import re

from .ident import split_prerelease

_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")


def parse(version):
    m = _RE.fullmatch(version) if isinstance(version, str) else None
    if not m:
        raise ValueError(f"invalid version {version!r}")
    pre = split_prerelease(m.group(4)) if m.group(4) else ()
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), pre)


def _cmp_ident(a, b):
    if isinstance(a, int) and isinstance(b, int):
        return (a > b) - (a < b)
    if isinstance(a, int):
        return -1
    if isinstance(b, int):
        return 1
    return (a > b) - (a < b)


def compare(a, b):
    pa, pb = parse(a), parse(b)
    if pa[:3] != pb[:3]:
        return -1 if pa[:3] < pb[:3] else 1
    xa, xb = pa[3], pb[3]
    if not xa and not xb:
        return 0
    if not xa:
        return 1
    if not xb:
        return -1
    for ia, ib in zip(xa, xb):
        c = _cmp_ident(ia, ib)
        if c:
            return c
    return (len(xa) > len(xb)) - (len(xa) < len(xb))


def bump(version, part):
    major, minor, patch, _ = parse(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown part {part!r}")
