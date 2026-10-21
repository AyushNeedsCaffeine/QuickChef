"""Rule-based evaluators for the golden dataset.

Scores are checks-passed / checks-run. A case passes only when every check
passes, which keeps the golden gate strict without hiding partial progress.
"""
from __future__ import annotations

from typing import Any


def norm(value: Any) -> str:
    text = str(value or "").lower().strip()
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    return " ".join(cleaned.split())


def tokens(value: Any) -> set[str]:
    return set(norm(value).split())


def _result(checks: dict[str, bool], details: dict | None = None) -> dict:
    if not checks:
        return {"score": 0.0, "passed": False, "checks": {}, "details": details or {}}
    passed = sum(1 for ok in checks.values() if ok)
    return {
        "score": round(passed / len(checks), 4),
        "passed": passed == len(checks),
        "checks": checks,
        "details": details or {},
    }


def _names(values: list) -> list[str]:
    names = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("name") or value.get("product_name") or ""
        names.append(norm(value))
    return names


def _group_present(names: list[str], group: list[str]) -> bool:
    name_tokens: set[str] = set()
    for name in names:
        name_tokens |= tokens(name)
    return any(norm(term) in name_tokens or norm(term) in " ".join(names) for term in group)


def _groups_present(names: list[str], groups: list[list[str]]) -> bool:
    return all(_group_present(names, group) for group in groups)


def _groups_absent(names: list[str], groups: list[list[str]]) -> bool:
    return all(not _group_present(names, group) for group in groups)


def _recipe(actual: dict) -> dict:
    return actual.get("recipe") if isinstance(actual.get("recipe"), dict) else actual


def score_dish(expect: dict, actual: dict) -> dict:
    display = actual.get("display") or actual.get("dish") or ""
    candidates = actual.get("candidates") or []
    candidate_names = [norm(c.get("name") if isinstance(c, dict) else c) for c in candidates]
    checks: dict[str, bool] = {}

    if "status" in expect:
        checks["status"] = int(actual.get("status") or 0) == int(expect["status"])
    if "understood" in expect:
        checks["understood"] = bool(actual.get("understood")) == bool(expect["understood"])
    if "display" in expect:
        checks["display"] = norm(display) == norm(expect["display"])
    if "display_one_of" in expect:
        checks["display_one_of"] = any(norm(display) == norm(item) for item in expect["display_one_of"])
    if "display_not" in expect:
        checks["display_not"] = norm(display) != norm(expect["display_not"])
    if "candidates_any" in expect:
        wanted = {norm(item) for item in expect["candidates_any"]}
        checks["candidates_any"] = any(name in wanted for name in candidate_names)
    if expect.get("candidates_none") is True:
        checks["candidates_none"] = not candidate_names
    if "needs_clarification" in expect:
        checks["needs_clarification"] = bool(actual.get("needs_clarification")) == bool(
            expect["needs_clarification"]
        )
    if "modifiers" in expect:
        checks["modifiers"] = bool(actual.get("modifiers")) == bool(expect["modifiers"])
    return _result(checks, {"display": display, "candidates": candidate_names})


def score_suggest(expect: dict, actual: dict) -> dict:
    results = actual.get("results") or []
    names = [norm(item.get("name") if isinstance(item, dict) else item) for item in results]
    checks: dict[str, bool] = {}

    if "names" in expect:
        checks["names"] = names == [norm(name) for name in expect["names"]]
    if "names_include" in expect:
        checks["names_include"] = all(norm(name) in names for name in expect["names_include"])
    if "names_exclude" in expect:
        checks["names_exclude"] = all(norm(name) not in names for name in expect["names_exclude"])
    if "count" in expect:
        checks["count"] = len(names) == int(expect["count"])
    if "first" in expect:
        checks["first"] = bool(names) and names[0] == norm(expect["first"])
    return _result(checks, {"names": names})


def score_recipe(expect: dict, actual: dict) -> dict:
    recipe = _recipe(actual)
    ingredients = recipe.get("ingredients") or []
    names = _names(ingredients)
    steps = recipe.get("steps") or []
    checks: dict[str, bool] = {}

    if "must_include" in expect:
        checks["must_include"] = _groups_present(names, expect["must_include"])
    if "must_exclude" in expect:
        checks["must_exclude"] = _groups_absent(names, expect["must_exclude"])
    if "min_ingredients" in expect:
        checks["min_ingredients"] = len(ingredients) >= int(expect["min_ingredients"])
    if "max_ingredients" in expect:
        checks["max_ingredients"] = len(ingredients) <= int(expect["max_ingredients"])
    if "min_steps" in expect:
        checks["min_steps"] = len(steps) >= int(expect["min_steps"])
    if "max_steps" in expect:
        checks["max_steps"] = len(steps) <= int(expect["max_steps"])
    if "source" in expect:
        checks["source"] = recipe.get("source") == expect["source"]
    if "source_one_of" in expect:
        checks["source_one_of"] = recipe.get("source") in expect["source_one_of"]
    if "notice_contains" in expect:
        checks["notice_contains"] = norm(expect["notice_contains"]) in norm(recipe.get("notice") or "")
    if expect.get("all_quantities_positive") is True:
        checks["all_quantities_positive"] = bool(ingredients) and all(
            float(item.get("quantity") or 0) > 0 for item in ingredients if isinstance(item, dict)
        )
    cart_names = _names((actual.get("cart") or {}).get("items") or [])
    if "min_cart_items" in expect:
        checks["min_cart_items"] = len(cart_names) >= int(expect["min_cart_items"])
    if "cart_must_include" in expect:
        checks["cart_must_include"] = _groups_present(cart_names, expect["cart_must_include"])
    if "cart_must_exclude" in expect:
        checks["cart_must_exclude"] = _groups_absent(cart_names, expect["cart_must_exclude"])
    return _result(
        checks,
        {
            "ingredients": len(ingredients),
            "steps": len(steps),
            "source": recipe.get("source"),
        },
    )


