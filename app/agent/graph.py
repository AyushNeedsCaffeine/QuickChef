from __future__ import annotations

import difflib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app import config
from app.agent import prompts, recipes
from app.agent.state import AgentState
from app.models import Ingredient
from app.services import matcher
from app.services.cart import cart_service
from app.services.catalog import _norm, get_catalog

log = logging.getLogger(__name__)


class DishCandidate(BaseModel):
    name: str
    description: str = ""
    confidence: float = 0.0


class ParsedInput(BaseModel):
    dish: Optional[str] = None
    canonical_dish: Optional[str] = None
    servings: Optional[int] = None
    candidates: list[DishCandidate] = Field(default_factory=list)
    needs_clarification: bool = False
    source: str = "heuristic"


class MatchCandidate(BaseModel):
    name: str
    description: str = ""
    confidence: float


class MatchSuggestions(BaseModel):
    canonical_dish: Optional[str] = None
    candidates: list[MatchCandidate] = Field(default_factory=list)


class RecipeItem(BaseModel):
    name: str
    quantity: float
    unit: str
    category: str = "other"


class RecipeDraft(BaseModel):
    ingredients: list[RecipeItem] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)


_llm = None


def get_llm():
    global _llm
    if not config.LLM_ENABLED:
        return None
    if _llm is None:
        from langchain_groq import ChatGroq

        _llm = ChatGroq(
            model=config.GROQ_MODEL,
            api_key=config.GROQ_API_KEY,
            temperature=0,
            reasoning_effort=config.GROQ_REASONING_EFFORT,
            max_tokens=config.GROQ_MAX_TOKENS,
            timeout=config.GROQ_TIMEOUT,
            max_retries=config.GROQ_MAX_RETRIES,
        )
    return _llm


def _structured(schema, messages: list, attempts: int = 2, label: str = "llm"):
    """Invoke the LLM with structured output, retrying on transient failures.

    Groq models can intermittently skip the tool/json call; ``json_schema`` mode is
    markedly more reliable than function calling for the gpt-oss family. Failures
    are logged instead of being swallowed silently.
    """
    llm = get_llm()
    if not llm:
        return None
    parser = llm.with_structured_output(schema, method="json_schema")
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        try:
            result = parser.invoke(messages)
            log.debug("%s ok in %.2fs (attempt %d)", label, time.perf_counter() - started, attempt)
            return result
        except Exception as exc:  # noqa: BLE001 - provider errors vary
            log.warning(
                "%s failed in %.2fs (attempt %d/%d): %s: %s",
                label,
                time.perf_counter() - started,
                attempt,
                attempts,
                type(exc).__name__,
                str(exc)[:300],
            )
    return None


def heuristic_parse(message: str) -> ParsedInput:
    text = message.strip()
    low = text.lower()

    servings: Optional[int] = None
    m = re.search(r"(\d{1,3})", text)
    if m:
        servings = int(m.group(1))

    dish = re.sub(r"\d{1,3}", " ", text)
    dish = re.sub(
        r"\b(i want to cook|i want to make|i wanna cook|want to cook|cook|make|prepare|"
        r"recipe for|recipe of|for|people|persons|person|servings|serving|please)\b",
        " ",
        dish,
        flags=re.IGNORECASE,
    )
    dish = re.sub(r"[^\w\s]", " ", dish)
    dish = re.sub(r"\s+", " ", dish).strip()
    if not dish or len(dish) < 2:
        dish = None
    if low.strip().isdigit():
        dish = None
    return ParsedInput(dish=dish, canonical_dish=dish, servings=servings, source="heuristic")


def suggest_catalog_matches(raw: str) -> list[DishCandidate]:
    """Ask the model which catalogue dishes an unknown dish name might mean."""
    catalog = recipes.dish_catalog()
    result = _structured(
        MatchSuggestions,
        [
            SystemMessage(content=prompts.match_system(catalog)),
            HumanMessage(content=f"Dish: {raw}"),
        ],
        label="dish_match",
    )
    if not isinstance(result, MatchSuggestions):
        return []

    allowed = {name.lower(): name for name in catalog}
    proposals: list[MatchCandidate] = []
    if result.canonical_dish:
        proposals.append(MatchCandidate(name=result.canonical_dish, confidence=1.0))
    proposals.extend(result.candidates)

    matches: list[DishCandidate] = []
    seen: set[str] = set()
    for candidate in proposals:
        name = (candidate.name or "").strip()
        key = name.lower()
        if key not in allowed or key in seen:
            continue
        if candidate.confidence < 0.5:
            continue
        seen.add(key)
        matches.append(
            DishCandidate(
                name=allowed[key],
                description=candidate.description,
                confidence=candidate.confidence,
            )
        )

    matches.sort(key=lambda candidate: candidate.confidence, reverse=True)
    if matches:
        floor = max(0.6, matches[0].confidence - 0.25)
        matches = [candidate for candidate in matches if candidate.confidence >= floor]
    return matches[:3]


