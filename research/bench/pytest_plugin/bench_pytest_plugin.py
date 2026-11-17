"""Loaded by run.py's grader with `-p bench_pytest_plugin`: hands accept_test.py the sandbox.

The harness also exports BENCH_SANDBOX / SANDBOX / SANDBOX_DIR / SANDBOX_PATH, so a test
can read the environment instead. A conftest fixture with the same name wins over these.
"""
import os
import pathlib

import pytest


def _sandbox():
    v = os.environ.get('BENCH_SANDBOX') or os.environ.get('SANDBOX')
    if not v:
        pytest.fail('BENCH_SANDBOX is not set; run through research/bench/run.py')
    return pathlib.Path(v)


@pytest.fixture
def sandbox():
    return _sandbox()


@pytest.fixture
def sandbox_dir():
    return _sandbox()


@pytest.fixture
def sandbox_path():
    return _sandbox()
