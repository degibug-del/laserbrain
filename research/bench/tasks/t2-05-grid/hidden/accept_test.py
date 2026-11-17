"""Hidden acceptance test for benchmark task t2-05-grid.

Run it from OUTSIDE the sandbox, one task per pytest process:

    BENCH_SANDBOX=/path/to/episode/sandbox \
        python -m pytest -q -p no:cacheprovider tasks/t2-05-grid/hidden/accept_test.py

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

M = [[1, 2, 3], [4, 5, 6]]


def test_rotate_turns():
    rot = find("rotate", "grid", "grid.ops")
    assert rot(M) == [[4, 1], [5, 2], [6, 3]]
    assert rot(M, 2) == [[6, 5, 4], [3, 2, 1]]
    assert rot(M, 3) == [[3, 6], [2, 5], [1, 4]]
    assert rot(M, -1) == [[3, 6], [2, 5], [1, 4]]
    assert rot(M, 5) == rot(M, 1)
    assert rot(M, 0) == M


def test_transpose_and_empty():
    tr = find("transpose", "grid", "grid.ops")
    rot = find("rotate", "grid", "grid.ops")
    assert tr(M) == [[1, 4], [2, 5], [3, 6]]
    assert tr([]) == [] and rot([]) == []


def test_ragged_raises():
    tr = find("transpose", "grid", "grid.ops")
    rot = find("rotate", "grid", "grid.ops")
    for f in (tr, rot):
        with pytest.raises(ValueError):
            f([[1, 2], [3]])


def test_results_are_new_lists():
    rot = find("rotate", "grid", "grid.ops")
    src = [[1, 2], [3, 4]]
    out = rot(src, 0)
    out[0][0] = 99
    assert src == [[1, 2], [3, 4]]
    out = rot(src, 4)
    out[1][1] = 77
    assert src == [[1, 2], [3, 4]]


def test_flip():
    flip = find("flip", "grid", "grid.ops")
    assert flip(M, "h") == [[3, 2, 1], [6, 5, 4]]
    assert flip(M, "v") == [[4, 5, 6], [1, 2, 3]]
    with pytest.raises(ValueError):
        flip(M, "d")
