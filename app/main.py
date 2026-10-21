from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from starlette.requests import Request

from app import config
from app.agent import recipes
from app.agent.graph import graph, parse_input
from app.models import (
    CartAddRequest,
    CartUpdateRequest,
    ChatRequest,
    ConfirmRequest,
    DishRequest,
    FeedbackRequest,
    PayRequest,
    ServingsRequest,
    SynonymRequest,
)
from app.services import feedback, photos, synonyms
from app.services.cart import cart_service
from app.services.catalog import get_catalog

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="QuickChef", version="2.0.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _thread(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _run_config(session_id: str, run_name: str = "graph", **meta) -> dict:
    """Graph invoke config enriched for LangSmith tracing (name, tags, metadata)."""
    metadata = {"session_id": session_id}
    metadata.update({k: v for k, v in meta.items() if v is not None})
    return {
        "configurable": {"thread_id": session_id},
        "run_name": run_name,
        "tags": ["quickchef", run_name],
        "metadata": metadata,
    }


def _snapshot(session_id: str):
    return graph.get_state(_thread(session_id))


def _session_view(session_id: str) -> dict:
    snap = _snapshot(session_id)
    values = snap.values or {}
    return {
        "session_id": session_id,
        "stage": values.get("stage"),
        "dish": values.get("dish"),
        "servings": values.get("servings"),
        "reply": values.get("reply"),
        "paused": bool(snap.next),
    }


def _recipe_view(values: dict) -> dict:
    dish = values.get("dish")
    source = values.get("recipe_source")
    modified = recipes.has_modifiers(dish or "")
    notice = None
    if modified and source == "offline":
        notice = (
            "Offline mode can't apply your modification (e.g. \"without onion\"). "
            "Enable the AI chef (Groq key) to honour it."
        )
    return {
        "dish": dish,
        "servings": values.get("servings"),
        "ingredients": values.get("ingredients", []),
        "steps": values.get("steps", []),
        "unmatched": values.get("unmatched", []),
        "source": source,
        "modifiers": modified,
        "notice": notice,
    }


def _cart_view(session_id: str) -> dict:
    items = [item.model_dump() for item in cart_service.get_cart(session_id)]
    return {"items": items, "totals": cart_service.totals(session_id)}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"llm_enabled": config.LLM_ENABLED})


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_enabled": config.LLM_ENABLED,
        "model": config.GROQ_MODEL if config.LLM_ENABLED else None,
        "reasoning_effort": config.GROQ_REASONING_EFFORT if config.LLM_ENABLED else None,
        "photos": config.PHOTO_ENABLED,
        "feedback": config.FEEDBACK_ENABLED,
        "tracing": config.LANGSMITH_ENABLED,
        "tracing_project": config.LANGSMITH_PROJECT if config.LANGSMITH_ENABLED else None,
    }


@app.post("/api/session")
def create_session():
    session_id = uuid.uuid4().hex
    return {"session_id": session_id, "stage": None, "dish": None, "servings": None, "reply": None, "paused": False}


@app.post("/api/chat/{session_id}")
def chat(session_id: str, body: ChatRequest):
    snap = _snapshot(session_id)
    if snap.next:
        return {
            "reply": "Your cart is ready. Review it and confirm to place your order.",
            "stage": (snap.values or {}).get("stage", "cart_review"),
            "paused": True,
        }
    result = graph.invoke(
        {"session_id": session_id, "messages": [HumanMessage(content=body.message.strip())]},
        _run_config(session_id, "chat"),
    )
    return {
        "reply": result.get("reply", ""),
        "stage": result.get("stage"),
        "dish": result.get("dish"),
        "servings": result.get("servings"),
        "paused": bool(_snapshot(session_id).next),
    }


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    snap = _snapshot(session_id)
    values = snap.values or {}
    return {
        **_session_view(session_id),
        "recipe": _recipe_view(values),
        "cart": _cart_view(session_id),
    }


UNKNOWN_DISH_MESSAGE = (
    "I don’t have a reliable recipe for that dish yet. "
    "Pick one from the list or try another name."
)


def _dish_response(raw: str, canonical: str, *, source: str, custom: bool = False) -> dict:
    modified = recipes.has_modifiers(raw)
    return {
        "understood": True,
        "dish": canonical,
        "display": canonical if not recipes.has_modifiers(raw) else recipes.display_name(raw),
        "raw": raw,
        "modifiers": modified,
        "candidates": [],
        "needs_clarification": False,
        "source": source,
        "custom": custom,
    }


@app.get("/api/dish/suggest")
def suggest_dish(q: str = "", limit: int = 8):
    return {"results": [{"name": name} for name in recipes.search_dishes(q, limit=limit)]}


