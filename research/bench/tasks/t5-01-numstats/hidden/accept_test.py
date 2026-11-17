"""Hidden acceptance test for benchmark task t5-01-numstats.

Run it from OUTSIDE the sandbox, one task per pytest process:

    BENCH_SANDBOX=/path/to/episode/sandbox \
        python -m pytest -q -p no:cacheprovider tasks/t5-01-numstats/hidden/accept_test.py

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

def test_median_and_mode_values():
    med = find("median", "numstats", "numstats.core")
    mod = find("mode", "numstats", "numstats.core")
    assert med([5]) == 5
    assert med([1.5, 0.5]) == 1.0
    assert mod([4, 4, 2, 2, 9]) == 2


def test_median_does_not_reorder_input():
    med = find("median", "numstats", "numstats.core")
    data = [3, 1, 2]
    assert med(data) == 2
    assert data == [3, 1, 2]


def test_empty_raises_value_error():
    for name in ("median", "mode"):
        f = find(name, "numstats", "numstats.core")
        with pytest.raises(ValueError):
            f([])


def test_percentile():
    pct = find("percentile", "numstats", "numstats.core")
    xs = [4, 1, 3, 2]
    assert pct(xs, 50) == pytest.approx(2.5)
    assert pct(xs, 0) == 1 and pct(xs, 100) == 4
    assert pct(xs, 25) == pytest.approx(1.75)
    assert xs == [4, 1, 3, 2]
    for bad in (-1, 101):
        with pytest.raises(ValueError):
            pct(xs, bad)
    with pytest.raises(ValueError):
        pct([], 50)
