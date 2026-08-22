"""Run every script-style suite as a subprocess and assert it exits clean.

This is the pytest-visible surface. The suites themselves are standalone scripts (see
../conftest.py for why) and are run here the same way a human runs them, so there is no
second code path that could pass while the real one fails.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# BOTH TREES, NOT JUST THIS ONE. This globbed python/ alone, so the three suites in
# javascript/ were collected by nothing and ran nowhere. All three had rotted: two died on
# imports the reorg left behind (_testhome, lasergear/lb_gate.py) and the third pointed at
# a laserbrain-sdk/ that no longer exists — and because no runner called them, none of it
# surfaced. test_attention.py is the parity guard on attention.json; it had been silently
# skipping the very comparison it exists to make while the two copies drifted five days
# apart. Found 2026-08-21.
#
# Identified as (dir, name) because the two trees can hold the same filename and each suite
# must run with its own directory as cwd.
SUITES = ([('.', p.name) for p in ROOT.glob('test_*.py')]
          + [('../javascript', p.name)
             for p in (ROOT.parent / 'javascript').glob('test_*.py')])
SUITES = sorted(SUITES, key=lambda t: (t[0], t[1]))


def _run_suite(where, suite, home):
    env = {**os.environ, 'LASERBRAIN_HOME': home}
    return subprocess.run([sys.executable, suite], cwd=(ROOT / where).resolve(),
                          capture_output=True, text=True, timeout=300, env=env)


@pytest.mark.parametrize('where,suite', SUITES,
                         ids=[f'{d}/{n}' if d != '.' else n for d, n in SUITES])
def test_suite_passes(where, suite):
    # A PRIVATE STATE ROOT PER SUITE. Two comments in the tree — test_gate_hosts.py and
    # javascript/test_attention.py — already say "run-tests.sh exports LASERBRAIN_HOME so no
    # suite can write to it" and defend against it. There is no run-tests.sh in this repo and
    # there is no record of one, so that invariant was being assumed rather than provided:
    # 37 of the 42 suites set no state root, and a full run rewrote the live
    # ~/.config/laserbrain/contexts.json every time.
    #
    # Which is not cosmetic. That store feeds `repetition` and "opened in N earlier
    # sessions", and those change what phronesis() returns — a probe in this repo watched a
    # verdict move from wrong-problem to abandon purely on residue from an earlier identical
    # run. The corpus has already paid for it once: the comment on the `repetition >= 3`
    # threshold records re-deriving it "after 248 of 680 contexts turned out to be test
    # fixtures". This is where that stops, centrally, instead of in 37 files that would each
    # have to remember.
    #
    # mkdtemp per suite, not per run: suites must not see each other's contexts either.
    # CLEANED UP. mkdtemp does not remove itself, so this leaked one populated state
    # directory per suite per run — 45 of them, growing with every CI job and every local
    # run. TemporaryDirectory in a with-block keeps the isolation and returns the disk.
    with tempfile.TemporaryDirectory(prefix=f'lb-{suite[:-3]}-') as _home:
        r = _run_suite(where, suite, _home)
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
    # Named explicitly: the count alone would stay satisfied if javascript/ dropped out
    # again, which is exactly how these three went unrun.
    assert any(d == '../javascript' for d, _ in SUITES), 'the javascript suites vanished'
