"""Hidden acceptance test for benchmark task t4-04-shelf.

Run it from OUTSIDE the sandbox, one task per pytest process:

    BENCH_SANDBOX=/path/to/episode/sandbox \
        python -m pytest -q -p no:cacheprovider tasks/t4-04-shelf/hidden/accept_test.py

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

BOOKS = [
    {"title": "Jane Eyre", "author": "Charlotte Brontë", "year": 1847},
    {"title": "Emma", "author": "Jane Austen", "year": 1815},
    {"title": "Persuasion", "author": "Jane Austen", "year": 1817},
    {"title": "Wuthering Heights", "author": "Emily Brontë", "year": 1847},
    {"title": "Les Misérables", "author": "Victor Hugo", "year": 1862},
    {"title": "Austerlitz", "author": "W. G. Sebald", "year": 2001},
]


def titles(found):
    return [b["title"] for b in found]


def test_all_words_must_match():
    s = load("shelf").search
    assert titles(s(BOOKS, "jane austen")) == ["Emma", "Persuasion"]
    assert titles(s(BOOKS, "emily heights")) == ["Wuthering Heights"]
    assert s(BOOKS, "jane hugo") == []


def test_ranking_title_before_author():
    s = load("shelf").search
    assert titles(s(BOOKS, "auste")) == ["Austerlitz", "Emma", "Persuasion"]
    assert titles(s(BOOKS, "Jane")) == ["Jane Eyre", "Emma", "Persuasion"]


def test_accent_insensitive_both_ways():
    s = load("shelf").search
    assert titles(s(BOOKS, "BRONTË")) == ["Jane Eyre", "Wuthering Heights"]
    assert titles(s(BOOKS, "miserables")) == ["Les Misérables"]


def test_blank_query():
    s = load("shelf").search
    assert s(BOOKS, "") == [] and s(BOOKS, "   ") == []
