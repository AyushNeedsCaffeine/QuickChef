from __future__ import annotations

import difflib
import re

from app.services.catalog import _norm

BASE_SERVINGS = 4

_MODIFIER_RE = re.compile(
    r"\b(without|no|extra|less|more|add|with|only|minus|skip|substitute|replace|avoid)\b",
    re.IGNORECASE,
)


def has_modifiers(dish: str) -> bool:
    """True if the dish phrase contains a modification (addition/exclusion)."""
    return bool(_MODIFIER_RE.search(dish or ""))


# Dishes shown in the UI. Used only as a catalogue for LLM candidate suggestions,
# not as an alias table: the model decides whether a user term means one of these.
POPULAR_DISHES = [
    "Garlic Naan",
    "Paneer Butter Masala",
    "Dal Makhani",
    "Chole Kulche",
    "Rajma Chawal",
    "Aloo Gobi",
    "Palak Paneer",
    "Matar Paneer",
    "Veg Biryani",
    "Veg Pulao",
    "Idli Sambar",
    "Masala Dosa",
    "Pav Bhaji",
    "Pasta",
    "Veg Hakka Noodles",
    "Rasmalai",
    "Gulab Jamun",
    "Kala Chana",
    "Masala Chana",
    "Pumpkin Sabzi",
    "Maggi Noodles",
    "Shahi Paneer",
    "Paneer Lababdar",
    "Paneer Tikka",
    "Paneer Bhurji",
    "Paneer Do Pyaza",
    "Kadai Paneer",
    "Chilli Paneer",
    "Afghani Soy Chaap",
    "Malai Soy Chaap",
    "Tandoori Soy Chaap",
    "Soya Chaap",
    "Butter Chicken",
    "Chicken Biryani",
    "Chicken Curry",
    "Chicken 65",
    "Egg Curry",
    "Egg Fried Rice",
    "Veg Fried Rice",
    "Veg Manchurian",
    "Dal Tadka",
    "Dal Fry",
    "Aloo Matar",
    "Bhindi Masala",
    "Baingan Bharta",
    "Aloo Paratha",
    "Paneer Paratha",
    "Upma",
    "Vegetable Poha",
    "Kadhi Chawal",
    "Kheer",
    "Gajar Halwa",
]


def _ordered_catalog() -> list[str]:
    """Curated dishes first, then any fallback-only names, without token duplicates."""
    catalog: list[str] = []
    seen: set[frozenset[str]] = set()
    for name in list(POPULAR_DISHES) + [key.title() for key in FALLBACK_RECIPES]:
        tokens = frozenset(_tokens(name))
        if tokens in seen:
            continue
        seen.add(tokens)
        catalog.append(name)
    return catalog


def dish_catalog() -> list[str]:
    """Names the dish resolver may suggest. Populated from the UI + offline corpus."""
    return sorted(_ordered_catalog())


_SEARCH_STOPWORDS = {"dish", "recipe", "meal", "curry", "sabzi", "food", "something", "else"}


def _search_token_match(query_token: str, name_token: str, *, prefix: bool) -> bool:
    if query_token == name_token:
        return True
    if prefix and len(query_token) >= 2 and name_token.startswith(query_token):
        return True
    if len(query_token) >= 3:
        return difflib.SequenceMatcher(None, query_token, name_token).ratio() >= 0.85
    return False


def search_dishes(query: str, limit: int = 8) -> list[str]:
    """Deterministic, catalogue-only search for the live dish typeahead.

    Every meaningful query token must match a token in the dish name (AND
    semantics). The last token may be a prefix so results appear while typing.
    Generic words such as ``curry`` do not reduce a search to a single dish.
    """
    limit = max(1, min(int(limit), 12))
    raw = (query or "").strip()
    ordered = _ordered_catalog()
    if not raw:
        return ordered[:limit]

    query_tokens = [token for token in _norm(raw).split() if token not in _SEARCH_STOPWORDS]
    if not query_tokens:
        return []

    scored: list[tuple[float, str]] = []
    for name in ordered:
        name_tokens = _norm(name).split()
        if not name_tokens:
            continue
        matches = True
        exact = 0
        matched_tokens: set[str] = set()
        for index, query_token in enumerate(query_tokens):
            is_last = index == len(query_tokens) - 1
            hit = next(
                (token for token in name_tokens if _search_token_match(query_token, token, prefix=is_last)),
                None,
            )
            if hit is None:
                matches = False
                break
            matched_tokens.add(hit)
            if query_token in name_tokens:
                exact += 1
        if not matches:
            continue

        normalized_name = _norm(name)
        normalized_query = " ".join(query_tokens)
        if normalized_name == normalized_query:
            score = 1000.0
        elif normalized_name.startswith(normalized_query):
            score = 800.0
        else:
            score = 500.0
        score += exact * 20
        score -= len(set(name_tokens) - matched_tokens) * 15
        score -= abs(len(name_tokens) - len(query_tokens)) * 5
        scored.append((score, name))

    scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return [name for _, name in scored[:limit]]


