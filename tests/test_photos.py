import json

from app.services import photos


def candidate(url="https://upload.wikimedia.org/example.jpg"):
    return {
        "url": url,
        "title": "Chole Kulche.jpg",
        "source": "Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Chole_Kulche.jpg",
        "artist": "Test Artist",
        "license": "CC BY-SA 4.0",
        "score": 14.0,
    }


def test_score_prefers_exact_dish_titles():
    assert photos._score_title("File:Chole Kulche.jpg", "Chole Kulche") > 0
    assert photos._score_title("File:Matar Kulcha.jpg", "Matar Kulcha") > 0
    assert photos._score_title("File:Palak Paneer.jpg", "Palak Paneer") > 0


def test_score_rejects_wrong_or_unrelated_titles():
    assert photos._score_title("File:Chole.jpg", "Chole Kulche") == 0
    assert photos._score_title("File:Restaurant menu.jpg", "Chole Kulche") == 0
    assert photos._score_title("File:Wikimedia logo.png", "Chole Kulche") == 0


def test_find_photo_downloads_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(photos, "CACHE_PATH", tmp_path / "photo_cache.json")
    monkeypatch.setattr(photos.config, "PHOTO_ENABLED", True)

    calls = {"search": 0, "download": 0}

    def fake_candidate(dish):
        calls["search"] += 1
        return candidate()

    def fake_download(url, slug):
        calls["download"] += 1
        path = photos.PHOTO_DIR / f"{slug}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return path

    monkeypatch.setattr(photos, "_commons_candidate", fake_candidate)
    monkeypatch.setattr(photos, "_download", fake_download)

    first = photos.find_photo("Chole Kulche")
    second = photos.find_photo("Chole Kulche")

    assert first["kind"] == "photo"
    assert first["url"] == "/static/dish_photos/chole-kulche.jpg"
    assert first["artist"] == "Test Artist"
    assert first["license"] == "CC BY-SA 4.0"
    assert second["url"] == first["url"]
    assert calls == {"search": 1, "download": 1}


def test_find_photo_caches_no_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(photos, "CACHE_PATH", tmp_path / "photo_cache.json")
    monkeypatch.setattr(photos.config, "PHOTO_ENABLED", True)

    calls = {"n": 0}

    def empty(dish):
        calls["n"] += 1
        return None

    monkeypatch.setattr(photos, "_commons_candidate", empty)
    monkeypatch.setattr(photos, "_wikipedia_candidate", empty)

    assert photos.find_photo("Unicorn Stew")["kind"] == "none"
    assert photos.find_photo("Unicorn Stew")["kind"] == "none"
    assert calls["n"] == 2


def _expire(path):
    data = json.loads(path.read_text())
    for entry in data.values():
        entry["fetched_at"] = 0
    path.write_text(json.dumps(data))


def test_expired_photo_refetches(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(photos, "CACHE_PATH", tmp_path / "photo_cache.json")
    monkeypatch.setattr(photos.config, "PHOTO_ENABLED", True)
    calls = {"search": 0, "download": 0}

    def fake_candidate(dish):
        calls["search"] += 1
        return candidate()

    def fake_download(url, slug):
        calls["download"] += 1
        path = photos.PHOTO_DIR / f"{slug}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return path

    monkeypatch.setattr(photos, "_commons_candidate", fake_candidate)
    monkeypatch.setattr(photos, "_download", fake_download)
    photos.find_photo("Chole Kulche")
    _expire(photos.CACHE_PATH)
    photos.find_photo("Chole Kulche")
    assert calls == {"search": 2, "download": 2}


def test_expired_photo_falls_back_to_stale_when_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(photos, "CACHE_PATH", tmp_path / "photo_cache.json")
    monkeypatch.setattr(photos.config, "PHOTO_ENABLED", True)

    def fake_candidate(dish):
        return candidate()

    def fake_download(url, slug):
        path = photos.PHOTO_DIR / f"{slug}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return path

    monkeypatch.setattr(photos, "_commons_candidate", fake_candidate)
    monkeypatch.setattr(photos, "_download", fake_download)
    first = photos.find_photo("Chole Kulche")
    _expire(photos.CACHE_PATH)

    monkeypatch.setattr(photos, "_commons_candidate", lambda dish: None)
    monkeypatch.setattr(photos, "_wikipedia_candidate", lambda dish: None)
    stale = photos.find_photo("Chole Kulche")
    assert stale["kind"] == first["kind"]
    assert stale["url"] == first["url"]
    assert stale["artist"] == first["artist"]
    assert stale["license"] == first["license"]


def test_failed_lookup_retries_after_failure_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(photos, "CACHE_PATH", tmp_path / "photo_cache.json")
    monkeypatch.setattr(photos.config, "PHOTO_ENABLED", True)
    calls = {"n": 0}

    def empty(dish):
        calls["n"] += 1
        return None

    monkeypatch.setattr(photos, "_commons_candidate", empty)
    monkeypatch.setattr(photos, "_wikipedia_candidate", empty)
    photos.find_photo("Unicorn Stew")
    _expire(photos.CACHE_PATH)
    photos.find_photo("Unicorn Stew")
    assert calls["n"] == 4


def test_score_rejects_people_and_decorations():
    assert photos._score_title("File:Maggi Hambling 2006.jpg", "Maggi Noodles") == 0
    assert photos._score_title("File:Carved pumpkin - Ludwigsburg 01.jpg", "Pumpkin Sabzi") == 0


def test_score_accepts_canonical_food_titles():
    assert photos._score_title("File:Maggi noodles.jpg", "Maggi Noodles") > 0
    assert photos._score_title("File:Pumpkin curry.jpg", "Pumpkin Sabzi") > 0
    assert photos._score_title("File:Kala chana curry.jpg", "Kala Chana") > 0


def test_find_photo_searches_with_canonical_name(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(photos, "CACHE_PATH", tmp_path / "photo_cache.json")
    monkeypatch.setattr(photos.config, "PHOTO_ENABLED", True)
    seen = []

    def fake_candidate(dish):
        seen.append(dish)
        return candidate()

    def fake_download(url, slug):
        path = photos.PHOTO_DIR / f"{slug}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return path

    monkeypatch.setattr(photos, "_commons_candidate", fake_candidate)
    monkeypatch.setattr(photos, "_download", fake_download)

    result = photos.find_photo("maggi")
    assert seen == ["Maggi Noodles"]
    assert result["kind"] == "photo"
    cache = json.loads(photos.CACHE_PATH.read_text())
    assert "maggi noodles" in cache
    assert "maggi" not in cache
