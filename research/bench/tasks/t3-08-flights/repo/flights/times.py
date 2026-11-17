from .tz import parse_offset  # noqa: F401


def duration_minutes(flight):
    raise NotImplementedError


def connections(flights, min_layover=45):
    raise NotImplementedError
