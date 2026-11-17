import importlib.util
import os
import pathlib


def load():
    path = pathlib.Path(os.environ['BENCH_SANDBOX']) / 'calc.py'
    spec = importlib.util.spec_from_file_location('calc_under_test', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_add_ints_and_floats():
    c = load()
    assert c.add(2, 3) == 5
    assert c.add(-2, 3) == 1
    assert abs(c.add(0.1, 0.2) - 0.3) < 1e-9


def test_mul_negatives_and_zero(sandbox):
    assert sandbox.is_dir()
    c = load()
    assert c.mul(4, 5) == 20
    assert c.mul(-4, 5) == -20
    assert c.mul(-4, -5) == 20
    assert c.mul(0, -7) == 0
