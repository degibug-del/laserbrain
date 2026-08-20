"""Run every script-style suite as a subprocess and assert it exits clean.

This is the pytest-visible surface. The suites themselves are standalone scripts (see
../conftest.py for why) and are run here the same way a human runs them, so there is no
second code path that could pass while the real one fails.
"""
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUITES = sorted(p.name for p in ROOT.glob('test_*.py'))


@pytest.mark.parametrize('suite', SUITES)
def test_suite_passes(suite):
    r = subprocess.run([sys.executable, suite], cwd=ROOT, capture_output=True, text=True,
                       timeout=300)
    # 77 means the suite could not run — its subject lives in another repo and was not
    # found. That is a SKIP, not a pass: reporting it green would be the same lie as a
    # green build over a check that never executed, which is the failure this whole project
    # is organised against. Three suites reach into lasergear; CI clones it so they really
    # run, and this path is what happens anywhere else.
    if r.returncode == 77:
        pytest.skip(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else f'{suite} skipped')
    # The script's own output is the useful failure message — it names the assertion that
    # broke, which an exit code alone cannot.
    assert r.returncode == 0, f'{suite} exited {r.returncode}\n{r.stdout[-3000:]}{r.stderr[-2000:]}'


def test_every_suite_is_collected():
    """A suite that stops being found is a suite that stops running, silently."""
    assert len(SUITES) >= 39, f'only {len(SUITES)} suites found — did a file get renamed?'
