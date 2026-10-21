"""Replay captured dish feedback against the current resolver.

This is a lightweight regression view over the feedback queue; it does not
modify the queue or the curated golden cases.

    python -m evals.run_feedback --kind dish_rejected
    python -m evals.run_feedback --kind dish_correction --offline
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent import graph as graph_mod
from app.main import app
from evals.evaluators import norm
from evals.golden_feedback import load_feedback


def _lookup(client: TestClient, dish: str) -> dict:
    session = client.post("/api/session").json()["session_id"]
    response = client.post(f"/api/dish/{session}", json={"dish": dish})
    body = response.json()
    return {
        "status": response.status_code,
        "dish": body.get("dish"),
        "display": body.get("display"),
        "candidates": [c.get("name") for c in body.get("candidates") or [] if isinstance(c, dict)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay captured dish feedback")
    parser.add_argument("--file", type=Path, help="feedback JSONL path")
    parser.add_argument("--kind", choices=("dish_rejected", "dish_correction"), default="dish_rejected")
    parser.add_argument("--offline", action="store_true", help="disable the LLM for the replay")
    parser.add_argument("--json-out", type=Path, help="write full replay results")
    parser.add_argument("--fail-on-regression", action="store_true", help="exit 1 when a bad suggestion repeats")
    args = parser.parse_args(argv)

    if args.offline:
        graph_mod.get_llm = lambda: None

    events = [event for event in load_feedback(args.file) if event.kind == args.kind]
    if not events:
        print(f"No {args.kind} events.")
        return 0

    results = []
    regressions = 0
    with TestClient(app) as client:
        for event in events:
            dish = event.data.get("dish") or {}
            correction = event.data.get("correction") or {}
            rejected = dish.get("suggested_dish") or correction.get("rejected_dish") or ""
            accepted = correction.get("accepted_dish") or ""
            current = _lookup(client, event.raw_dish)
            if args.kind == "dish_rejected":
                bad = bool(rejected) and norm(current.get("display")) == norm(rejected)
                regressions += int(bad)
                outcome = {"same_bad_suggestion": bad}
            else:
                good = bool(accepted) and norm(current.get("display")) == norm(accepted)
                regressions += int(bool(accepted) and not good)
                outcome = {"matches_accepted": good}
            result = {
                "id": event.id,
                "raw": event.raw_dish,
                "rejected": rejected,
                "accepted": accepted,
                "current": current,
                **outcome,
            }
            results.append(result)
            print(json.dumps(result, ensure_ascii=False))

    print(f"\n{len(results)} event(s) | {regressions} regression(s)")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 1 if args.fail_on_regression and regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
