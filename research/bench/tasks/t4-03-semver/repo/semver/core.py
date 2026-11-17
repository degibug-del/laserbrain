from .ident import split_prerelease  # noqa: F401


def parse(version):
    raise NotImplementedError


def compare(a, b):
    raise NotImplementedError
