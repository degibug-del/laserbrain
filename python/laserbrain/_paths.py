"""Where laserbrain keeps its state, for the published package.

The SDK's copy of lasergear/lb_paths.py, which it cannot import: lasergear is a set of
host hooks and is not shipped in the wheel. Same resolution order, same defaults.

    1. a specific override where one exists (LASERBRAIN_STATE_DIR, ...)
    2. LASERBRAIN_HOME, relocating both trees at once
    3. the historical paths, unchanged

An unset environment behaves exactly as every release before this one.
"""
import os
import pathlib


def config_dir():
    h = os.environ.get('LASERBRAIN_HOME')
    return (pathlib.Path(h).expanduser() / 'config') if h else (
        pathlib.Path.home() / '.config' / 'laserbrain')


def sessions_dir():
    d = os.environ.get('LASERBRAIN_STATE_DIR')
    if d:
        return pathlib.Path(d).expanduser()
    h = os.environ.get('LASERBRAIN_HOME')
    return (pathlib.Path(h).expanduser() / 'sessions') if h else (
        pathlib.Path.home() / '.claude' / 'laserbrain')


def config(*parts):
    return config_dir().joinpath(*parts)
