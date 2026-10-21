import json
import subprocess
import sys
from pathlib import Path

from evals import evaluators, promote_feedback
from evals.golden import GoldenCase, filter_cases, load_cases, load_manifest
from evals.golden_feedback import load_feedback, summarize

ROOT = Path(__file__).resolve().parents[1]


def test_golden_cases_load_and_are_unique():
    cases = load_cases()
    ids = [case.id for case in cases]
    assert len(cases) == len(set(ids))
    assert len(cases) >= 50
    assert {case.suite for case in cases} == {"dish", "recipe", "cart", "flow", "photo", "edge"}


def test_manifest_counts_match_cases():
    cases = load_cases()
    manifest = load_manifest()
    counts = manifest["counts"]
    assert counts["total"] == len(cases)
    assert counts["by_mode"]["offline"] == len([c for c in cases if c.mode == "offline"])
    assert counts["by_mode"]["live"] == len([c for c in cases if c.mode == "live"])
    for suite, expected in counts["by_suite"].items():
        assert expected == len([c for c in cases if c.suite == suite])


def test_offline_filter_excludes_live_cases():
    offline = filter_cases(load_cases(), live=False)
    assert offline
    assert all(not case.live for case in offline)
    assert len(offline) == load_manifest()["counts"]["by_mode"]["offline"]


def test_dish_evaluator_detects_display_and_candidate():
    case = GoldenCase(
        id="x",
        suite="dish",
        mode="live",
        input={},
        expect={"display": "Matar Kulcha", "candidates_any": ["Chole Kulche"], "needs_clarification": True},
    )
    result = evaluators.evaluate(
        case,
        {
            "display": "Matar Kulcha",
            "candidates": [{"name": "Chole Kulche"}],
            "needs_clarification": True,
        },
    )
    assert result["passed"] is True
    assert result["score"] == 1.0


def test_recipe_evaluator_honours_exclusions():
    case = GoldenCase(
        id="x",
        suite="recipe",
        mode="live",
        input={},
        expect={"must_include": [["rajma", "kidney"]], "must_exclude": [["onion"], ["garlic"]], "min_steps": 3},
    )
    good = evaluators.evaluate(
        case,
        {"recipe": {"ingredients": [{"name": "Kidney Beans"}], "steps": ["a", "b", "c"]}},
    )
    bad = evaluators.evaluate(
        case,
        {"recipe": {"ingredients": [{"name": "Kidney Beans"}, {"name": "Onion"}], "steps": ["a", "b", "c"]}},
    )
    assert good["passed"] is True
    assert bad["passed"] is False


def test_recipe_evaluator_checks_cart_contents():
    case = GoldenCase(
        id="x",
        suite="recipe",
        mode="offline",
        input={},
        expect={
            "cart_must_include": [["kala", "chana"]],
            "cart_must_exclude": [["rose water"], ["chana dal"]],
        },
    )
    good = evaluators.evaluate(
        case,
        {
            "recipe": {"ingredients": [{"name": "Kala Chana"}], "steps": ["a", "b", "c"]},
            "cart": {"items": [{"name": "Kala Chana (500g)"}]},
        },
    )
    bad = evaluators.evaluate(
        case,
        {
            "recipe": {"ingredients": [{"name": "Kala Chana"}], "steps": ["a", "b", "c"]},
            "cart": {"items": [{"name": "Rose Water"}, {"name": "Chana Dal (500g)"}]},
        },
    )
    assert good["passed"] is True
    assert bad["passed"] is False


def test_scale_evaluator():
    case = GoldenCase(
        id="x",
        suite="recipe",
        mode="offline",
        input={},
        expect={"scale": {"factor": 2, "tolerance": 0.05}},
    )
    result = evaluators.evaluate(
        case,
        {"base_quantities": {"rice": 100, "dal": 50}, "scaled_quantities": {"rice": 200, "dal": 100}},
    )
    assert result["passed"] is True


def test_offline_golden_runner_passes():
    result = subprocess.run(
        [sys.executable, "-m", "evals.run_golden", "--quiet"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failed" in result.stdout


def test_display_not_evaluator():
    ok = evaluators.score_dish({"display_not": "Matar Kulcha"}, {"display": "Chole Kulche"})
    bad = evaluators.score_dish({"display_not": "Matar Kulcha"}, {"display": "Matar Kulcha"})
    assert ok["passed"] is True
    assert bad["passed"] is False


def test_feedback_loader_and_summary(tmp_path):
    path = tmp_path / "feedback.jsonl"
    path.write_text(
        '{"schema_version":1,"id":"fb_one","kind":"dish_rejected","captured_at":"2026-10-20T00:00:00Z",'
        '"needs_review":true,"status":"pending_review","dish":{"raw":"Matar Kulcha"}}\n'
        '{"schema_version":1,"id":"fb_two","kind":"review_liked","captured_at":"2026-10-20T00:00:01Z",'
        '"needs_review":false,"status":"recorded","dish":{"raw":"Dal Makhani"}}\n',
        encoding="utf-8",
    )
    events = load_feedback(path)
    assert [event.id for event in events] == ["fb_one", "fb_two"]
    assert events[0].review_pending is True
    assert events[0].raw_dish == "Matar Kulcha"
    summary = summarize(events)
    assert summary["total"] == 2
    assert summary["pending_review"] == 1
    assert summary["by_kind"]["dish_rejected"] == 1


def test_promote_feedback_writes_dish_case(tmp_path):
    path = tmp_path / "feedback.jsonl"
    path.write_text(
        '{"schema_version":1,"id":"fb_corr","kind":"dish_correction","captured_at":"2026-10-20T00:00:00Z",'
        '"needs_review":true,"status":"pending_review","dish":{"raw":"Matar Kulcha"},'
        '"correction":{"parent_id":"fb_rej","rejected_raw":"Matar Kulcha","rejected_dish":"Matar Kulcha",'
        '"accepted_raw":"Matar Kulcha","accepted_dish":"Chole Kulche","accepted_display":"Chole Kulche"}}\n',
        encoding="utf-8",
    )
    out = tmp_path / "promoted.json"
    rc = promote_feedback.main(
        [
            "--file", str(path),
            "--id", "fb_corr",
            "--expect-display", "Chole Kulche",
            "--out", str(out),
        ]
    )
    assert rc == 0
    case = json.loads(out.read_text(encoding="utf-8"))
    assert case["suite"] == "dish"
    assert case["input"] == {"dish": "Matar Kulcha"}
    assert case["expect"] == {"display": "Chole Kulche"}
    assert "from-feedback" in case["tags"]
