from .rates import ZONES  # noqa: F401
from .volume import volumetric_kg  # noqa: F401


def shipping_cost(parcel):
    """parcel: {"id", "zone", "kg", "l", "w", "h"} with dimensions in cm."""
    raise NotImplementedError
