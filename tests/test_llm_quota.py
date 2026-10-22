import json

from app.agent import graph
from app.services import llm_quota


def test_quota_limit_persists_and_reports_remaining(monkeypatch, tmp_path):
    path = tmp_path / "quota.json"
    monkeypatch.setattr(llm_quota, "QUOTA_PATH", path)
    monkeypatch.setattr(llm_quota, "LIMIT", 2)
    llm_quota.reset()

    assert llm_quota.remaining() == 2
    assert llm_quota.consume() is True
    assert llm_quota.consume() is True
    assert llm_quota.consume() is False
    assert llm_quota.remaining() == 0
    assert json.loads(path.read_text())["count"] == 2


def test_quota_rolls_over_on_a_new_day(monkeypatch, tmp_path):
    day = {"value": "2026-10-21"}
    monkeypatch.setattr(llm_quota, "QUOTA_PATH", tmp_path / "quota.json")
    monkeypatch.setattr(llm_quota, "LIMIT", 1)
    monkeypatch.setattr(llm_quota, "_today", lambda: day["value"])
    llm_quota.reset()

    assert llm_quota.consume() is True
    assert llm_quota.consume() is False
    day["value"] = "2026-10-22"
    assert llm_quota.consume() is True


def test_corrupt_quota_file_starts_fresh(monkeypatch, tmp_path):
    path = tmp_path / "quota.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(llm_quota, "QUOTA_PATH", path)
    monkeypatch.setattr(llm_quota, "LIMIT", 1)

    assert llm_quota.consume() is True
    assert llm_quota.consume() is False


def test_zero_limit_disables_quota(monkeypatch):
    monkeypatch.setattr(llm_quota, "LIMIT", 0)

    assert llm_quota.available() is True
    assert llm_quota.consume() is True
    assert llm_quota.remaining() is None


def test_structured_does_not_call_llm_when_quota_is_exhausted(monkeypatch, tmp_path):
    class Parser:
        def __init__(self):
            self.calls = 0

        def invoke(self, _messages):
            self.calls += 1
            return graph.ParsedInput(dish="Dal Makhani", canonical_dish="Dal Makhani")

    class FakeLLM:
        def __init__(self, parser):
            self.parser = parser

        def with_structured_output(self, _schema, method=None):
            return self.parser

    parser = Parser()
    monkeypatch.setattr(llm_quota, "QUOTA_PATH", tmp_path / "quota.json")
    monkeypatch.setattr(llm_quota, "LIMIT", 1)
    llm_quota.reset()
    monkeypatch.setattr(graph, "get_llm", lambda: FakeLLM(parser))

    assert graph._structured(graph.ParsedInput, [], label="test") is not None
    assert graph._structured(graph.ParsedInput, [], label="test") is None
    assert parser.calls == 1
