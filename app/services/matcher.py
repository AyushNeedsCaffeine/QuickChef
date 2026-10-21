from __future__ import annotations

from dataclasses import dataclass, field

from app.models import CartItem, Ingredient
from app.services import pack_selector
from app.services.catalog import Catalog, _norm, get_catalog


@dataclass
class MatchResult:
    matched: list[CartItem] = field(default_factory=list)
    unmatched: list[Ingredient] = field(default_factory=list)
    pantry: list[Ingredient] = field(default_factory=list)


_PANTRY_WORDS = {"water", "ice", "hot", "warm", "cold", "boiling", "cubes", "as", "needed", "for"}


def is_pantry(name: str) -> bool:
    tokens = set(_norm(name).split())
    return "water" in tokens and tokens <= _PANTRY_WORDS or tokens in ({"ice"}, {"ice", "cubes"})


def match_ingredients(ingredients: list[Ingredient], catalog: Catalog | None = None) -> MatchResult:
    catalog = catalog or get_catalog()
    result = MatchResult()
    for ing in ingredients:
        if is_pantry(ing.name):
            result.pantry.append(ing)
            continue
        product = catalog.resolve(ing.name)
        if product is None:
            result.unmatched.append(ing)
            continue
        item = pack_selector.build_cart_item(product, ing.quantity, ing.unit)
        if item is None:
            result.unmatched.append(ing)
            continue
        item.name = f"{product.name} ({_fmt_pack(item)})"
        result.matched.append(item)
    return result


def _fmt_pack(item: CartItem) -> str:
    size = item.pack_size
    size_str = str(int(size)) if float(size).is_integer() else str(size)
    return f"{size_str}{item.pack_unit}"