def _close_catalog_candidates(text: str) -> list[DishCandidate]:
    """Conservative fallback for a missing LLM suggestion.

    Compare the final (head) noun only, so a shared ingredient word such as
    "matar" cannot turn "Matar Kulcha" into "Matar Paneer".
    """
    query_tokens = _norm(text).split()
    if not query_tokens or len(query_tokens[-1]) < 4:
        return []
    head = query_tokens[-1]
    scored: list[tuple[float, str]] = []
    for name in recipes.dish_catalog():
        tokens = _norm(name).split()
        if not tokens or len(tokens[-1]) < 4:
            continue
        score = difflib.SequenceMatcher(None, head, tokens[-1]).ratio()
        if score >= 0.8:
            scored.append((score, name))
    scored.sort(reverse=True)
    return [
        DishCandidate(name=name, description="close catalogue name", confidence=0.6)
        for _, name in scored[:3]
    ]


def parse_input(message: str) -> ParsedInput:
    result = _structured(
        ParsedInput,
        [
            SystemMessage(content=prompts.parse_system()),
            HumanMessage(content=message),
        ],
        label="dish_resolution",
    )
    if not isinstance(result, ParsedInput):
        return heuristic_parse(message)

    result.source = "llm"
    result.candidates = []
    result.needs_clarification = False
    raw = message.strip()
    if recipes.has_modifiers(raw):
        result.canonical_dish = recipes.display_name(raw)
        return result

    canonical = (result.canonical_dish or result.dish or "").strip()
    if canonical:
        if recipes.has_catalog_dish(canonical):
            result.canonical_dish = recipes.catalog_name(canonical) or canonical
        else:
            product = get_catalog().resolve(canonical)
            if product and recipes.has_catalog_dish(product.name):
                result.canonical_dish = recipes.catalog_name(product.name) or product.name
            else:
                matches = suggest_catalog_matches(raw)
                if not matches:
                    matches = _close_catalog_candidates(canonical)
                result.candidates = matches
                result.needs_clarification = bool(matches)
    return result


@dataclass
class ResolvedRecipe:
    ingredients: list[RecipeItem] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    source: str = "llm"


_recipe_cache: dict[tuple[str, int], ResolvedRecipe] = {}
_recipe_cache_lock = threading.Lock()


def _copy_recipe(recipe: ResolvedRecipe) -> ResolvedRecipe:
    return ResolvedRecipe(
        ingredients=[RecipeItem(**item.model_dump()) for item in recipe.ingredients],
        steps=list(recipe.steps),
        source=recipe.source,
    )


def resolve_recipe(dish: str, servings: int) -> ResolvedRecipe | None:
    cache_key = (_norm(dish), int(servings))
    with _recipe_cache_lock:
        cached = _recipe_cache.get(cache_key)
    if cached is not None:
        return _copy_recipe(cached)

    result = _structured(
        RecipeDraft,
        [
            SystemMessage(content=prompts.EXTRACT_SYSTEM),
            HumanMessage(content=f"Dish: {dish}\nServings: {servings}"),
        ],
        label=f"recipe:{dish}",
    )
    recipe: ResolvedRecipe | None = None
    if isinstance(result, RecipeDraft) and result.ingredients:
        recipe = ResolvedRecipe(ingredients=result.ingredients, steps=result.steps, source="llm")
    else:
        fallback = recipes.get_fallback_recipe(dish)
        if fallback:
            recipe = ResolvedRecipe(
                ingredients=[
                    RecipeItem(name=n, quantity=q, unit=u, category=c)
                    for n, q, u, c in recipes.scale(fallback, servings)
                ],
                steps=recipes.get_fallback_steps(dish) or [],
                source="offline",
            )

    if recipe is not None:
        with _recipe_cache_lock:
            _recipe_cache[cache_key] = _copy_recipe(recipe)
    return recipe


def extract_ingredients(dish: str, servings: int) -> list[RecipeItem] | None:
    recipe = resolve_recipe(dish, servings)
    return recipe.ingredients if recipe else None