def split_modifiers(dish: str) -> tuple[str, str]:
    """Split a dish phrase into its base name and trailing modification text."""
    text = (dish or "").strip()
    match = _MODIFIER_RE.search(text)
    if not match:
        return text, ""
    base = text[: match.start()].strip()
    if not base:
        return text, ""
    return base, text[match.start() :].strip()


def _tokens(text: str) -> set[str]:
    # "veg" and "veggie" are generic shorthand, not dish-specific aliases.
    normalised = _norm(text).replace("veggie", "vegetable").replace("veg ", "vegetable ")
    if normalised.endswith(" veg"):
        normalised = normalised[:-3] + " vegetable"
    return set(normalised.split())

FALLBACK_RECIPES: dict[str, list[tuple[str, float, str, str]]] = {
    "dal makhani": [
        ("Urad Dal Whole", 250, "g", "pulses"),
        ("Kidney Beans", 60, "g", "pulses"),
        ("Butter", 100, "g", "dairy"),
        ("Fresh Cream", 100, "ml", "dairy"),
        ("Tomato", 400, "g", "vegetables"),
        ("Onion", 200, "g", "vegetables"),
        ("Ginger", 20, "g", "vegetables"),
        ("Garlic", 20, "g", "vegetables"),
        ("Green Chilli", 20, "g", "vegetables"),
        ("Turmeric Powder", 1, "tsp", "spices"),
        ("Red Chilli Powder", 2, "tsp", "spices"),
        ("Coriander Powder", 2, "tsp", "spices"),
        ("Cumin Seeds", 1, "tsp", "spices"),
        ("Garam Masala", 1, "tsp", "spices"),
        ("Kasuri Methi", 1, "tbsp", "spices"),
        ("Salt", 2, "tsp", "spices"),
        ("Sunflower Oil", 2, "tbsp", "oils"),
        ("Coriander Leaves", 50, "g", "vegetables"),
    ],
    "paneer butter masala": [
        ("Paneer", 400, "g", "dairy"),
        ("Butter", 80, "g", "dairy"),
        ("Fresh Cream", 100, "ml", "dairy"),
        ("Tomato", 500, "g", "vegetables"),
        ("Onion", 200, "g", "vegetables"),
        ("Cashew Nuts", 50, "g", "dry_fruits"),
        ("Ginger Garlic Paste", 2, "tbsp", "condiments"),
        ("Red Chilli Powder", 2, "tsp", "spices"),
        ("Turmeric Powder", 1, "tsp", "spices"),
        ("Garam Masala", 1, "tsp", "spices"),
        ("Kasuri Methi", 1, "tbsp", "spices"),
        ("Sugar", 1, "tsp", "spices"),
        ("Salt", 2, "tsp", "spices"),
        ("Coriander Leaves", 30, "g", "vegetables"),
    ],
    "rajma curry": [
        ("Kidney Beans", 300, "g", "pulses"),
        ("Onion", 200, "g", "vegetables"),
        ("Tomato", 300, "g", "vegetables"),
        ("Ginger", 20, "g", "vegetables"),
        ("Garlic", 15, "g", "vegetables"),
        ("Green Chilli", 15, "g", "vegetables"),
        ("Cumin Seeds", 1, "tsp", "spices"),
        ("Turmeric Powder", 1, "tsp", "spices"),
        ("Red Chilli Powder", 2, "tsp", "spices"),
        ("Coriander Powder", 2, "tsp", "spices"),
        ("Garam Masala", 1, "tsp", "spices"),
        ("Sunflower Oil", 2, "tbsp", "oils"),
        ("Salt", 2, "tsp", "spices"),
        ("Coriander Leaves", 30, "g", "vegetables"),
    ],
    "chole": [
        ("White Chickpeas", 300, "g", "pulses"),
        ("Onion", 200, "g", "vegetables"),
        ("Tomato", 300, "g", "vegetables"),
        ("Ginger", 20, "g", "vegetables"),
        ("Garlic", 15, "g", "vegetables"),
        ("Green Chilli", 15, "g", "vegetables"),
        ("Chana Masala", 2, "tsp", "spices"),
        ("Turmeric Powder", 1, "tsp", "spices"),
        ("Red Chilli Powder", 2, "tsp", "spices"),
        ("Cumin Seeds", 1, "tsp", "spices"),
        ("Sunflower Oil", 2, "tbsp", "oils"),
        ("Salt", 2, "tsp", "spices"),
        ("Coriander Leaves", 30, "g", "vegetables"),
    ],
    "aloo gobi": [
        ("Potato", 400, "g", "vegetables"),
        ("Cauliflower", 1, "pc", "vegetables"),
        ("Onion", 150, "g", "vegetables"),
        ("Tomato", 200, "g", "vegetables"),
        ("Ginger", 15, "g", "vegetables"),
        ("Green Chilli", 15, "g", "vegetables"),
        ("Turmeric Powder", 1, "tsp", "spices"),
        ("Red Chilli Powder", 1, "tsp", "spices"),
        ("Coriander Powder", 2, "tsp", "spices"),
        ("Cumin Seeds", 1, "tsp", "spices"),
        ("Garam Masala", 1, "tsp", "spices"),
        ("Sunflower Oil", 3, "tbsp", "oils"),
        ("Salt", 2, "tsp", "spices"),
        ("Coriander Leaves", 30, "g", "vegetables"),
    ],
    "vegetable biryani": [
        ("Basmati Rice", 500, "g", "grains"),
        ("Onion", 300, "g", "vegetables"),
        ("Tomato", 200, "g", "vegetables"),
        ("Carrot", 100, "g", "vegetables"),
        ("Green Peas", 100, "g", "vegetables"),
        ("Potato", 150, "g", "vegetables"),
        ("Curd", 200, "g", "dairy"),
        ("Ghee", 3, "tbsp", "dairy"),
        ("Ginger Garlic Paste", 2, "tbsp", "condiments"),
        ("Green Chilli", 20, "g", "vegetables"),
        ("Biryani Masala", 2, "tbsp", "spices"),
        ("Turmeric Powder", 1, "tsp", "spices"),
        ("Coriander Leaves", 40, "g", "vegetables"),
        ("Mint Leaves", 30, "g", "vegetables"),
        ("Salt", 3, "tsp", "spices"),
    ],
    "vegetable poha": [
        ("Poha", 250, "g", "grains"),
        ("Onion", 150, "g", "vegetables"),
        ("Potato", 150, "g", "vegetables"),
        ("Green Peas", 50, "g", "vegetables"),
        ("Green Chilli", 15, "g", "vegetables"),
        ("Curry Leaves", 10, "g", "vegetables"),
        ("Mustard Seeds", 1, "tsp", "spices"),
        ("Turmeric Powder", 1, "tsp", "spices"),
        ("Peanuts", 50, "g", "snacks"),
        ("Lemon", 1, "pc", "vegetables"),
        ("Sunflower Oil", 2, "tbsp", "oils"),
        ("Salt", 1, "tsp", "spices"),
        ("Coriander Leaves", 30, "g", "vegetables"),
    ],
}


