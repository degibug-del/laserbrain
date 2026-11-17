import pathlib

from pantry import scale, shopping_list
from pantry.loader import load_records

DATA = pathlib.Path(__file__).parent / "data"


def test_fixture_shopping_list():
    recipes = load_records(DATA / "recipes.json")
    assert shopping_list(recipes) == [
        ("butter", 115, "g"), ("flour", 450, "g"), ("milk", 300, "ml"),
        ("sugar", 0.5, "cup"), ("sugar", 2, "tbsp")]


def test_fixture_scale():
    pancakes = load_records(DATA / "recipes.json")[0]
    assert [i["qty"] for i in scale(pancakes, 6)["items"]] == [300, 450, 3]