def _last_human(state: AgentState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return ""


def understand(state: AgentState) -> dict:
    if state.get("preparsed"):
        update: dict = {"needs_clarification": False, "candidates": []}
        if state.get("dish"):
            update["dish"] = state["dish"]
        if state.get("servings"):
            update["servings"] = state["servings"]
        return update

    parsed = parse_input(_last_human(state))
    update = {}
    dish = parsed.canonical_dish or parsed.dish
    if dish:
        update["dish"] = dish
    if parsed.servings:
        update["servings"] = parsed.servings
    if parsed.candidates:
        update["candidates"] = [candidate.model_dump() for candidate in parsed.candidates]
    update["needs_clarification"] = bool(parsed.needs_clarification and parsed.candidates)
    return update


def route_after_understand(state: AgentState) -> str:
    if not state.get("dish"):
        return "ask_dish"
    if state.get("needs_clarification") and state.get("candidates"):
        return "clarify"
    if not state.get("servings"):
        return "ask_servings"
    return "extract"


def ask_dish(state: AgentState) -> dict:
    reply = "What would you like to cook today? Tell me a dish and I'll build your cart."
    return {"stage": "await_dish", "reply": reply, "messages": [AIMessage(content=reply)]}


def clarify(state: AgentState) -> dict:
    names = [c.get("name") for c in state.get("candidates", []) if c.get("name")][:3]
    options = ", ".join(names)
    reply = f"I can make that more than one way. Did you mean {options}?"
    return {
        "stage": "await_dish",
        "reply": reply,
        "messages": [AIMessage(content=reply)],
        "needs_clarification": False,
    }


def ask_servings(state: AgentState) -> dict:
    reply = f"Nice, {state['dish']}! How many people are you cooking for?"
    return {"stage": "await_servings", "reply": reply, "messages": [AIMessage(content=reply)]}


def extract(state: AgentState) -> dict:
    dish = state["dish"]
    servings = int(state["servings"])
    recipe = resolve_recipe(dish, servings)
    if not recipe or not recipe.ingredients:
        reply = (
            f"Sorry, I couldn't build a recipe for '{dish}'. "
            "Could you name a well-known dish (e.g. Dal Makhani, Paneer Butter Masala, Chole)?"
        )
        return {
            "dish": None,
            "steps": [],
            "stage": "await_dish",
            "error": f"No recipe found for '{dish}'.",
            "reply": reply,
            "messages": [AIMessage(content=reply)],
        }
    return {
        "ingredients": [i.model_dump() for i in recipe.ingredients],
        "steps": list(recipe.steps),
        "recipe_source": recipe.source,
        "error": None,
        "stage": "matching",
    }


def route_after_extract(state: AgentState) -> str:
    return "match" if state.get("stage") == "matching" else END


def match(state: AgentState) -> dict:
    session_id = state["session_id"]
    ingredients = [Ingredient(**i) for i in state.get("ingredients", [])]
    result = matcher.match_ingredients(ingredients)
    cart_service.clear(session_id)
    cart_service.add_items(session_id, result.matched)

    count = len(result.matched)
    reply = f"I've added {count} ingredients for {state['dish']} ({state['servings']} people) to your cart."
    if result.unmatched:
        names = ", ".join(i.name for i in result.unmatched)
        reply += f" I couldn't find: {names}."
    reply += " Review the cart and confirm to place your order."

    return {
        "cart": [c.model_dump() for c in result.matched],
        "unmatched": [i.name for i in result.unmatched],
        "stage": "cart_review",
        "reply": reply,
        "messages": [AIMessage(content=reply)],
    }


def cart_review(state: AgentState) -> dict:
    decision = interrupt(
        {
            "stage": "cart_review",
            "session_id": state["session_id"],
            "cart": state.get("cart", []),
        }
    )
    action = (decision or {}).get("action", "confirm")
    if action == "confirm":
        return {
            "stage": "placing",
            "payment_method": (decision or {}).get("method", "cod"),
            "address": (decision or {}).get("address", "Home"),
        }
    reply = "No problem, I've kept your cart. Tell me when you want to place the order."
    return {"stage": "cancelled", "reply": reply, "messages": [AIMessage(content=reply)]}


def route_after_review(state: AgentState) -> str:
    return "place_order" if state.get("stage") == "placing" else END


def place_order(state: AgentState) -> dict:
    session_id = state["session_id"]
    try:
        order = cart_service.place_order(
            session_id,
            address=state.get("address", "Home"),
            payment_method=state.get("payment_method", "cod"),
        )
    except ValueError as exc:
        reply = f"Couldn't place the order: {exc}"
        return {"stage": "done", "reply": reply, "messages": [AIMessage(content=reply)]}

    lines = [f"Order {order.order_id} placed for {state['dish']}!"]
    for item in order.items:
        lines.append(f"- {item.name} x{item.quantity} — Rs {item.line_total}")
    lines.append(f"Total: Rs {order.total} (incl. fees). Your order will arrive in ~10 minutes.")
    reply = "\n".join(lines)
    return {
        "stage": "done",
        "order": order.model_dump(),
        "reply": reply,
        "messages": [AIMessage(content=reply)],
    }


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("understand", understand)
    builder.add_node("ask_dish", ask_dish)
    builder.add_node("clarify", clarify)
    builder.add_node("ask_servings", ask_servings)
    builder.add_node("extract", extract)
    builder.add_node("match", match)
    builder.add_node("cart_review", cart_review)
    builder.add_node("place_order", place_order)

    builder.add_edge(START, "understand")
    builder.add_conditional_edges(
        "understand",
        route_after_understand,
        {
            "ask_dish": "ask_dish",
            "clarify": "clarify",
            "ask_servings": "ask_servings",
            "extract": "extract",
        },
    )
    builder.add_edge("ask_dish", END)
    builder.add_edge("clarify", END)
    builder.add_edge("ask_servings", END)
    builder.add_conditional_edges(
        "extract",
        route_after_extract,
        {"match": "match", END: END},
    )
    builder.add_edge("match", "cart_review")
    builder.add_conditional_edges(
        "cart_review",
        route_after_review,
        {"place_order": "place_order", END: END},
    )
    builder.add_edge("place_order", END)

    return builder.compile(checkpointer=MemorySaver())


graph = build_graph()