def score_cart(expect: dict, actual: dict) -> dict:
    matched = _names(actual.get("matched") or [])
    unmatched = _names(actual.get("unmatched") or [])
    checks: dict[str, bool] = {}

    if "matched_min" in expect:
        checks["matched_min"] = len(matched) >= int(expect["matched_min"])
    if "unmatched_max" in expect:
        checks["unmatched_max"] = len(unmatched) <= int(expect["unmatched_max"])
    if "matched_any" in expect:
        checks["matched_any"] = _groups_present(matched, expect["matched_any"])
    if "matched_not" in expect:
        checks["matched_not"] = _groups_absent(matched, expect["matched_not"])
    if "unmatched_any" in expect:
        checks["unmatched_any"] = _groups_present(unmatched, expect["unmatched_any"])
    return _result(checks, {"matched": matched, "unmatched": unmatched})


def score_flow(expect: dict, actual: dict) -> dict:
    order = actual.get("order") or {}
    checks: dict[str, bool] = {}

    if "stage" in expect:
        checks["stage"] = actual.get("stage") == expect["stage"]
    if "recipe_source" in expect:
        checks["recipe_source"] = actual.get("recipe_source") == expect["recipe_source"]
    if "min_cart_items" in expect:
        checks["min_cart_items"] = int(actual.get("cart_items") or 0) >= int(expect["min_cart_items"])
    if "total_positive" in expect:
        checks["total_positive"] = float(actual.get("total") or 0) > 0
    if "notice_contains" in expect:
        checks["notice_contains"] = norm(expect["notice_contains"]) in norm(actual.get("notice") or "")
    if expect.get("order_paid") is True:
        checks["order_paid"] = bool(order.get("order_id")) and float(order.get("total") or 0) > 0
    if "payment_method" in expect:
        checks["payment_method"] = order.get("payment_method") == expect["payment_method"]
    if "address" in expect:
        checks["address"] = order.get("address") == expect["address"]
    return _result(checks, {"stage": actual.get("stage"), "error": actual.get("error")})


def score_photo(expect: dict, actual: dict) -> dict:
    checks: dict[str, bool] = {}
    if "kind" in expect:
        checks["kind"] = actual.get("kind") == expect["kind"]
    if "license_present" in expect:
        present = bool((actual.get("license") or "").strip())
        checks["license_present"] = present == bool(expect["license_present"])
    if "artist_present" in expect:
        present = bool((actual.get("artist") or "").strip())
        checks["artist_present"] = present == bool(expect["artist_present"])
    if "source_contains" in expect:
        checks["source_contains"] = norm(expect["source_contains"]) in norm(actual.get("source") or "")
    if "url_prefix" in expect:
        checks["url_prefix"] = str(actual.get("url") or "").startswith(expect["url_prefix"])
    return _result(
        checks,
        {"kind": actual.get("kind"), "url": actual.get("url"), "reason": actual.get("reason")},
    )


def score_edge(expect: dict, actual: dict) -> dict:
    checks: dict[str, bool] = {}
    if "status" in expect:
        checks["status"] = int(actual.get("status") or 0) == int(expect["status"])
    if "understood" in expect:
        checks["understood"] = bool(actual.get("understood")) == bool(expect["understood"])
    if "stage" in expect:
        checks["stage"] = actual.get("stage") == expect["stage"]
    if expect.get("no_server_error") is True:
        checks["no_server_error"] = int(actual.get("status") or 0) < 500
    return _result(checks, {"status": actual.get("status"), "error": actual.get("error")})


def score_scale(expect: dict, actual: dict) -> dict:
    base = actual.get("base_quantities") or {}
    scaled = actual.get("scaled_quantities") or {}
    factor = float(expect.get("factor") or 1)
    tolerance = float(expect.get("tolerance") or 0.05)
    if not base or not scaled:
        return _result({"has_quantities": False}, {"base": base, "scaled": scaled})
    common = set(base) & set(scaled)
    if not common:
        return _result({"common_ingredients": False}, {"base": len(base), "scaled": len(scaled)})
    mismatches = [
        name
        for name in common
        if abs(float(scaled[name]) - float(base[name]) * factor) > tolerance * max(1.0, abs(float(base[name]) * factor))
    ]
    return _result(
        {"common_ingredients": True, "linear_scale": not mismatches},
        {"mismatches": mismatches[:10], "checked": len(common)},
    )


def evaluate(case, actual: dict) -> dict:
    if case.suite == "dish":
        return score_dish(case.expect, actual)
    if case.suite == "recipe":
        if "scale" in case.expect:
            return score_scale(case.expect["scale"], actual)
        return score_recipe(case.expect, actual)
    if case.suite == "suggest":
        return score_suggest(case.expect, actual)
    if case.suite == "cart":
        return score_cart(case.expect, actual)
    if case.suite == "flow":
        return score_flow(case.expect, actual)
    if case.suite == "photo":
        return score_photo(case.expect, actual)
    if case.suite == "edge":
        return score_edge(case.expect, actual)
    return _result({}, {"error": f"unknown suite {case.suite}"})
