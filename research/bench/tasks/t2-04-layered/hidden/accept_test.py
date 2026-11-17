"""Hidden acceptance test for benchmark task t2-04-layered.

Run it from OUTSIDE the sandbox, one task per pytest process:

    BENCH_SANDBOX=/path/to/episode/sandbox \
        python -m pytest -q -p no:cacheprovider tasks/t2-04-layered/hidden/accept_test.py

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

import copy


def test_recursive_merge_and_replace():
    m = load("layered").merge
    base = {"db": {"host": "x", "opts": {"ssl": True, "pool": 5}}, "tags": [1, 2], "n": 1}
    over = {"db": {"opts": {"pool": 10}}, "tags": [3], "n": {"now": "dict"}}
    assert m(base, over) == {"db": {"host": "x", "opts": {"ssl": True, "pool": 10}}, "tags": [3], "n": {"now": "dict"}}
    assert m({"a": {"x": 1}}, {"a": 5}) == {"a": 5}


def test_none_deletes_nested_and_missing():
    m = load("layered").merge
    assert m({"a": {"x": 1, "y": 2}}, {"a": {"y": None}}) == {"a": {"x": 1}}
    assert m({"a": 1}, {"zzz": None}) == {"a": 1}


def test_inputs_not_mutated_and_not_shared():
    m = load("layered").merge
    base = {"a": {"l": [{"k": 1}]}, "keep": [1]}
    over = {"a": {"m": [{"k": 2}]}, "new": [{"z": 0}]}
    b0, o0 = copy.deepcopy(base), copy.deepcopy(over)
    out = m(base, over)
    assert base == b0 and over == o0
    out["a"]["l"][0]["k"] = 99
    out["keep"].append(2)
    out["new"][0]["z"] = 5
    out["a"]["m"][0]["k"] = 7
    assert base == b0 and over == o0


def test_plus_appends():
    m = load("layered").merge
    assert m({"plugins": ["a"]}, {"+plugins": ["b", "c"]}) == {"plugins": ["a", "b", "c"]}
    assert m({}, {"+plugins": ["b"]}) == {"plugins": ["b"]}
    assert m({"a": {"l": [1]}}, {"a": {"+l": [2]}}) == {"a": {"l": [1, 2]}}