FALLBACK_STEPS: dict[str, list[str]] = {
    "dal makhani": [
        "Rinse and soak the urad dal and kidney beans overnight, then pressure cook until soft.",
        "Heat butter and oil, add cumin seeds, then saute onion, ginger, garlic and green chilli.",
        "Add tomato, turmeric, red chilli and coriander powder; cook until the masala releases oil.",
        "Add the boiled lentils with a little water and simmer on low for 20-25 minutes.",
        "Mash some lentils for a creamy texture and stir in cream and butter.",
        "Finish with garam masala and crushed kasuri methi, garnish with coriander and serve hot.",
    ],
    "paneer butter masala": [
        "Blanch tomatoes with cashews and blend into a smooth puree.",
        "Heat butter, saute onion and ginger-garlic paste until fragrant.",
        "Add the tomato-cashew puree with turmeric, red chilli and salt; cook until thick.",
        "Stir in cream and sugar and simmer to a rich gravy.",
        "Add paneer cubes and gently simmer for 5 minutes.",
        "Sprinkle garam masala and kasuri methi, garnish with coriander and serve.",
    ],
    "rajma curry": [
        "Soak rajma overnight and pressure cook until soft with salt.",
        "Heat oil, add cumin seeds, then saute onion, ginger, garlic and green chilli.",
        "Add tomato and the dry spices; cook until the masala thickens.",
        "Add the cooked rajma with its stock and simmer for 15-20 minutes.",
        "Mash a few beans to thicken the gravy and adjust seasoning.",
        "Finish with garam masala and coriander leaves, serve with rice.",
    ],
    "chole": [
        "Soak chickpeas overnight and pressure cook until tender.",
        "Heat oil, add cumin seeds, then saute onion, ginger, garlic and green chilli.",
        "Add tomato, turmeric and red chilli powder; cook until the masala is thick.",
        "Add chana masala and the cooked chickpeas with some water.",
        "Simmer for 15 minutes, mashing a few chickpeas for a thicker gravy.",
        "Garnish with coriander and serve with bhature or rice.",
    ],
    "aloo gobi": [
        "Cut potato and cauliflower into even florets and cubes.",
        "Heat oil, add cumin seeds, then saute onion, ginger and green chilli.",
        "Add tomato and the dry spices and cook into a masala.",
        "Add potato and cauliflower, toss to coat, cover and cook on low heat.",
        "Sprinkle water as needed and cook until vegetables are tender.",
        "Finish with garam masala and coriander, serve with roti.",
    ],
    "vegetable biryani": [
        "Rinse and soak basmati rice for 30 minutes, then drain.",
        "Heat ghee, fry onions until golden and set half aside for garnish.",
        "Add ginger-garlic paste, vegetables and biryani masala; saute for a few minutes.",
        "Layer the marinated vegetables with rice, curd, mint and coriander.",
        "Seal and cook on low heat (dum) for 20-25 minutes.",
        "Fluff gently, garnish with fried onions and serve with raita.",
    ],
    "vegetable poha": [
        "Rinse poha in water until soft, then drain and set aside.",
        "Heat oil, crackle mustard seeds, add curry leaves, onion, potato and green chilli.",
        "Add peas and turmeric and cook until the vegetables are soft.",
        "Add the poha and salt, toss gently and cook for 3-4 minutes.",
        "Squeeze lemon and mix in roasted peanuts.",
        "Garnish with coriander and serve warm.",
    ],
}


