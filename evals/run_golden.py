"""Run the curated QuickChef golden dataset.

Offline (default) runs only cases marked ``mode: offline`` with the LLM disabled,
so it is safe in CI. ``--live`` also runs LLM and photo cases (needs a Groq key
and network access).

Examples:
    python -m evals.run_golden
    python -m evals.run_golden --suite dish --suite recipe --json-out /tmp/golden.json
    python -m evals.run_golden --live --suite dish --id dish-colloquial-matar-kulcha
    python -m evals.run_golden --live --suite photo --write-baseline evals/baselines/photos.json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app import main as main_mod
from app.agent import graph as graph_mod
from app.models import Ingredient
from app.services import matcher, photos, synonyms
from evals.evaluators import evaluate, norm
from evals.golden import SUITES, filter_cases, load_cases, load_manifest


def _new_session(client: TestClient) -> str:
    return client.post("/api/session").json()["session_id"]


def _post_servings(client: TestClient, dish: str, servings: int) -> tuple[int, dict]:
    session = _new_session(client)
    response = client.post(f"/api/servings/{session}", json={"dish": dish, "servings": servings})
    return response.status_code, response.json()


def run_dish(client: TestClient, case) -> dict:
    session = _new_session(client)
    response = client.post(f"/api/dish/{session}", json={"dish": case.input.get("dish", "")})
    body = response.json()
    if response.status_code != 200:
        return {
            "status": response.status_code,
            "understood": False,
            "display": None,
            "candidates": [],
            "needs_clarification": False,
            "modifiers": False,
            "error": body,
        }
    return body


def _quantities(recipe: dict) -> dict[str, float]:
    quantities: dict[str, float] = {}
    for item in recipe.get("ingredients") or []:
        name = norm(item.get("name"))
        try:
            quantities[name] = float(item.get("quantity") or 0)
        except (TypeError, ValueError):
            quantities[name] = 0.0
    return quantities


def run_recipe(client: TestClient, case) -> dict:
    scale = case.expect.get("scale")
    if scale:
        base_servings = int(case.input.get("base_servings") or 4)
        _, base_body = _post_servings(client, case.input["dish"], base_servings)
        _, scaled_body = _post_servings(client, case.input["dish"], int(case.input["servings"]))
        return {
            "base_quantities": _quantities(base_body.get("recipe") or {}),
            "scaled_quantities": _quantities(scaled_body.get("recipe") or {}),
        }

    status, body = _post_servings(client, case.input.get("dish", ""), int(case.input.get("servings") or 4))
    if status != 200:
        return {"recipe": {}, "cart": {}, "error": body, "status": status}
    return body


def run_cart(case) -> dict:
    ingredients = [
        Ingredient(
            name=str(item.get("name", "")),
            quantity=float(item.get("quantity") or 1),
            unit=str(item.get("unit") or "pc"),
            category=str(item.get("category") or "other"),
        )
        for item in case.input.get("ingredients") or []
    ]
    result = matcher.match_ingredients(ingredients)
    return {
        "matched": [item.model_dump() for item in result.matched],
        "unmatched": [item.model_dump() for item in result.unmatched],
    }


def run_flow(client: TestClient, case) -> dict:
    session = _new_session(client)
    response = client.post(
        f"/api/servings/{session}",
        json={"dish": case.input.get("dish", ""), "servings": int(case.input.get("servings") or 4)},
    )
    body = response.json()
    if response.status_code != 200:
        return {
            "stage": body.get("stage"),
            "recipe_source": None,
            "cart_items": 0,
            "total": 0,
            "error": body,
            "status": response.status_code,
        }

    recipe = body.get("recipe") or {}
    cart = body.get("cart") or {}
    actual = {
        "stage": body.get("stage"),
        "recipe_source": recipe.get("source"),
        "cart_items": len(cart.get("items") or []),
        "total": (cart.get("totals") or {}).get("total"),
        "notice": recipe.get("notice"),
        "order": None,
    }
    if case.input.get("pay"):
        pay = client.post(
            f"/api/order/{session}/pay",
            json={
                "method": case.input.get("method") or "upi",
                "address": case.input.get("address") or "Home",
            },
        )
        pay_body = pay.json()
        if pay.status_code == 200:
            actual["order"] = pay_body.get("order")
        else:
            actual["error"] = pay_body
            actual["status"] = pay.status_code
    return actual


def run_photo(case) -> dict:
    return photos.find_photo(case.input.get("dish", ""))


def run_edge(client: TestClient, case) -> dict:
    endpoint = case.input.get("endpoint") or "dish"
    session = _new_session(client)
    if endpoint == "servings":
        response = client.post(
            f"/api/servings/{session}",
            json={
                "dish": case.input.get("dish", ""),
                "servings": case.input.get("servings", 4),
            },
        )
    else:
        response = client.post(f"/api/dish/{session}", json={"dish": case.input.get("dish", "")})
    body = response.json()
    return {
        "status": response.status_code,
        "understood": body.get("understood"),
        "stage": body.get("stage"),
        "error": body if response.status_code >= 400 else None,
    }


def run_case(client: TestClient, case) -> dict:
    if case.suite == "dish":
        return run_dish(client, case)
    if case.suite == "recipe":
        return run_recipe(client, case)
    if case.suite == "cart":
        return run_cart(case)
    if case.suite == "flow":
        return run_flow(client, case)
    if case.suite == "photo":
        return run_photo(case)
    if case.suite == "edge":
        return run_edge(client, case)
    return {"error": f"unknown suite {case.suite}"}


def _configure_offline() -> None:
    graph_mod.get_llm = lambda: None


def _isolate_state() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="quickchef-golden-"))
    synonyms.STORE_PATH = tmp / "synonyms.json"
    photos.CACHE_PATH = tmp / "photo_cache.json"
    photos.PHOTO_DIR = tmp / "photos"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the QuickChef golden dataset")
    parser.add_argument("--suite", action="append", choices=SUITES, help="limit to a suite (repeatable)")
    parser.add_argument("--id", action="append", dest="ids", help="limit to a case id (repeatable)")
    parser.add_argument("--live", action="store_true", help="also run LLM/photo cases")
    parser.add_argument("--limit", type=int, help="run at most N cases")
    parser.add_argument("--min-score", type=float, default=1.0, help="minimum mean score (default 1.0)")
    parser.add_argument("--json-out", type=Path, help="write full results as JSON")
    parser.add_argument("--write-baseline", type=Path, help="write results as the new baseline")
    parser.add_argument("--baseline", type=Path, help="compare against a previous results JSON")
    parser.add_argument("--list", action="store_true", help="list selected cases and exit")
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cases = filter_cases(load_cases(), suites=args.suite, ids=args.ids, live=args.live)
    if args.limit:
        cases = cases[: args.limit]

    if args.list:
        for case in cases:
            print(f"{case.id:44} {case.suite:7} {case.mode:7} {','.join(case.tags)}")
        print(f"\n{len(cases)} case(s)")
        return 0
    if not cases:
        print("No golden cases selected.")
        return 0

    original_get_llm = graph_mod.get_llm
    if not args.live:
        _configure_offline()
    _isolate_state()

    manifest = load_manifest()
    print(
        f"QuickChef golden | mode={'live' if args.live else 'offline'} | "
        f"{len(cases)} case(s) | dataset v{manifest.get('version', '?')}"
    )

    client = TestClient(main_mod.app)
    results = []
    started = time.perf_counter()
    for case in cases:
        case_started = time.perf_counter()
        if args.live:
            graph_mod.get_llm = original_get_llm if case.live else (lambda: None)
        with graph_mod._recipe_cache_lock:
            graph_mod._recipe_cache.clear()
        try:
            actual = run_case(client, case)
            outcome = evaluate(case, actual)
        except Exception as exc:  # noqa: BLE001 - a crash is a failed case
            actual = {"error": f"{type(exc).__name__}: {exc}"}
            outcome = {"score": 0.0, "passed": False, "checks": {}, "details": {}}

        elapsed = time.perf_counter() - case_started
        record = {
            "id": case.id,
            "suite": case.suite,
            "mode": case.mode,
            "score": outcome["score"],
            "passed": outcome["passed"],
            "checks": outcome["checks"],
            "details": outcome["details"],
            "seconds": round(elapsed, 2),
        }
        if not outcome["passed"]:
            record["actual"] = actual
        results.append(record)

        if not args.quiet:
            status = "PASS" if outcome["passed"] else "FAIL"
            print(f"{status}  {case.id:44} {outcome['score']:.2f}  {elapsed:5.2f}s")

    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    failed = total - passed
    mean_score = round(sum(item["score"] for item in results) / total, 4)
    elapsed_total = round(time.perf_counter() - started, 2)
    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "mean_score": mean_score,
        "min_score": min(item["score"] for item in results),
        "seconds": elapsed_total,
        "mode": "live" if args.live else "offline",
    }

    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": summary["mode"],
        "summary": summary,
        "results": results,
    }

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.write_baseline:
        args.write_baseline.parent.mkdir(parents=True, exist_ok=True)
        args.write_baseline.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(
        f"\n{passed} passed, {failed} failed | mean {mean_score:.2f} | "
        f"min {summary['min_score']:.2f} | {elapsed_total:.2f}s"
    )

    if args.baseline:
        try:
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Could not read baseline: {exc}")
            return 1
        old = {item["id"]: item for item in baseline.get("results") or []}
        regressions = [
            item["id"]
            for item in results
            if old.get(item["id"], {}).get("passed") and not item["passed"]
        ]
        if regressions:
            print(f"Regressions vs baseline: {', '.join(regressions)}")
            return 1
        print(f"Baseline OK ({len(old)} previous case(s))")

    if failed or mean_score < args.min_score:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
