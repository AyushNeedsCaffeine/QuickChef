from __future__ import annotations

import math

from app.models import CartItem, Ingredient, Pack, Product

MASS = "mass"
VOLUME = "volume"
COUNT = "count"

_UNIT_MAP: dict[str, tuple[str, float]] = {
    "g": (MASS, 1.0),
    "gm": (MASS, 1.0),
    "gram": (MASS, 1.0),
    "grams": (MASS, 1.0),
    "kg": (MASS, 1000.0),
    "kgs": (MASS, 1000.0),
    "kilogram": (MASS, 1000.0),
    "ml": (VOLUME, 1.0),
    "milliliter": (VOLUME, 1.0),
    "millilitre": (VOLUME, 1.0),
    "l": (VOLUME, 1000.0),
    "lt": (VOLUME, 1000.0),
    "liter": (VOLUME, 1000.0),
    "litre": (VOLUME, 1000.0),
    "cup": (VOLUME, 240.0),
    "cups": (VOLUME, 240.0),
    "tbsp": (VOLUME, 15.0),
    "tablespoon": (VOLUME, 15.0),
    "tablespoons": (VOLUME, 15.0),
    "tsp": (VOLUME, 5.0),
    "teaspoon": (VOLUME, 5.0),
    "teaspoons": (VOLUME, 5.0),
    "pc": (COUNT, 1.0),
    "pcs": (COUNT, 1.0),
    "piece": (COUNT, 1.0),
    "pieces": (COUNT, 1.0),
    "no": (COUNT, 1.0),
    "nos": (COUNT, 1.0),
    "number": (COUNT, 1.0),
    "pinch": (MASS, 0.4),
    "pinches": (MASS, 0.4),
    "clove": (COUNT, 1.0),
    "cloves": (COUNT, 1.0),
    "inch": (MASS, 5.0),
    "slice": (COUNT, 1.0),
    "slices": (COUNT, 1.0),
    "bunch": (COUNT, 1.0),
    "sprig": (COUNT, 1.0),
    "handful": (MASS, 30.0),
}


def to_base(quantity: float, unit: str) -> tuple[float, str]:
    entry = _UNIT_MAP.get(str(unit).strip().lower())
    if entry is None:
        return float(quantity), MASS
    dimension, factor = entry
    return float(quantity) * factor, dimension


def _coerce(required: float, req_dim: str, pack_dim: str) -> float | None:
    if req_dim == pack_dim:
        return required
    pair = {req_dim, pack_dim}
    if pair == {MASS, VOLUME}:
        return required
    if req_dim == COUNT:
        return required
    if pack_dim == COUNT:
        return None
    return None


def _pack_base(pack: Pack) -> tuple[float, str]:
    return to_base(pack.size, pack.unit)


def select_packs(product: Product, quantity: float, unit: str) -> tuple[list[tuple[Pack, int]], float]:
    required, req_dim = to_base(quantity, unit)

    converted: list[tuple[float, Pack]] = []
    for pack in product.packs:
        size_base, pack_dim = _pack_base(pack)
        need = _coerce(required, req_dim, pack_dim)
        if need is None:
            continue
        converted.append((size_base, pack))

    if not converted:
        pack = min(product.packs, key=lambda p: _pack_base(p)[0])
        return [(pack, 1)], required

    if required <= 0:
        pack = min(converted, key=lambda t: t[0])[1]
        return [(pack, 1)], 0.0

    best: tuple[float, float, Pack, int] | None = None
    for size_base, pack in converted:
        count = max(1, math.ceil(required / size_base))
        cost = count * pack.price
        waste = count * size_base - required
        candidate = (cost, waste, pack, count)
        if best is None or (cost, waste) < (best[0], best[1]):
            best = candidate

    assert best is not None
    return [(best[2], best[3])], required


def build_cart_item(product: Product, quantity: float, unit: str) -> CartItem | None:
    selections, _ = select_packs(product, quantity, unit)
    if not selections:
        return None
    pack, count = selections[0]
    return CartItem(
        product_id=product.id,
        name=product.name,
        pack_size=pack.size,
        pack_unit=pack.unit,
        quantity=count,
        unit_price=pack.price,
    )


def scale_ingredient(ingredient: Ingredient, servings: int, base_servings: int = 4) -> Ingredient:
    factor = servings / base_servings if base_servings else 1
    return Ingredient(
        name=ingredient.name,
        quantity=round(ingredient.quantity * factor, 2),
        unit=ingredient.unit,
        category=ingredient.category,
    )
