from .units import canonical_unit


def scale(recipe, servings):
    factor = servings / recipe["serves"]
    return {
        "name": recipe["name"],
        "serves": servings,
        "items": [
            {"ingredient": i["ingredient"], "qty": round(i["qty"] * factor, 2), "unit": canonical_unit(i["unit"])}
            for i in recipe["items"]
        ],
    }


def shopping_list(recipes):
    totals = {}
    for r in recipes:
        for i in r["items"]:
            key = (i["ingredient"].strip().lower(), canonical_unit(i["unit"]))
            totals[key] = totals.get(key, 0) + i["qty"]
    return [(ing, round(q, 2), unit) for (ing, unit), q in sorted(totals.items())]
