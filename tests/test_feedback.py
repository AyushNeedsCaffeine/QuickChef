import pytest
from fastapi.testclient import TestClient

from app.agent import graph as graph_mod
from app.main import app
from app.services import feedback, synonyms


@pytest.fixture(autouse=True)
def isolated_feedback(monkeypatch, tmp_path):
    monkeypatch.setattr(feedback, "FEEDBACK_PATH", tmp_path / "feedback.jsonl")
    monkeypatch.setattr(feedback, "FEEDBACK_ENABLED", True)
    monkeypatch.setattr(synonyms, "STORE_PATH", tmp_path / "synonyms.json")
    monkeypatch.setattr(graph_mod, "get_llm", lambda: None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def session(client):
    return client.post("/api/session").json()["session_id"]


def read_events():
    return feedback.load_events()


def test_dish_rejection_is_captured(client, session):
    dish = client.post(f"/api/dish/{session}", json={"dish": "dal makhni"}).json()
    assert dish["source"] == "heuristic"

    response = client.post(
        f"/api/feedback/{session}",
        json={
            "kind": "dish_rejected",
            "raw": dish["raw"],
            "dish": dish["dish"],
            "display": dish["display"],
            "candidates": dish["candidates"],
            "needs_clarification": dish["needs_clarification"],
            "modifiers": dish["modifiers"],
            "source": dish["source"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stored"] is True

    events = read_events()
    assert len(events) == 1
    event = events[0]
    assert event["kind"] == "dish_rejected"
    assert event["needs_review"] is True
    assert event["status"] == "pending_review"
    assert event["dish"]["raw"] == "dal makhni"
    assert event["dish"]["suggested_dish"] == "Dal Makhani"
    assert event["dish"]["display"] == "Dal Makhani"
    assert event["dish"]["source"] == "heuristic"
    assert body["id"] == event["id"]


def test_correction_links_to_rejection(client, session):
    rejected = client.post(
        f"/api/feedback/{session}",
        json={"kind": "dish_rejected", "raw": "Matar Kulcha", "dish": "Matar Kulcha", "source": "llm"},
    ).json()
    assert rejected["stored"] is True

    response = client.post(
        f"/api/feedback/{session}",
        json={
            "kind": "dish_correction",
            "parent_id": rejected["id"],
            "raw": "Matar Kulcha",
            "dish": "Matar Kulcha",
            "accepted_raw": "Matar Kulcha",
            "accepted_dish": "Chole Kulche",
            "accepted_display": "Chole Kulche",
        },
    )
    assert response.status_code == 200
    assert response.json()["stored"] is True

    events = read_events()
    assert len(events) == 2
    assert events[1]["kind"] == "dish_correction"
    assert events[1]["correction"]["parent_id"] == rejected["id"]
    assert events[1]["correction"]["accepted_dish"] == "Chole Kulche"


def test_review_like_and_dislike_capture_snapshots(client, session):
    built = client.post(
        f"/api/servings/{session}",
        json={"dish": "dal makhni", "servings": 4},
    )
    assert built.status_code == 200

    liked = client.post(
        f"/api/feedback/{session}",
        json={"kind": "review_liked", "raw": "dal makhni", "dish": "Dal Makhani", "display": "Dal Makhani"},
    )
    assert liked.status_code == 200
    assert liked.json()["stored"] is True

    disliked = client.post(
        f"/api/feedback/{session}",
        json={"kind": "review_disliked", "raw": "dal makhni", "dish": "Dal Makhani", "display": "Dal Makhani"},
    )
    assert disliked.status_code == 200
    assert disliked.json()["stored"] is True

    events = read_events()
    assert [e["kind"] for e in events] == ["review_liked", "review_disliked"]
    assert events[0]["needs_review"] is False
    assert events[0]["status"] == "recorded"
    assert events[1]["needs_review"] is True
    assert events[1]["status"] == "pending_review"
    for event in events:
        assert event["recipe"]["ingredients"]
        assert event["recipe"]["steps"]
        assert event["cart"]["items"]
        assert event["cart"]["totals"]["total"] > 0
        assert event["dish"]["dish"] == "Dal Makhani"


def test_review_feedback_without_snapshot_is_not_stored(client):
    session = client.post("/api/session").json()["session_id"]
    response = client.post(
        f"/api/feedback/{session}",
        json={"kind": "review_liked", "raw": "dal makhni", "dish": "Dal Makhani"},
    )
    assert response.status_code == 200
    assert response.json()["stored"] is False
    assert read_events() == []


def test_feedback_validation(client, session):
    assert client.post(f"/api/feedback/{session}", json={"kind": "dish_rejected"}).status_code == 422
    assert (
        client.post(
            f"/api/feedback/{session}",
            json={"kind": "dish_correction", "accepted_dish": "Chole Kulche"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/feedback/{session}",
            json={"kind": "dish_correction", "parent_id": "fb_x", "accepted_dish": "Chole Kulche"},
        ).status_code
        == 200
    )
    assert client.post(f"/api/feedback/{session}", json={"kind": "unknown"}).status_code == 422


def test_feedback_disabled(monkeypatch, client, session):
    monkeypatch.setattr(feedback, "FEEDBACK_ENABLED", False)
    response = client.post(
        f"/api/feedback/{session}",
        json={"kind": "dish_rejected", "raw": "Matar Kulcha", "dish": "Matar Kulcha"},
    )
    assert response.status_code == 200
    assert response.json()["stored"] is False
    assert response.json()["reason"] == "feedback disabled"
    assert read_events() == []


def test_feedback_write_failure_is_best_effort(monkeypatch, tmp_path, client, session):
    monkeypatch.setattr(feedback, "FEEDBACK_PATH", tmp_path)
    response = client.post(
        f"/api/feedback/{session}",
        json={"kind": "dish_rejected", "raw": "Matar Kulcha", "dish": "Matar Kulcha"},
    )
    assert response.status_code == 200
    assert response.json()["stored"] is False
    assert response.json()["reason"] == "write failed"


def test_feedback_text_is_capped_and_contains_no_secrets(client, session):
    response = client.post(
        f"/api/feedback/{session}",
        json={"kind": "dish_rejected", "raw": "x" * 1000, "dish": "Matar Kulcha", "source": "llm"},
    )
    assert response.status_code == 200
    event = read_events()[0]
    assert len(event["dish"]["raw"]) == feedback.MAX_TEXT
    text = str(event)
    assert "GROQ_API_KEY" not in text
    assert "api_key" not in text.lower()


def test_frontend_feedback_hooks(client):
    html = client.get("/").text
    assert 'id="review-feedback"' in html
    assert 'id="review-like"' in html
    assert 'id="review-dislike"' in html
    script = client.get("/static/script.js").text
    assert "captureFeedback" in script
    assert "dish_rejected" in script
    assert "review_disliked" in script
