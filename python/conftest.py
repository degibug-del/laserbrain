"""Keep pytest away from the script-style suites, and point it at the runner instead.

WHY THIS FILE EXISTS. Every test_*.py here is a standalone script: it runs its checks at
import time and ends with `raise SystemExit(0 if ok else 1)`. That is a deliberate choice —
each file can be run alone, prints its own assertions, and needs no framework — and it is
also why `python3 -m pytest` did not merely fail, it died:

    INTERNALERROR> SystemExit: 0
    no tests ran in 0.07s

pytest imports a module to collect it, the module exits the interpreter mid-collection, and
the whole run dies before a single check executes. The suite genuinely passes; the single
most obvious command a reviewer types does not. Found by an audit of this repo on
2026-08-17, and it had been true for the life of the package.

The fix keeps both audiences. The scripts stay scripts — `python3 test_frozen.py` is
unchanged — and pytest is told to ignore them here, then given tests/test_suites.py, which
runs each one as a subprocess and asserts its exit code. So `pytest` reports 39 real
results, and nothing about how the suites are written had to change.
"""
import pathlib

# Ignore the script-style suites at the repo root. tests/ is a directory, so this glob does
# not touch the runner inside it.
collect_ignore_glob = ['test_*.py']

SUITES = sorted(p.name for p in pathlib.Path(__file__).parent.glob('test_*.py'))
