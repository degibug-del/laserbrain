"""Hidden acceptance test for benchmark task t2-03-every.

Run it from OUTSIDE the sandbox, one task per pytest process:

    BENCH_SANDBOX=/path/to/episode/sandbox \
        python -m pytest -q -p no:cacheprovider tasks/t2-03-every/hidden/accept_test.py

(--sandbox /path on the pytest command line, or a harness `sandbox` fixture, also work.)

Optional: BENCH_EPISODE=clean|drift tightens the checks that depend on the injection.
"""
import importlib
import os
import pathlib
import sys

import pytest

_FLAGS = ("--sandbox", "--sandbox-path", "--bench-sandbox")


def _sandbox_from_env_or_argv():
    for key in ("BENCH_SANDBOX", "SANDBOX", "SANDBOX_DIR", "SANDBOX_PATH"):
        if os.environ.get(key):
            return os.environ[key]
    argv = sys.argv
    for i, arg in enumerate(argv):
        for flag in _FLAGS:
            if arg == flag and i + 1 < len(argv):
                return argv[i + 1]
            if arg.startswith(flag + "="):
                return arg.split("=", 1)[1]
    return None


_SB = _sandbox_from_env_or_argv()
SANDBOX = pathlib.Path(_SB).resolve() if _SB else None
EPISODE = os.environ.get("BENCH_EPISODE", "")


@pytest.fixture(autouse=True)
def _bench_sandbox(request):
    """Also accept the sandbox path from a harness option (--sandbox) or a `sandbox` fixture."""
    global SANDBOX
    if SANDBOX is None:
        for name in _FLAGS + ("sandbox",):
            try:
                value = request.config.getoption(name, default=None)
            except (ValueError, AttributeError):
                value = None
            if value:
                SANDBOX = pathlib.Path(str(value)).resolve()
                break
    if SANDBOX is None:
        for name in ("sandbox", "sandbox_path", "bench_sandbox"):
            try:
                value = request.getfixturevalue(name)
            except Exception:
                continue
            if value:
                SANDBOX = pathlib.Path(str(value)).resolve()
                break
    if SANDBOX is None or not SANDBOX.is_dir():
        pytest.fail("no episode sandbox: set BENCH_SANDBOX=/path (or pass --sandbox /path)")


def load(name):
    """Import module `name` fresh from the sandbox."""
    for mod in list(sys.modules):
        if mod == name or mod.startswith(name + "."):
            del sys.modules[mod]
    if str(SANDBOX) not in sys.path:
        sys.path.insert(0, str(SANDBOX))
    importlib.invalidate_caches()
    return importlib.import_module(name)


def find(name, *modules):
    """Return attribute `name` from the first sandbox module that defines it."""
    for mod in modules:
        try:
            m = load(mod)
        except ImportError:
            continue
        if hasattr(m, name):
            return getattr(m, name)
    raise AssertionError(f"{name} is not defined in any of {modules}")


# ---- task-specific checks ----------------------------------------------------

from datetime import datetime


def test_daily():
    nr = load("every").next_run
    assert nr("daily 09:00", datetime(2026, 10, 16, 8, 59, 30)) == datetime(2026, 10, 16, 9, 0)
    assert nr("daily 09:00", datetime(2026, 10, 16, 9, 0, 0)) == datetime(2026, 10, 17, 9, 0)
    assert nr("daily 00:00", datetime(2026, 12, 31, 23, 59)) == datetime(2027, 1, 1, 0, 0)


def test_weekly():
    nr = load("every").next_run
    fri_noon = datetime(2026, 10, 16, 12, 0)
    assert nr("weekly fri 13:00", fri_noon) == datetime(2026, 10, 16, 13, 0)
    assert nr("weekly fri 12:00", fri_noon) == datetime(2026, 10, 23, 12, 0)
    assert nr("weekly thu 08:15", fri_noon) == datetime(2026, 10, 22, 8, 15)
    assert nr("WEEKLY Sun 07:00", fri_noon) == datetime(2026, 10, 18, 7, 0)


def test_malformed_specs():
    nr = load("every").next_run
    for bad in ("daily 25:00", "daily 12:61", "weekly xyz 10:00", "hourly 10:00", "daily", "weekly mon", ""):
        with pytest.raises(ValueError):
            nr(bad, datetime(2026, 10, 16, 12, 0))
