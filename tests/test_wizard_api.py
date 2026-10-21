import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app.agent import graph as graph_mod
from app.main import app
from app.services import synonyms


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setattr(graph_mod, "get_llm", lambda: None)


@pytest.fixture(autouse=True)
def isolated_synonyms(monkeypatch, tmp_path):
    monkeypatch.setattr(synonyms, "STORE_PATH", tmp_path / "synonyms.json")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def session(client):
    return client.post("/api/session").json()["session_id"]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_homepage(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "QuickChef" in r.text


def test_dish_understood(client, session):
    r = client.post(f"/api/dish/{session}", json={"dish": "dal makhni"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is True
    assert body["display"] == "Dal Makhani"
    assert body["modifiers"] is False


def test_llm_display_uses_canonical_name(client, session, monkeypatch):
    parsed = graph_mod.ParsedInput(
        dish="kale chane", canonical_dish="Kala Chana", source="llm"
    )
    monkeypatch.setattr(main_mod, "parse_input", lambda _raw: parsed)
    r = client.post(f"/api/dish/{session}", json={"dish": "kale chane"})
    assert r.status_code == 200
    body = r.json()
    assert body["dish"] == "Kala Chana"
    assert body["display"] == "Kala Chana"


def test_dish_preserves_modifiers(client, session):
    r = client.post(f"/api/dish/{session}", json={"dish": "Rajma without onion garlic"})
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] is True
    assert body["dish"].startswith("Rajma Curry")
    assert "without onion garlic" in body["dish"]
    assert body["modifiers"] is True
    assert body["display"] == "Rajma Without Onion Garlic"


def test_servings_offline_modifier_sets_notice(client, session):
    r = client.post(f"/api/servings/{session}", json={"dish": "Rajma without onion garlic", "servings": 4})
    assert r.status_code == 200
    recipe = r.json()["recipe"]
    assert recipe["modifiers"] is True
    assert recipe["source"] == "offline"
    assert recipe["notice"]  # non-empty: offline can't honour the modifier


def test_servings_plain_has_no_notice(client, session):
    r = client.post(f"/api/servings/{session}", json={"dish": "chole", "servings": 4})
    assert r.status_code == 200
    recipe = r.json()["recipe"]
    assert recipe["modifiers"] is False
    assert recipe["notice"] is None


def test_dish_empty_rejected(client, session):
    r = client.post(f"/api/dish/{session}", json={"dish": "   "})
    assert r.status_code == 422
    assert r.json()["understood"] is False


def test_servings_builds_cart_and_recipe(client, session):
    r = client.post(f"/api/servings/{session}", json={"dish": "dal makhni", "servings": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "cart_review"
    assert body["paused"] is True
    assert len(body["cart"]["items"]) > 0
    assert len(body["recipe"]["ingredients"]) > 0
    assert len(body["recipe"]["steps"]) > 0
    assert body["recipe"]["source"] == "offline"


def test_servings_unknown_dish(client, session):
    r = client.post(f"/api/servings/{session}", json={"dish": "unicorn stew", "servings": 3})
    assert r.status_code == 422
    assert "reliable recipe" in r.json()["message"]


def test_session_view_reflects_state(client, session):
    client.post(f"/api/servings/{session}", json={"dish": "chole", "servings": 2})
    r = client.get(f"/api/session/{session}")
    assert r.status_code == 200
    body = r.json()
    assert body["dish"] == "Chole"
    assert body["servings"] == 2
    assert len(body["cart"]["items"]) > 0


def test_cart_add_update_remove(client, session):
    client.post(f"/api/servings/{session}", json={"dish": "chole", "servings": 2})
    before = len(client.get(f"/api/cart/{session}").json()["items"])

    add = client.post(f"/api/cart/{session}/items", json={"product_id": "milk", "quantity": 1})
    assert len(add.json()["items"]) == before + 1

    client.patch(f"/api/cart/{session}/items/milk", json={"quantity": 5})
    milk = [i for i in client.get(f"/api/cart/{session}").json()["items"] if i["product_id"] == "milk"][0]
    assert milk["quantity"] == 5

    rem = client.delete(f"/api/cart/{session}/items/milk")
    assert len(rem.json()["items"]) == before


def test_pay_places_order(client, session):
    client.post(f"/api/servings/{session}", json={"dish": "paneer butter masala", "servings": 4})
    r = client.post(f"/api/order/{session}/pay", json={"method": "upi"})
    assert r.status_code == 200
    order = r.json()["order"]
    assert order["order_id"].startswith("QC")
    assert order["payment_method"] == "upi"
    assert order["total"] > 0
    # cart cleared after payment
    assert client.get(f"/api/cart/{session}").json()["items"] == []


def test_pay_without_pending_order(client, session):
    r = client.post(f"/api/order/{session}/pay", json={"method": "cod"})
    assert r.status_code == 400


def test_free_delivery_threshold(client, session):
    # cashew pack is ₹210 -> above the ₹199 free-delivery threshold
    client.post(f"/api/cart/{session}/items", json={"product_id": "cashew", "quantity": 1})
    totals = client.get(f"/api/cart/{session}").json()["totals"]
    assert totals["delivery_fee"] == 0


def test_servings_exposes_unmatched_key(client, session):
    body = client.post(f"/api/servings/{session}", json={"dish": "chole", "servings": 4}).json()
    assert isinstance(body["recipe"]["unmatched"], list)


def test_pay_records_address(client, session):
    client.post(f"/api/servings/{session}", json={"dish": "chole", "servings": 2})
    order = client.post(f"/api/order/{session}/pay", json={"method": "card", "address": "12 MG Road"}).json()["order"]
    assert order["payment_method"] == "card"
    assert order["address"] == "12 MG Road"


def test_cancel_pending_order(client, session):
    client.post(f"/api/servings/{session}", json={"dish": "rajma curry", "servings": 3})
    r = client.post(f"/api/cart/{session}/cancel")
    assert r.status_code == 200
    assert r.json()["stage"] == "cancelled"


def test_cancel_without_pending_order(client, session):
    r = client.post(f"/api/cart/{session}/cancel")
    assert r.status_code == 400


def test_chat_returns_review_reminder_while_paused(client, session):
    client.post(f"/api/servings/{session}", json={"dish": "aloo gobi", "servings": 3})
    body = client.post(f"/api/chat/{session}", json={"message": "add more"}).json()
    assert body["paused"] is True
    assert "cart is ready" in body["reply"].lower()


def test_dish_returns_catalogue_candidate(client, session, monkeypatch):
    parsed = graph_mod.ParsedInput(
        dish="Matar Kulcha",
        canonical_dish="Matar Kulcha",
        candidates=[
            graph_mod.DishCandidate(name="Chole Kulche", description="colloquial", confidence=1.0)
        ],
        needs_clarification=True,
        source="llm",
    )
    monkeypatch.setattr(main_mod, "parse_input", lambda message: parsed)
    body = client.post(f"/api/dish/{session}", json={"dish": "Matar Kulcha"}).json()
    assert body["dish"] == "Matar Kulcha"
    assert body["candidates"] == [
        {"name": "Chole Kulche", "description": "colloquial", "confidence": 1.0}
    ]
    assert body["needs_clarification"] is True


def test_learned_synonym_wins_on_next_lookup(client, session):
    r = client.post("/api/synonyms", json={"term": "Matar Kulcha", "canonical": "Chole Kulche"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    body = client.post(f"/api/dish/{session}", json={"dish": "Matar Kulcha"}).json()
    assert body["dish"] == "Chole Kulche"
    assert body["display"] == "Chole Kulche"
    assert body["candidates"] == []
    assert body["needs_clarification"] is False


def test_learned_synonym_skips_parse_llm(client, session, monkeypatch):
    synonyms.learn("Matar Kulcha", "Chole Kulche")

    def fail_parse(_message):
        raise AssertionError("learned synonyms should not call the LLM")

    monkeypatch.setattr(main_mod, "parse_input", fail_parse)
    body = client.post(f"/api/dish/{session}", json={"dish": "Matar Kulcha"}).json()
    assert body["dish"] == "Chole Kulche"
    assert body["display"] == "Chole Kulche"
    assert body["candidates"] == []


def test_synonym_validation(client):
    assert client.post("/api/synonyms", json={"term": "", "canonical": "Chole Kulche"}).status_code == 422
    assert client.post("/api/synonyms", json={"term": "Matar Kulcha", "canonical": ""}).status_code == 422


def test_unknown_dish_is_rejected(client, session):
    r = client.post(f"/api/dish/{session}", json={"dish": "Sushi"})
    assert r.status_code == 422
    assert r.json()["understood"] is False
    assert "reliable recipe" in r.json()["message"]


def test_custom_dish_can_be_new_when_llm_is_enabled(client, session):
    r = client.post(f"/api/dish/{session}", json={"dish": "Unicorn stew", "custom": True})
    assert r.status_code == 200
    assert r.json()["dish"] == "Unicorn stew"
    assert r.json()["custom"] is True


def test_custom_unknown_dish_is_rejected_without_llm(client, session, monkeypatch):
    monkeypatch.setattr(main_mod.config, "LLM_ENABLED", False)
    r = client.post(f"/api/dish/{session}", json={"dish": "Unicorn stew", "custom": True})
    assert r.status_code == 422
    assert "AI chef" in r.json()["message"]


def test_custom_llm_normalizes_typo_to_catalogue(client, session, monkeypatch):
    parsed = graph_mod.ParsedInput(
        dish="rasgula", canonical_dish="Rasgulla", source="llm"
    )
    monkeypatch.setattr(main_mod, "parse_input", lambda _raw: parsed)
    r = client.post(f"/api/dish/{session}", json={"dish": "rasgula", "custom": True})
    assert r.status_code == 200
    body = r.json()
    assert body["dish"] == "Rasgulla"
    assert body["display"] == "Rasgulla"
    assert body["custom"] is True


def test_custom_known_dish_is_accepted(client, session):
    r = client.post(f"/api/dish/{session}", json={"dish": "Paneer Tikka", "custom": True})
    assert r.status_code == 200
    assert r.json()["dish"] == "Paneer Tikka"
    assert r.json()["custom"] is True


def test_suggest_endpoint_chaap_and_and_semantics(client):
    chaap = client.get("/api/dish/suggest", params={"q": "chaap"}).json()["results"]
    assert [item["name"] for item in chaap] == [
        "Soya Chaap",
        "Malai Soy Chaap",
        "Afghani Soy Chaap",
        "Tandoori Soy Chaap",
    ]
    malai = client.get("/api/dish/suggest", params={"q": "malai chaap"}).json()["results"]
    assert [item["name"] for item in malai] == ["Malai Soy Chaap"]
    paneer = client.get("/api/dish/suggest", params={"q": "paneer"}).json()["results"]
    assert "Paneer Tikka" in [item["name"] for item in paneer]
    assert "Soya Chaap" not in [item["name"] for item in paneer]


def test_suggest_endpoint_rasgula_typo(client):
    names = [
        item["name"]
        for item in client.get("/api/dish/suggest", params={"q": "rasgula"}).json()["results"]
    ]
    assert names == ["Rasgulla"]


def test_suggest_endpoint_empty_and_unknown(client):
    popular = client.get("/api/dish/suggest", params={"limit": 4}).json()["results"]
    assert [item["name"] for item in popular] == ["Garlic Naan", "Paneer Butter Masala", "Dal Makhani", "Chole Kulche"]
    assert client.get("/api/dish/suggest", params={"q": "unicorn"}).json()["results"] == []


def test_homepage_has_typeahead_and_custom_only_photo_ui(client):
    html = client.get("/").text
    assert 'id="dish-suggestions"' in html
    assert 'id="custom-dish-input"' in html
    assert 'id="brand-home"' in html
    assert 'id="dc-photo"' in html
    assert 'src="/static/logo-160.png"' in html
    assert "recipe-photo" not in html
    assert "dc-media" not in html


def test_photo_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        main_mod.photos,
        "find_photo",
        lambda dish: {"kind": "photo", "url": "/static/dish_photos/test.jpg"},
    )
    r = client.get("/api/dish/photo", params={"dish": "Chole Kulche"})
    assert r.status_code == 200
    assert r.json()["kind"] == "photo"
    assert r.json()["dish"] == "Chole Kulche"
    assert client.get("/api/dish/photo").status_code == 422


def test_servings_passes_custom_flag(client, session, monkeypatch):
    captured = {}

    def fake_invoke(state, config=None):
        captured.update(state)
        return {
            "stage": "cart_review",
            "dish": state.get("dish"),
            "servings": state.get("servings"),
            "ingredients": [],
            "steps": [],
        }

    monkeypatch.setattr(main_mod.graph, "invoke", fake_invoke)
    r = client.post(
        f"/api/servings/{session}",
        json={"dish": "Misal Pav", "servings": 2, "custom": True},
    )
    assert r.status_code == 200
    assert captured["custom"] is True
    assert captured["dish"] == "Misal Pav"


def test_servings_passes_preparsed_dish(client, session, monkeypatch):
    captured = {}

    def fake_invoke(state, config=None):
        captured.update(state)
        return {
            "stage": "cart_review",
            "dish": state.get("dish"),
            "servings": state.get("servings"),
            "ingredients": [],
            "steps": [],
        }

    monkeypatch.setattr(main_mod.graph, "invoke", fake_invoke)
    r = client.post(f"/api/servings/{session}", json={"dish": "Chole Kulche", "servings": 3})
    assert r.status_code == 200
    assert captured["preparsed"] is True
    assert captured["dish"] == "Chole Kulche"
    assert captured["servings"] == 3


def test_static_assets_served(client):
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/script.js").status_code == 200
    assert client.get("/static/doodles.png").status_code == 200
    assert client.get("/static/dish-placeholder.svg").status_code == 200
    assert client.get("/static/logo-160.png").status_code == 200
    assert client.get("/static/favicon.png").status_code == 200
    card_art = [
        "naan", "paneer-butter-masala", "dal-makhani", "chole-kulche", "rajma-chawal",
        "aloo-gobi", "palak-paneer", "veg-biryani", "veg-pulao", "idli-sambar",
        "masala-dosa", "pav-bhaji", "pasta", "hakka-noodles", "rasmalai", "gulab-jamun",
    ]
    for art in card_art:
        assert client.get(f"/static/foods/{art}.svg").status_code == 200

