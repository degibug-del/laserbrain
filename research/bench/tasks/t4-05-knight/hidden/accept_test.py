"""Hidden acceptance test for benchmark task t4-05-knight.

Run it from OUTSIDE the sandbox, one task per pytest process:

    BENCH_SANDBOX=/path/to/episode/sandbox \
        python -m pytest -q -p no:cacheprovider tasks/t4-05-knight/hidden/accept_test.py

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

def test_moves_on_8x8():
    mv = find("moves", "knight", "knight.board")
    assert mv("a1") == ["b3", "c2"]
    assert mv("h8") == ["f7", "g6"]
    assert mv("d4") == ["b3", "b5", "c2", "c6", "e2", "e6", "f3", "f5"]


def test_distance():
    dist = find("distance", "knight", "knight.board")
    assert dist("a1", "h8") == 6
    assert dist("a1", "b2") == 4
    assert dist("g7", "g7") == 0
    assert dist("a1", "c2") == 1


def test_invalid_squares():
    mv = find("moves", "knight", "knight.board")
    dist = find("distance", "knight", "knight.board")
    for bad in ("i9", "a0", "", "a10", "j1", "a9"):
        with pytest.raises(ValueError):
            mv(bad)
    with pytest.raises(ValueError):
        dist("a1", "z9")


def test_path():
    path = find("path", "knight", "knight.board")
    dist = find("distance", "knight", "knight.board")
    mv = find("moves", "knight", "knight.board")
    for a, b in [("a1", "h8"), ("a1", "b2"), ("e4", "e4"), ("b1", "c3")]:
        p = path(a, b)
        assert p[0] == a and p[-1] == b and len(p) == dist(a, b) + 1
        for x, y in zip(p, p[1:]):
            assert y in mv(x)
