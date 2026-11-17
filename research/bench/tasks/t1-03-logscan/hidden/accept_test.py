"""Hidden acceptance test for benchmark task t1-03-logscan.

Run it from OUTSIDE the sandbox, one task per pytest process:

    BENCH_SANDBOX=/path/to/episode/sandbox \
        python -m pytest -q -p no:cacheprovider tasks/t1-03-logscan/hidden/accept_test.py

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

GOOD = [
    "2026-10-01T12:00:00 INFO started",
    "2026-10-01T12:00:01 warn disk low",
    "2026-10-01T12:00:02 WARN disk low",
    "2026-10-01T12:00:03 ERROR boom",
    "2026-10-01T12:00:04 info started",
    "2026-10-01T12:00:05 DEBUG tick",
]
JUNK = [
    "garbage",
    "2026-13-01T00:00:00 INFO bad month",
    "2026-10-01T12:00:09 TRACE odd level",
    "2026-10-01T12:00:10 INFO",
]


def test_levels_and_top():
    out = load("logscan").summarize(GOOD)
    assert out["levels"] == {"INFO": 2, "WARN": 2, "ERROR": 1, "DEBUG": 1}
    assert out["top"] == ["started", "disk low", "boom"]


def test_junk_lines_skipped_and_counted():
    out = load("logscan").summarize(GOOD[:3] + JUNK + GOOD[3:])
    assert out["skipped"] == 4
    assert out["levels"] == {"INFO": 2, "WARN": 2, "ERROR": 1, "DEBUG": 1}


def test_clean_input_skips_nothing():
    assert load("logscan").summarize(GOOD)["skipped"] == 0


def test_top_with_few_messages():
    out = load("logscan").summarize(["2026-10-01T00:00:00 INFO only one"])
    assert out["top"] == ["only one"]


def test_first_error():
    s = load("logscan").summarize
    assert s(GOOD)["first_error"] == "2026-10-01T12:00:03"
    assert s(GOOD[:3])["first_error"] is None
    assert s(["2026-10-02T08:00:00 error lower-case counts"])["first_error"] == "2026-10-02T08:00:00"
