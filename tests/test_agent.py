import pytest
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.agent import graph as graph_mod
from app.agent.graph import build_graph, heuristic_parse
from app.services.cart import CartService
import app.services.cart as cart_module


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setattr(graph_mod, "get_llm", lambda: None)


@pytest.fixture
def fresh(monkeypatch):
    svc = CartService()
    monkeypatch.setattr(cart_module, "cart_service", svc)
    monkeypatch.setattr(graph_mod, "cart_service", svc)
    g = build_graph()
    return g, {"configurable": {"thread_id": "test-thread"}}


def test_extract_allows_custom_non_catalogue_dish(monkeypatch):
    recipe = graph_mod.ResolvedRecipe(
        ingredients=[
            graph_mod.RecipeItem(name="Milk", quantity=500, unit="ml", category="dairy")
        ],
        steps=["Boil the milk and simmer."],
        source="llm",
    )
    monkeypatch.setattr(graph_mod, "resolve_recipe", lambda dish, servings: recipe)
    result = graph_mod.extract({"dish": "Misal Pav", "servings": 4, "custom": True})
    assert result["stage"] == "matching"
    assert result["recipe_source"] == "llm"


def test_extract_still_rejects_uncatalogued_non_custom_dish():
    result = graph_mod.extract({"dish": "Misal Pav", "servings": 4})
    assert result["stage"] == "await_dish"
    assert result["dish"] is None


def test_heuristic_parse_dish_and_servings():
    parsed = heuristic_parse("I want to cook Dal Makhani for 6 people")
    assert parsed.dish
    assert "dal" in parsed.dish.lower()
    assert parsed.servings == 6


def test_heuristic_parse_servings_only():
    parsed = heuristic_parse("4")
    assert parsed.servings == 4
    assert parsed.dish is None


def test_full_happy_path(fresh):
    g, cfg = fresh
    g.invoke({"session_id": "test-thread", "messages": [HumanMessage(content="I want to cook dal makhni")]}, cfg)
    state = g.invoke({"session_id": "test-thread", "messages": [HumanMessage(content="4 people")]}, cfg)
    assert state["stage"] == "cart_review"
    assert len(state["cart"]) > 0
    assert g.get_state(cfg).next

    result = g.invoke(Command(resume={"action": "confirm"}), cfg)
    assert result["stage"] == "done"
    assert result["order"]["order_id"].startswith("QC")
    assert result["order"]["total"] > 0


def test_cancel_path(fresh):
    g, cfg = fresh
    g.invoke({"session_id": "test-thread", "messages": [HumanMessage(content="paneer butter masala")]}, cfg)
    g.invoke({"session_id": "test-thread", "messages": [HumanMessage(content="2")]}, cfg)
    result = g.invoke(Command(resume={"action": "cancel"}), cfg)
    assert result["stage"] == "cancelled"


def test_unknown_dish_reprompts(fresh):
    g, cfg = fresh
    g.invoke({"session_id": "test-thread", "messages": [HumanMessage(content="unicorn stew")]}, cfg)
    state = g.invoke({"session_id": "test-thread", "messages": [HumanMessage(content="3")]}, cfg)
    assert state["stage"] == "await_dish"
    assert state.get("dish") is None


def test_servings_first_then_dish(fresh):
    g, cfg = fresh
    first = g.invoke({"session_id": "test-thread", "messages": [HumanMessage(content="4")]}, cfg)
    assert first["stage"] == "await_dish"
    second = g.invoke({"session_id": "test-thread", "messages": [HumanMessage(content="chole")]}, cfg)
    assert second["stage"] == "cart_review"
    assert len(second["cart"]) > 0
