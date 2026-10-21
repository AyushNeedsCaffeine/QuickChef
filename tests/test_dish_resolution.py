from app.agent import graph


def test_known_dish_normalises_without_matcher(monkeypatch):
    calls = []

    def fake_structured(schema, messages, attempts=2, label="llm"):
        calls.append(label)
        assert schema is graph.ParsedInput
        return graph.ParsedInput(dish="Dal Makhni", canonical_dish="Dal Makhni")

    monkeypatch.setattr(graph, "_structured", fake_structured)
    parsed = graph.parse_input("Dal Makhni")

    assert parsed.canonical_dish == "Dal Makhani"
    assert parsed.candidates == []
    assert calls == ["dish_resolution"]


def test_matar_paneer_is_known_and_not_suggested_as_butter_masala(monkeypatch):
    def fake_structured(schema, messages, attempts=2, label="llm"):
        assert schema is graph.ParsedInput
        return graph.ParsedInput(dish="Matar Paneer", canonical_dish="Matar Paneer")

    monkeypatch.setattr(graph, "_structured", fake_structured)
    parsed = graph.parse_input("Matar Paneer")

    assert parsed.canonical_dish == "Matar Paneer"
    assert parsed.candidates == []
    assert parsed.needs_clarification is False


def test_unknown_dish_gets_catalogue_candidates(monkeypatch):
    calls = []

    def fake_structured(schema, messages, attempts=2, label="llm"):
        calls.append(label)
        if schema is graph.ParsedInput:
            return graph.ParsedInput(dish="Matar Kulcha", canonical_dish="Matar Kulcha")
        assert schema is graph.MatchSuggestions
        return graph.MatchSuggestions(
            candidates=[
                graph.MatchCandidate(name="Chole Kulche", description="colloquial name", confidence=0.92),
                graph.MatchCandidate(name="Chole", description="served with chole", confidence=0.55),
                graph.MatchCandidate(name="Aloo Gobi", description="unrelated", confidence=0.2),
            ]
        )

    monkeypatch.setattr(graph, "_structured", fake_structured)
    parsed = graph.parse_input("Matar Kulcha")

    assert parsed.canonical_dish == "Matar Kulcha"
    assert [candidate.name for candidate in parsed.candidates] == ["Chole Kulche"]
    assert parsed.needs_clarification is True
    assert calls == ["dish_resolution", "dish_match"]


def test_empty_llm_candidates_fall_back_to_close_catalogue_name(monkeypatch):
    def fake_structured(schema, messages, attempts=2, label="llm"):
        if schema is graph.ParsedInput:
            return graph.ParsedInput(dish="Matar Kulcha", canonical_dish="Matar Kulcha")
        return graph.MatchSuggestions(candidates=[])

    monkeypatch.setattr(graph, "_structured", fake_structured)
    parsed = graph.parse_input("Matar Kulcha")

    assert parsed.canonical_dish == "Matar Kulcha"
    assert [candidate.name for candidate in parsed.candidates] == ["Chole Kulche"]
    assert parsed.needs_clarification is True


def test_unknown_dish_with_no_match_stays_literal(monkeypatch):
    def fake_structured(schema, messages, attempts=2, label="llm"):
        if schema is graph.ParsedInput:
            return graph.ParsedInput(dish="Sushi", canonical_dish="Sushi")
        return graph.MatchSuggestions(candidates=[])

    monkeypatch.setattr(graph, "_structured", fake_structured)
    parsed = graph.parse_input("Sushi")

    assert parsed.canonical_dish == "Sushi"
    assert parsed.candidates == []
    assert parsed.needs_clarification is False


def test_modifiers_skip_matcher_and_are_preserved(monkeypatch):
    calls = []

    def fake_structured(schema, messages, attempts=2, label="llm"):
        calls.append(label)
        return graph.ParsedInput(dish="Rajma without onion garlic", canonical_dish="Rajma Curry")

    monkeypatch.setattr(graph, "_structured", fake_structured)
    parsed = graph.parse_input("Rajma without onion garlic")

    assert parsed.canonical_dish == "Rajma Without Onion Garlic"
    assert parsed.candidates == []
    assert calls == ["dish_resolution"]


def test_hinglish_dishes_canonicalise_to_catalogue_names():
    from app.agent import recipes

    assert recipes.display_name("maggi") == "Maggi Noodles"
    assert recipes.display_name("pumpkin") == "Pumpkin Sabzi"
    assert recipes.display_name("kala chana") == "Kala Chana"
    assert recipes.display_name("masala chana") == "Masala Chana"
    assert recipes.display_name("rasgula") == "Rasgulla"
    assert recipes.get_fallback_recipe("rasgula") is not None


def test_kale_chane_resolves_to_kala_chana(monkeypatch):
    def fake_structured(schema, messages, attempts=2, label="llm"):
        assert schema is graph.ParsedInput
        return graph.ParsedInput(dish="kale chane", canonical_dish="black chickpeas")

    monkeypatch.setattr(graph, "_structured", fake_structured)
    parsed = graph.parse_input("kale chane")
    assert parsed.canonical_dish == "Kala Chana"
    assert parsed.candidates == []
    assert parsed.needs_clarification is False
