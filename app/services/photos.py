from __future__ import annotations

import html
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from app import config
from app.agent import recipes
from app.services.catalog import _norm

PHOTO_DIR = config.BASE_DIR / "static" / "dish_photos"
CACHE_PATH = config.BASE_DIR / "data" / "photo_cache.json"
USER_AGENT = config.PHOTO_USER_AGENT
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8,application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://commons.wikimedia.org/",
}
ALLOWED_HOSTS = {"upload.wikimedia.org", "thumb.wikimedia.org", "commons.wikimedia.org"}
MIME_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
BAD_WORDS = {
    "logo",
    "map",
    "menu",
    "sign",
    "shop",
    "packet",
    "label",
    "diagram",
    "drawing",
    "illustration",
    "poster",
    "advertisement",
    "advert",
    "carved",
    "carving",
    "jack",
    "lantern",
    "halloween",
    "sculpture",
    "statue",
    "portrait",
    "selfie",
    "costume",
    "decorative",
    "decoration",
    "museum",
}
OPTIONAL_TAILS = {"sabzi", "curry", "masala", "fry", "bhaji"}
MIN_PHOTO_SCORE = 12.0
MIN_PHOTO_WIDTH = 480
MIN_PHOTO_HEIGHT = 320
MIN_PHOTO_RATIO = 0.6
MAX_PHOTO_RATIO = 2.2
CACHE_VERSION = 2
_lock = threading.Lock()


