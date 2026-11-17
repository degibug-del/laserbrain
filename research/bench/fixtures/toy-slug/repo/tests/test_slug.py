import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from slug import slugify  # noqa: E402


def test_basic():
    assert slugify('Hello World') == 'hello-world'
