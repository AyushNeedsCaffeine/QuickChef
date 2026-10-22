"""Global daily budget for logical LLM requests.

The demo deployment has no accounts, so the safest quota is deployment-wide.
One logical ``_structured()`` call consumes one request; provider retries within
that call do not consume extra units. Catalogue-only requests never call this
module. Recipe resolution checks availability before caching an offline fallback,
and custom/modified requests use it to avoid silently serving an unmodified recipe.

The counter is intentionally file-backed for single-process deployments; a
multi-worker or multi-instance deployment would need a shared store instead.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app import config

logger = logging.getLogger(__name__)

LIMIT = config.LLM_DAILY_LIMIT
TIMEZONE = config.LLM_QUOTA_TIMEZONE
QUOTA_PATH = config.LLM_QUOTA_PATH

_lock = threading.Lock()


def _zone() -> ZoneInfo:
    try:
        return ZoneInfo(TIMEZONE)
    except Exception:  # noqa: BLE001 - missing tzdata should not break the app
        logger.warning("Unknown quota timezone %r; falling back to UTC", TIMEZONE)
        return ZoneInfo("UTC")


def _today() -> str:
    return datetime.now(_zone()).date().isoformat()


def _load() -> dict:
    try:
        data = json.loads(QUOTA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUOTA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(QUOTA_PATH)


def _count_for_today(data: dict) -> int:
    if data.get("date") != _today():
        return 0
    try:
        return max(0, int(data.get("count") or 0))
    except (TypeError, ValueError):
        return 0


def available() -> bool:
    """True when another logical LLM request may be made."""
    if LIMIT <= 0:
        return True
    with _lock:
        return _count_for_today(_load()) < LIMIT


def remaining() -> int | None:
    """Remaining requests today, or ``None`` when the quota is disabled."""
    if LIMIT <= 0:
        return None
    with _lock:
        return max(0, LIMIT - _count_for_today(_load()))


def consume() -> bool:
    """Atomically reserve one request, returning False when exhausted."""
    if LIMIT <= 0:
        return True
    today = _today()
    with _lock:
        data = _load()
        count = _count_for_today(data)
        if count >= LIMIT:
            return False
        _save({"date": today, "count": count + 1})
        return True


def reset() -> None:
    """Reset today's counter (tests and per-case golden isolation)."""
    with _lock:
        _save({"date": _today(), "count": 0})
