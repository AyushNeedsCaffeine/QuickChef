from app.services.catalog import get_catalog


def test_catalog_loads():
    catalog = get_catalog()
    assert len(catalog.all()) >= 100


def test_resolve_by_name():
    catalog = get_catalog()
    assert catalog.resolve("Onion").id == "onion"


def test_resolve_by_alias():
    catalog = get_catalog()
    assert catalog.resolve("pyaz").id == "onion"
    assert catalog.resolve("haldi").id == "turmeric"
    assert catalog.resolve("black lentils").id == "urad_dal"


def test_resolve_unknown_returns_none():
    catalog = get_catalog()
    assert catalog.resolve("unicorn tears") is None


def test_search_ranks_exact_first():
    catalog = get_catalog()
    results = catalog.search("tomato")
    assert results
    assert results[0].id == "tomato"


def test_resolve_new_ingredients_and_aliases():
    catalog = get_catalog()
    assert catalog.resolve("Pumpkin").id == "pumpkin"
    assert catalog.resolve("kaddu").id == "pumpkin"
    assert catalog.resolve("Kale leaves").id == "kale"
    assert catalog.resolve("Chickpeas (dry)").id == "chickpeas"
    assert catalog.resolve("Chickpeas").id == "chickpeas"
    assert catalog.resolve("Kala chana").id == "kala_chana"
    assert catalog.resolve("Kale chane").id == "kala_chana"
    assert catalog.resolve("Kala Chana (black chickpeas)").id == "kala_chana"
    assert catalog.resolve("Cilantro (fresh coriander leaves)").id == "coriander_leaves"
    assert catalog.resolve("Ginger-Garlic Paste").id == "garlic_paste"


def test_resolve_rejects_weak_token_overlap():
    catalog = get_catalog()
    assert catalog.resolve("Water") is None
    assert catalog.resolve("Kale") is not None
    assert catalog.resolve("Unicorn tears") is None


def test_matcher_does_not_buy_wrong_lookalikes():
    from app.models import Ingredient
    from app.services import matcher

    result = matcher.match_ingredients(
        [
            Ingredient(name="Kala Chana", quantity=200, unit="g"),
            Ingredient(name="Kale leaves", quantity=100, unit="g"),
            Ingredient(name="Chickpeas (dry)", quantity=100, unit="g"),
            Ingredient(name="Water", quantity=200, unit="ml"),
        ]
    )
    ids = {item.product_id for item in result.matched}
    assert ids == {"kala_chana", "kale", "chickpeas"}
    assert [item.name for item in result.pantry] == ["Water"]
    assert result.unmatched == []
