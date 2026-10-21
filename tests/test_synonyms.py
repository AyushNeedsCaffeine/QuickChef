from app.services import synonyms


def test_learn_and_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(synonyms, "STORE_PATH", tmp_path / "data" / "synonyms.json")
    assert synonyms.lookup("Matar Kulcha") is None
    assert synonyms.learn("Matar Kulcha", "Chole Kulche") is True
    assert synonyms.lookup("matar   kulcha") == "Chole Kulche"
    assert synonyms.all_learned() == {"matar kulcha": "Chole Kulche"}


def test_learn_rejects_empty_values(tmp_path, monkeypatch):
    monkeypatch.setattr(synonyms, "STORE_PATH", tmp_path / "synonyms.json")
    assert synonyms.learn("", "Chole Kulche") is False
    assert synonyms.learn("Matar Kulcha", "   ") is False
    assert synonyms.all_learned() == {}


def test_corrupt_store_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "synonyms.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(synonyms, "STORE_PATH", path)
    assert synonyms.lookup("matar kulcha") is None
    assert synonyms.learn("matar kulcha", "Chole Kulche") is True
    assert synonyms.lookup("matar kulcha") == "Chole Kulche"