@app.post("/api/dish/{session_id}")
def submit_dish(session_id: str, body: DishRequest):
    raw = body.dish.strip()
    if not raw:
        return JSONResponse(status_code=422, content={"understood": False, "message": "Please enter a dish name."})

    learned = synonyms.lookup(raw)
    if learned:
        canonical = recipes.catalog_name(learned)
        if canonical:
            return _dish_response(raw, canonical, source="synonym")

    if body.custom:
        canonical = recipes.catalog_name(raw)
        if not canonical:
            return JSONResponse(status_code=422, content={"understood": False, "message": UNKNOWN_DISH_MESSAGE})
        return _dish_response(raw, canonical, source="catalog", custom=True)

    parsed = parse_input(raw)
    if not parsed.dish:
        return JSONResponse(
            status_code=422,
            content={"understood": False, "message": "I couldn't understand that dish. Try something like 'Dal Makhani'."},
        )

    canonical = recipes.catalog_name(parsed.canonical_dish or parsed.dish or raw)
    seen = {(parsed.canonical_dish or parsed.dish or raw).lower()}
    candidates = []
    for candidate in parsed.candidates:
        name = (candidate.name or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        candidates.append(
            {
                "name": name,
                "description": candidate.description,
                "confidence": candidate.confidence,
            }
        )

    if not canonical and not candidates:
        return JSONResponse(status_code=422, content={"understood": False, "message": UNKNOWN_DISH_MESSAGE})

    dish = canonical or (parsed.canonical_dish or parsed.dish or raw).strip()
    return {
        "understood": True,
        "dish": dish,
        "display": dish if not recipes.has_modifiers(raw) else recipes.display_name(raw),
        "raw": raw,
        "modifiers": recipes.has_modifiers(raw),
        "candidates": candidates,
        "needs_clarification": bool(candidates),
        "source": parsed.source,
        "custom": False,
    }


@app.get("/api/dish/photo")
def dish_photo(dish: str = "", canonical: str = ""):
    name = (canonical or dish).strip()
    if not name:
        raise HTTPException(status_code=422, detail="dish is required")
    photo = photos.find_photo(name)
    photo.setdefault("dish", name)
    return photo


@app.post("/api/synonyms")
def learn_synonym(body: SynonymRequest):
    if not synonyms.learn(body.term, body.canonical):
        raise HTTPException(status_code=422, detail="term and canonical are required")
    return {"ok": True, "term": body.term.strip(), "canonical": body.canonical.strip()}


def _feedback_meta() -> dict:
    return {
        "llm_enabled": config.LLM_ENABLED,
        "model": config.GROQ_MODEL if config.LLM_ENABLED else None,
        "reasoning_effort": config.GROQ_REASONING_EFFORT if config.LLM_ENABLED else None,
        "photo_enabled": config.PHOTO_ENABLED,
    }


@app.post("/api/feedback/{session_id}")
def submit_feedback(session_id: str, body: FeedbackRequest):
    event: dict = {
        "kind": body.kind,
        "session_id": session_id,
        "app": _feedback_meta(),
    }

    if body.kind == "dish_rejected":
        raw = (body.raw or "").strip()
        if not raw:
            raise HTTPException(status_code=422, detail="raw dish is required")
        event.update(
            {
                "needs_review": True,
                "dish": {
                    "raw": raw,
                    "suggested_dish": body.dish,
                    "display": body.display,
                    "candidates": body.candidates[:3],
                    "needs_clarification": body.needs_clarification,
                    "modifiers": body.modifiers,
                    "source": body.source,
                },
            }
        )
    elif body.kind == "dish_correction":
        if not (body.parent_id or "").strip() or not (body.accepted_dish or "").strip():
            raise HTTPException(status_code=422, detail="parent_id and accepted_dish are required")
        event.update(
            {
                "needs_review": True,
                "correction": {
                    "parent_id": body.parent_id,
                    "rejected_raw": body.raw,
                    "rejected_dish": body.dish,
                    "accepted_raw": body.accepted_raw,
                    "accepted_dish": body.accepted_dish,
                    "accepted_display": body.accepted_display or body.accepted_dish,
                },
            }
        )
    else:
        snap = _snapshot(session_id)
        values = snap.values or {}
        recipe = _recipe_view(values)
        cart = _cart_view(session_id)
        if not recipe.get("ingredients") or not cart.get("items"):
            return {"ok": True, "stored": False, "reason": "no review snapshot available"}
        event.update(
            {
                "needs_review": body.kind == "review_disliked",
                "dish": {
                    "raw": body.raw,
                    "dish": values.get("dish"),
                    "display": body.display or values.get("dish"),
                    "servings": values.get("servings"),
                },
                "recipe": recipe,
                "cart": cart,
            }
        )

    return feedback.capture(event)


def _reset_if_paused(session_id: str) -> None:
    if _snapshot(session_id).next:
        graph.invoke(Command(resume={"action": "cancel"}), _run_config(session_id, "reset"))


@app.post("/api/servings/{session_id}")
def submit_servings(session_id: str, body: ServingsRequest):
    raw_dish = body.dish.strip()
    if not raw_dish:
        return JSONResponse(status_code=422, content={"message": "Please choose a dish first."})
    learned = synonyms.lookup(raw_dish) or raw_dish
    dish = recipes.catalog_name(learned)
    if not dish:
        return JSONResponse(
            status_code=422,
            content={"message": UNKNOWN_DISH_MESSAGE, "stage": "await_dish"},
        )
    _reset_if_paused(session_id)
    message = f"I want to cook {dish} for {body.servings} people"
    result = graph.invoke(
        {
            "session_id": session_id,
            "dish": dish,
            "servings": body.servings,
            "preparsed": True,
            "messages": [HumanMessage(content=message)],
        },
        _run_config(session_id, "wizard.servings", dish=dish, servings=body.servings),
    )
    if result.get("stage") != "cart_review":
        return JSONResponse(
            status_code=422,
            content={
                "message": result.get("error") or "I couldn't find a recipe for that dish. Please try another one.",
                "stage": result.get("stage"),
            },
        )
    snap = _snapshot(session_id)
    return {
        "recipe": _recipe_view(result),
        "cart": _cart_view(session_id),
        "paused": bool(snap.next),
        "stage": result.get("stage"),
    }


@app.get("/api/cart/{session_id}")
def get_cart(session_id: str):
    return _cart_view(session_id)


@app.post("/api/cart/{session_id}/items")
def add_cart_item(session_id: str, body: CartAddRequest):
    try:
        cart_service.add_product(session_id, body.product_id, body.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return get_cart(session_id)


@app.patch("/api/cart/{session_id}/items/{product_id}")
def update_cart_item(session_id: str, product_id: str, body: CartUpdateRequest):
    cart_service.update_quantity(session_id, product_id, body.quantity)
    return get_cart(session_id)


@app.delete("/api/cart/{session_id}/items/{product_id}")
def delete_cart_item(session_id: str, product_id: str):
    cart_service.remove_product(session_id, product_id)
    return get_cart(session_id)


@app.post("/api/cart/{session_id}/confirm")
def confirm_order(session_id: str, body: ConfirmRequest):
    snap = _snapshot(session_id)
    if not snap.next:
        raise HTTPException(status_code=400, detail="No pending order to confirm.")
    result = graph.invoke(Command(resume={"action": "confirm", "address": body.address}), _run_config(session_id, "wizard.confirm", address=body.address))
    order = cart_service.session_orders(session_id)
    return {
        "reply": result.get("reply", ""),
        "stage": result.get("stage"),
        "order": result.get("order"),
        "orders": [o.model_dump() for o in order],
    }


@app.post("/api/order/{session_id}/pay")
def pay_order(session_id: str, body: PayRequest):
    snap = _snapshot(session_id)
    if not snap.next:
        raise HTTPException(status_code=400, detail="No pending order to pay for.")
    result = graph.invoke(
        Command(resume={"action": "confirm", "method": body.method, "address": body.address}),
        _run_config(session_id, "wizard.pay", method=body.method, address=body.address),
    )
    return {
        "reply": result.get("reply", ""),
        "stage": result.get("stage"),
        "order": result.get("order"),
        "method": body.method,
    }


@app.post("/api/cart/{session_id}/cancel")
def cancel_order(session_id: str):
    snap = _snapshot(session_id)
    if not snap.next:
        raise HTTPException(status_code=400, detail="No pending order to cancel.")
    result = graph.invoke(Command(resume={"action": "cancel"}), _run_config(session_id, "wizard.cancel"))
    return {"reply": result.get("reply", ""), "stage": result.get("stage")}


@app.get("/api/orders/{session_id}")
def get_orders(session_id: str):
    return {"orders": [o.model_dump() for o in cart_service.session_orders(session_id)]}


@app.get("/api/catalog/search")
def search_catalog(q: str = "", limit: int = 8):
    catalog = get_catalog()
    products = catalog.search(q, limit=limit) if q else catalog.all()[:limit]
    return {
        "results": [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "price": min(pk.price for pk in p.packs),
                "pack": f"{pk.size:g}{pk.unit}",
            }
            for p in products
            for pk in [min(p.packs, key=lambda x: x.price)]
        ]
    }
