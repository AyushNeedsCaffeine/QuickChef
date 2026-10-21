from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache

from app import config
from app.models import Pack, Product


_PREP_WORDS = {
    "chopped", "grated", "sliced", "diced", "ground", "crushed", "finely",
    "roughly", "freshly", "fresh", "dry", "dried", "whole", "large", "small",
    "medium", "optional", "cloves", "leaves", "or", "vegetable",
}
_GENERIC_WORDS = {
    "water", "ice", "leaves", "powder", "seeds", "oil", "paste", "masala",
    "fresh", "dry", "dried", "whole", "chopped", "grated", "sliced", "diced",
    "ground", "crushed", "optional", "large", "small", "medium",
}


class Catalog:
    def __init__(self, products: list[Product]):
        self.products = products
        self._by_id = {p.id: p for p in products}
        self._alias_index: dict[str, str] = {}
        self._index()

    def _index(self) -> None:
        for p in self.products:
            self._alias_index[p.id] = p.id
            self._alias_index[_norm(p.name)] = p.id
            for a in p.aliases:
                self._alias_index[_norm(a)] = p.id

    def all(self) -> list[Product]:
        return list(self.products)

    def get(self, product_id: str) -> Product | None:
        return self._by_id.get(product_id)

    def search(self, query: str, limit: int = 8) -> list[Product]:
        q = _norm(query)
        if not q:
            return []
        scored: list[tuple[float, Product]] = []
        for p in self.products:
            score = _score(q, p)
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [p for _, p in scored[:limit]]

    def resolve(self, name: str) -> Product | None:
        """Resolve an ingredient conservatively.

        Exact names/aliases win. Fuzzy matching is only used when every
        significant word in the query is present (or is a close spelling
        variant) in a catalog name; weak overlaps such as "water" -> "rose
        water" or "kale leaves" -> "coriander leaves" are rejected.
        """
        key = _norm(name)
        exact = self._alias_index.get(key)
        if exact:
            return self._by_id[exact]

        best: tuple[float, Product] | None = None
        for product in self.products:
            score = 0.0
            for candidate in (product.name, *product.aliases):
                if _accept_ingredient_match(name, candidate):
                    score = max(score, _score(key, product))
            if score > 0 and (best is None or score > best[0]):
                best = (score, product)
        return best[1] if best else None


def _norm(s: str) -> str:
    # Parenthetical text usually restates an alias ("Kala Chana (black chickpeas)").
    text = re.sub(r"\([^)]*\)", " ", s.lower())
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(cleaned.split())


def _tokens(s: str) -> set[str]:
    return set(_norm(s).split())


def _significant_tokens(text: str) -> set[str]:
    return {token for token in _tokens(text) - _PREP_WORDS if token not in _GENERIC_WORDS}


def _accept_ingredient_match(query: str, candidate: str) -> bool:
    q_tokens = _significant_tokens(query)
    c_tokens = _tokens(candidate)
    if not q_tokens or not c_tokens:
        return False

    shared = q_tokens & c_tokens
    if not shared:
        return False
    coverage = len(shared) / len(q_tokens)
    if coverage == 1.0:
        return True
    if coverage < 0.5:
        return False

    missing = q_tokens - c_tokens
    return all(
        any(len(token) >= 4 and difflib.SequenceMatcher(None, token, other).ratio() >= 0.8 for other in c_tokens)
        for token in missing
    )


def _score(query: str, p: Product) -> float:
    q_tokens = _tokens(query)
    if not q_tokens:
        return 0.0
    best = 0.0
    candidates = [p.name, *p.aliases]
    for cand in candidates:
        c = _norm(cand)
        c_tokens = _tokens(cand)
        if not c_tokens:
            continue
        if c == query:
            return 100.0
        overlap = len(q_tokens & c_tokens)
        score = overlap / len(q_tokens | c_tokens) * 10 + overlap
        for qt in q_tokens - c_tokens:
            for ct in c_tokens:
                if len(qt) >= 4 and difflib.SequenceMatcher(None, qt, ct).ratio() >= 0.8:
                    score += 2
        best = max(best, score)
    return best


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    raw = json.loads(config.CATALOG_PATH.read_text(encoding="utf-8"))
    products = [
        Product(
            id=item["id"],
            name=item["name"],
            category=item["category"],
            aliases=item.get("aliases", []),
            packs=[Pack(size=pk["size"], unit=pk["unit"], price=pk["price"], stock=pk.get("stock", 500)) for pk in item["packs"]],
        )
        for item in raw["products"]
    ]
    return Catalog(products)
