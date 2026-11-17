import importlib.util
import pathlib

import pytest


@pytest.fixture
def slugify(sandbox_dir):
    spec = importlib.util.spec_from_file_location('slug_under_test', pathlib.Path(sandbox_dir) / 'slug.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.slugify


def test_basic(slugify):
    assert slugify('Hello World') == 'hello-world'


@pytest.mark.parametrize('raw,want', [
    ('Hello,   World!', 'hello-world'),
    ('  --Trim me--  ', 'trim-me'),
    ("It's 2 o'clock", 'its-2-oclock'),
])
def test_edges(slugify, raw, want):
    assert slugify(raw) == want
