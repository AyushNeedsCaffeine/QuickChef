from app.agent import recipes


def test_canonical_name_known_dishes():
    assert recipes.canonical_name("dal makhni") == "Dal Makhani"
    assert recipes.canonical_name("Dal Makhani") == "Dal Makhani"
    assert recipes.canonical_name("paneer butter masala") == "Paneer Butter Masala"
    assert recipes.canonical_name("chole") == "Chole"


def test_canonical_name_unknown_returns_none():
    assert recipes.canonical_name("unicorn stew") is None
    assert recipes.canonical_name("") is None


def test_catalog_resolution_is_strict():
    assert recipes.catalog_name("Chole Kulche") == "Chole Kulche"
    assert recipes.catalog_name("chole kulcha") == "Chole Kulche"
    assert recipes.catalog_name("Palak Paneer") == "Palak Paneer"
    assert recipes.catalog_name("Masala Dosa") == "Masala Dosa"
    assert recipes.catalog_name("Rajma") == "Rajma Curry"
    assert recipes.catalog_name("Matar Kulcha") is None
    assert recipes.catalog_name("Paneer Tikka") is None


def test_no_false_fallback_matches():
    assert recipes.get_fallback_recipe("palak paneer") is None
    assert recipes.get_fallback_recipe("masala dosa") is None
    assert recipes.get_fallback_recipe("veg pulao") is None


def test_modifier_names_are_preserved():
    assert recipes.has_modifiers("Rajma without onion garlic") is True
    assert recipes.display_name("Rajma without onion garlic") == "Rajma Without Onion Garlic"
    assert recipes.display_name("Dal Makhni") == "Dal Makhani"


def test_catalogue_has_no_duplicate_token_sets():
    catalog = recipes.dish_catalog()
    token_sets = {frozenset(recipes._tokens(name)) for name in catalog}
    assert len(token_sets) == len(catalog)


def test_get_fallback_recipe_scales_to_base():
    recipe = recipes.get_fallback_recipe("dal makhani")
    assert recipe is not None
    assert len(recipe) >= 10
    names = [r[0] for r in recipe]
    assert "Urad Dal Whole" in names


def test_get_fallback_recipe_unknown_returns_none():
    assert recipes.get_fallback_recipe("unicorn stew") is None


def test_get_fallback_steps_present_and_ordered():
    steps = recipes.get_fallback_steps("dal makhani")
    assert steps is not None
    assert 3 <= len(steps) <= 8
    assert all(isinstance(s, str) and s for s in steps)


def test_get_fallback_steps_unknown_returns_none():
    assert recipes.get_fallback_steps("unicorn stew") is None


def test_every_recipe_has_steps():
    for dish in recipes.FALLBACK_RECIPES:
        steps = recipes.get_fallback_steps(dish)
        assert steps, f"missing steps for {dish}"
        assert 3 <= len(steps) <= 8


def test_scale_is_linear():
    recipe = recipes.get_fallback_recipe("chole")
    base = recipes.scale(recipe, 4)
    double = recipes.scale(recipe, 8)
    half = recipes.scale(recipe, 2)
    for (n0, q0, u0, _), (n8, q8, _, _), (n2, q2, _, _) in zip(base, double, half):
        assert n0 == n8 == n2
        assert q8 == round(q0 * 2, 2)
        assert q2 == round(q0 / 2, 2)


def test_scale_preserves_units():
    recipe = recipes.get_fallback_recipe("paneer butter masala")
    scaled = recipes.scale(recipe, 6)
    assert [r[2] for r in scaled] == [r[2] for r in recipe]


def test_resolve_key_exact_substring_and_none():
    keys = list(recipes.FALLBACK_RECIPES.keys())
    assert recipes._resolve_key("chole", keys) == "chole"
    assert recipes._resolve_key("dal makhani curry", keys) == "dal makhani"
    assert recipes._resolve_key("", keys) is None


def test_resolve_key_token_overlap_for_modified_phrase():
    keys = list(recipes.FALLBACK_RECIPES.keys())
    assert recipes._resolve_key("rajma without onion garlic", keys) == "rajma curry"


def test_has_modifiers():
    assert recipes.has_modifiers("Rajma without onion garlic") is True
    assert recipes.has_modifiers("Mix veg with mushrooms") is True
    assert recipes.has_modifiers("Chole extra paneer") is True
    assert recipes.has_modifiers("dal makhni") is False
    assert recipes.has_modifiers("Paneer Butter Masala") is False