def _resolve_key(dish: str, keys) -> str | None:
    """Resolve a dish to a corpus key conservatively.

    Modifiers are stripped before matching. A match requires an exact key, the
    query's tokens being a subset of a longer key (e.g. "rajma" -> "rajma curry"),
    or a very close spelling. The reverse subset direction is deliberately rejected:
    it used to map "chole kulcha" onto "chole". Loose token overlap is also avoided:
    it used to map Palak Paneer and Masala Dosa onto Paneer Butter Masala.
    """
    base, _ = split_modifiers(dish)
    key = _norm(base)
    if not key:
        key = _norm(dish)
    if not key:
        return None

    normalized = {_norm(name): name for name in keys}
    if key in normalized:
        return normalized[key]

    words = key.split()
    generic_tail = {"curry", "recipe", "dish", "meal"}
    while words and words[-1] in generic_tail:
        words.pop()
        shorter = " ".join(words)
        if shorter in normalized:
            return normalized[shorter]

    tokens = _tokens(key)
    candidates: list[tuple[float, float, int, str, str]] = []
    for name, original in normalized.items():
        name_tokens = _tokens(name)
        if not name_tokens or not tokens:
            continue
        if tokens <= name_tokens:
            coverage = len(tokens) / len(name_tokens)
            ratio = difflib.SequenceMatcher(None, key, name).ratio()
            candidates.append((coverage, ratio, -len(name_tokens), name, original))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][4]

    close = difflib.get_close_matches(key, list(normalized), n=1, cutoff=0.86)
    return normalized[close[0]] if close else None


def get_fallback_recipe(dish: str) -> list[tuple[str, float, str, str]] | None:
    key = _resolve_key(dish, FALLBACK_RECIPES.keys())
    return FALLBACK_RECIPES[key] if key else None


def get_fallback_steps(dish: str) -> list[str] | None:
    key = _resolve_key(dish, FALLBACK_STEPS.keys())
    return list(FALLBACK_STEPS[key]) if key else None


def catalog_name(dish: str) -> str | None:
    """Return the properly cased catalogue name for a confidently resolved dish."""
    base, mods = split_modifiers(dish)
    name = _resolve_key(base, dish_catalog())
    if not name:
        return None
    return f"{name} {mods}".strip() if mods else name


def has_catalog_dish(dish: str) -> bool:
    """True when the dish confidently resolves to a known catalogue name."""
    return catalog_name(dish) is not None


def canonical_name(dish: str) -> str | None:
    key = _resolve_key(dish, FALLBACK_RECIPES.keys())
    return " ".join(word.capitalize() for word in key.split()) if key else None


def display_name(dish: str) -> str:
    """Human-friendly label without forcing an unrelated offline recipe match."""
    base, mods = split_modifiers(dish)
    if not mods:
        name = catalog_name(dish)
        if name:
            return name
    key = _resolve_key(base, FALLBACK_RECIPES.keys())
    if key:
        ratio = difflib.SequenceMatcher(None, _norm(base), key).ratio()
        if _tokens(base) == _tokens(key) or ratio >= 0.9:
            label = " ".join(word.capitalize() for word in key.split())
            modifier = " ".join(word.capitalize() for word in mods.split())
            return f"{label} {modifier}".strip()
    return " ".join(word.capitalize() for word in dish.split())


def scale(recipe: list[tuple[str, float, str, str]], servings: int) -> list[tuple[str, float, str, str]]:
    factor = servings / BASE_SERVINGS
    return [(name, round(qty * factor, 2), unit, cat) for name, qty, unit, cat in recipe]
