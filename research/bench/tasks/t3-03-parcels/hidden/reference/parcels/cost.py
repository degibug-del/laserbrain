import math

from .rates import ZONES
from .volume import volumetric_kg


def billable_kg(parcel):
    kg = max(parcel["kg"], volumetric_kg(parcel["l"], parcel["w"], parcel["h"]))
    return math.ceil(kg * 2 - 1e-9) / 2


def shipping_cost(parcel):
    if parcel["zone"] not in ZONES:
        raise KeyError(parcel["zone"])
    base, per_kg = ZONES[parcel["zone"]]
    return round(base + per_kg * billable_kg(parcel), 2)
