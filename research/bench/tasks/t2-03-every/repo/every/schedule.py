from .parse import parse_hhmm  # noqa: F401


def next_run(spec, after):
    """Next datetime strictly after `after` for 'daily HH:MM' or 'weekly DAY HH:MM'."""
    raise NotImplementedError