def _load_cache() -> dict[str, dict]:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(data: dict[str, dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(CACHE_PATH)


def _clean(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _slug(dish: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _norm(dish)).strip("-")
    return slug[:80] or "dish"


def _http_json(url: str, params: dict) -> dict:
    with httpx.Client(
        timeout=config.PHOTO_TIMEOUT,
        follow_redirects=True,
        headers=HEADERS,
    ) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def _photo_quality_ok(width: int, height: int) -> bool:
    if width < MIN_PHOTO_WIDTH or height < MIN_PHOTO_HEIGHT:
        return False
    ratio = width / height if height else 0
    return MIN_PHOTO_RATIO <= ratio <= MAX_PHOTO_RATIO


def _score_title(title: str, dish: str) -> float:
    original = re.sub(r"^file:", "", title.strip(), flags=re.IGNORECASE)
    stem = re.sub(r"\.[a-z0-9]{2,5}$", "", original, flags=re.IGNORECASE)
    title_tokens = recipes._tokens(stem)
    dish_tokens = recipes._tokens(dish)
    if not dish_tokens:
        return 0.0
    if any(word in title_tokens for word in BAD_WORDS):
        return 0.0

    core_tokens = dish_tokens - OPTIONAL_TAILS
    if not core_tokens:
        core_tokens = dish_tokens
    shared = core_tokens & title_tokens
    if len(shared) != len(core_tokens):
        return 0.0

    missing = dish_tokens - title_tokens
    if missing - OPTIONAL_TAILS:
        return 0.0

    coverage = len(dish_tokens & title_tokens) / len(dish_tokens)
    score = len(shared) / len(core_tokens) * 10 + len(shared)
    if coverage == 1.0:
        score += 3
    if original.lower().endswith((".jpg", ".jpeg")):
        score += 1
    return score


def _commons_candidate(dish: str) -> dict | None:
    try:
        data = _http_json(
            "https://commons.wikimedia.org/w/api.php",
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": dish,
                "gsrnamespace": 6,
                "gsrlimit": 10,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size|mime",
                "iiurlwidth": 640,
                "format": "json",
            },
        )
    except Exception:
        return None

    best: tuple[float, dict] | None = None
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime") or ""
        if mime not in MIME_EXT:
            continue
        size = int(info.get("size") or 0)
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if not _photo_quality_ok(width, height):
            continue
        image_url = info.get("url")
        if size > 3_000_000 and info.get("thumburl"):
            image_url = info["thumburl"]
        if not image_url:
            continue
        score = _score_title(page.get("title", ""), dish)
        if score < MIN_PHOTO_SCORE:
            continue
        meta = info.get("extmetadata") or {}
        candidate = {
            "url": image_url,
            "title": re.sub(r"^file:", "", page.get("title", ""), flags=re.IGNORECASE),
            "source": "Wikimedia Commons",
            "source_url": "https://commons.wikimedia.org/wiki/"
            + quote(page.get("title", "").replace(" ", "_")),
            "artist": _clean((meta.get("Artist") or {}).get("value"))
            or _clean((meta.get("Credit") or {}).get("value"))
            or "Wikimedia Commons",
            "license": _clean((meta.get("LicenseShortName") or {}).get("value")),
            "score": round(score, 2),
            "width": width,
            "height": height,
        }
        if best is None or candidate["score"] > best[0]:
            best = (candidate["score"], candidate)
    return best[1] if best else None


def _wikipedia_candidate(dish: str) -> dict | None:
    try:
        data = _http_json(
            "https://en.wikipedia.org/w/api.php",
            {
                "action": "query",
                "prop": "pageimages",
                "piprop": "thumbnail",
                "pithumbsize": 640,
                "redirects": 1,
                "format": "json",
                "titles": dish,
            },
        )
    except Exception:
        return None

    for page in ((data.get("query") or {}).get("pages") or {}).values():
        thumb = (page.get("thumbnail") or {}).get("source")
        if not thumb:
            continue
        score = _score_title(str(page.get("title") or dish), dish)
        if score < MIN_PHOTO_SCORE:
            continue
        return {
            "url": thumb,
            "title": page.get("title", dish),
            "source": "Wikipedia / Wikimedia Commons",
            "source_url": "https://en.wikipedia.org/wiki/" + quote(page.get("title", dish).replace(" ", "_")),
            "artist": "Wikimedia Commons contributors",
            "license": "",
            "score": round(score, 2),
            "width": 0,
            "height": 0,
        }
    return None


def _allowed(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


def _download(url: str, slug: str) -> Path | None:
    if not _allowed(url):
        return None

    response = None
    for attempt in range(2):
        try:
            with httpx.Client(
                timeout=config.PHOTO_TIMEOUT,
                follow_redirects=True,
                headers=HEADERS,
            ) as client:
                response = client.get(url)
            if response.status_code in (403, 429) and attempt == 0:
                time.sleep(2)
                continue
            response.raise_for_status()
            break
        except Exception:
            if attempt == 0:
                time.sleep(1)
                continue
            return None

    if response is None:
        return None
    mime = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    extension = MIME_EXT.get(mime)
    if not extension or len(response.content) > 4_000_000:
        return None

    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    path = PHOTO_DIR / f"{slug}{extension}"
    path.write_bytes(response.content)
    return path


def _touch_cache(key: str, entry: dict) -> dict:
    updated = {**entry, "fetched_at": int(time.time())}
    with _lock:
        cache = _load_cache()
        cache[key] = updated
        _save_cache(cache)
    return updated


def _none(reason: str = "no confident photo") -> dict:
    return {
        "url": None,
        "kind": "none",
        "source": None,
        "source_url": None,
        "artist": None,
        "license": None,
        "reason": reason,
        "version": CACHE_VERSION,
        "fetched_at": int(time.time()),
    }


def find_photo(dish: str) -> dict:
    """Find a confident dish photo, caching it locally when possible.

    Returns ``kind="photo"`` with a local URL, or ``kind="none"`` when no image
    passes the relevance threshold. A wrong photo is worse than no photo.
    """
    if not config.PHOTO_ENABLED:
        return _none("photos disabled")

    base, _ = recipes.split_modifiers(dish)
    # Use the dish catalogue's canonical name for photo search: "maggi" becomes
    # "Maggi Noodles" and "pumpkin" becomes "Pumpkin Sabzi", which keeps the
    # lexical title search from returning people or decorations with the same word.
    canonical = recipes.display_name(base) if base else ""
    photo_dish = canonical or base or dish
    key = _norm(photo_dish) or _norm(dish)
    if not key:
        return _none("empty dish")

    with _lock:
        cache = _load_cache()
    entry = cache.get(key)
    if entry and entry.get("version") != CACHE_VERSION:
        entry = None
    stale_photo: dict | None = None
    if entry:
        age = time.time() - int(entry.get("fetched_at", 0))
        if entry.get("kind") == "photo" and entry.get("url"):
            path = PHOTO_DIR / Path(entry["url"]).name
            if path.exists():
                if age < config.PHOTO_CACHE_TTL:
                    return entry
                stale_photo = entry
        elif entry.get("kind") == "none":
            if age < config.PHOTO_FAILURE_TTL:
                return entry

    candidate = _commons_candidate(photo_dish) or _wikipedia_candidate(photo_dish)
    if not candidate:
        if stale_photo:
            return _touch_cache(key, stale_photo)
        result = _none()
        with _lock:
            cache = _load_cache()
            cache[key] = result
            _save_cache(cache)
        return result

    path = _download(candidate["url"], _slug(photo_dish))
    if not path:
        if stale_photo:
            return _touch_cache(key, stale_photo)
        result = _none("download failed")
        with _lock:
            cache = _load_cache()
            cache[key] = result
            _save_cache(cache)
        return result

    result = {
        "url": f"/static/dish_photos/{path.name}",
        "kind": "photo",
        "source": candidate["source"],
        "source_url": candidate["source_url"],
        "artist": candidate["artist"],
        "license": candidate["license"],
        "title": candidate.get("title"),
        "score": candidate.get("score"),
        "width": candidate.get("width"),
        "height": candidate.get("height"),
        "version": CACHE_VERSION,
        "fetched_at": int(time.time()),
    }
    with _lock:
        cache = _load_cache()
        cache[key] = result
        _prune(cache)
        _save_cache(cache)
    return result


def _prune(cache: dict[str, dict]) -> None:
    if len(cache) <= 300:
        return
    ordered = sorted(cache.items(), key=lambda item: int(item[1].get("fetched_at", 0)))
    for key, entry in ordered[:50]:
        cache.pop(key, None)
        url = entry.get("url")
        if url:
            try:
                (PHOTO_DIR / Path(url).name).unlink(missing_ok=True)
            except OSError:
                pass
