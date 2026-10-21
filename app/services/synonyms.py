from __future__ import annotations

import json
import threading
from pathlib import Path

from app import config
from app.services.catalog import _norm

STORE_PATH = config.BASE_DIR / "data" / "synonyms.json"
_lock = threading.Lock()


def _load() -> dict[str, str]:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if key and value}


def _save(data: dict[str, str]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STORE_PATH)


def lookup(term: str) -> str | None:
    """Return a learned canonical dish for a user term, if one exists."""
    key = _norm(term)
    if not key:
        return None
    with _lock:
        return _load().get(key)


def learn(term: str, canonical: str) -> bool:
    """Remember that ``term`` means ``canonical`` for this app instance."""
    key = _norm(term)
    value = (canonical or "").strip()
    if not key or not value:
        return False
    with _lock:
        data = _load()
        data[key] = value
        _save(data)
    return True


def all_learned() -> dict[str, str]:
    with _lock:
        return _load()
