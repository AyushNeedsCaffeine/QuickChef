"""Best-effort capture of user feedback for later golden-dataset review.

Events are appended as JSONL so they can be inspected and promoted into the
curated golden cases without ever blocking the shopping flow.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)

FEEDBACK_PATH = config.FEEDBACK_PATH
FEEDBACK_ENABLED = config.FEEDBACK_ENABLED
MAX_TEXT = 300
MAX_EVENT_BYTES = 64_000
_lock = threading.Lock()


def _clean(value: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value))
    return text.strip()[:MAX_TEXT]


def _sanitize(value, depth: int = 0):
    if depth > 6:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, list):
        return [_sanitize(item, depth + 1) for item in value[:50]]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in list(value.items())[:50]:
            cleaned[_clean(key)[:80]] = _sanitize(item, depth + 1)
        return cleaned
    return _clean(value)


def _dump(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _fit(event: dict) -> dict:
    if len(_dump(event).encode("utf-8")) <= MAX_EVENT_BYTES:
        return event
    event = dict(event)
    event["truncated"] = True
    recipe = event.get("recipe")
    if isinstance(recipe, dict):
        recipe = dict(recipe)
        recipe["ingredients"] = list(recipe.get("ingredients") or [])[:30]
        recipe["steps"] = list(recipe.get("steps") or [])[:6]
        recipe["unmatched"] = list(recipe.get("unmatched") or [])[:20]
        event["recipe"] = recipe
    cart = event.get("cart")
    if isinstance(cart, dict):
        cart = dict(cart)
        cart["items"] = list(cart.get("items") or [])[:30]
        event["cart"] = cart
    if len(_dump(event).encode("utf-8")) <= MAX_EVENT_BYTES:
        return event
    event.pop("recipe", None)
    event["note"] = "event truncated before storage"
    return event


def _append(line: str) -> None:
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(FEEDBACK_PATH, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def capture(event: dict) -> dict:
    """Append one feedback event. Storage failures return ``stored=False``."""
    if not FEEDBACK_ENABLED:
        return {"ok": True, "stored": False, "reason": "feedback disabled"}

    payload = dict(event)
    payload.setdefault("schema_version", 1)
    payload.setdefault("id", f"fb_{uuid.uuid4().hex[:12]}")
    payload.setdefault("captured_at", datetime.now(timezone.utc).isoformat())
    payload["status"] = "pending_review" if payload.get("needs_review") else "recorded"
    payload = _sanitize(payload)
    payload = _fit(payload)
    try:
        with _lock:
            _append(_dump(payload))
    except OSError as exc:
        logger.warning("feedback write failed: %s", exc)
        return {"ok": True, "stored": False, "reason": "write failed", "id": payload["id"]}
    return {"ok": True, "stored": True, "id": payload["id"], "status": payload["status"]}


def load_events(path: Path | None = None) -> list[dict]:
    path = path or FEEDBACK_PATH
    if not path.exists():
        return []
    events = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                logger.warning("skipping malformed feedback line in %s", path)
    return events
