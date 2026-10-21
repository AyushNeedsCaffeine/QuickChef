"""Review captured feedback and promote selected events into curated golden cases.

Examples:
    python -m evals.promote_feedback --summary
    python -m evals.promote_feedback --list
    python -m evals.promote_feedback --id fb_abc123 --expect-display "Chole Kulche" --append
    python -m evals.promote_feedback --id fb_def456 --suite recipe \
        --expect-json '{"must_include": [["rajma", "kidney"]], "min_steps": 3}' --append
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.golden import GOLDEN_DIR, SUITES, load_cases, load_manifest
from evals.golden_feedback import FeedbackEvent, load_feedback, summarize


def _build_case(event: FeedbackEvent, args: argparse.Namespace) -> dict:
    if event.kind in ("dish_rejected", "dish_correction"):
        if not args.expect_display:
            raise SystemExit("--expect-display is required for dish feedback")
        suite = "dish"
        input_data = {"dish": event.raw_dish}
        expect = {"display": args.expect_display}
        mode = "live"
    else:
        if not args.suite or not args.expect_json:
            raise SystemExit("--suite and --expect-json are required for review feedback")
        try:
            expect = json.loads(args.expect_json)
        except ValueError as exc:
            raise SystemExit(f"invalid --expect-json: {exc}") from exc
        if not isinstance(expect, dict):
            raise SystemExit("--expect-json must be a JSON object")
        dish = event.data.get("dish") or {}
        suite = args.suite
        input_data = {
            "dish": dish.get("dish") or event.raw_dish,
            "servings": dish.get("servings") or 4,
        }
        mode = args.mode

    case_id = args.case_id or f"promoted-{event.kind}-{event.id}"
    return {
        "id": case_id,
        "suite": suite,
        "mode": mode,
        "input": input_data,
        "expect": expect,
        "tags": ["promoted", "from-feedback", event.kind],
        "notes": f"Promoted from feedback {event.id} captured at {event.captured_at}.",
    }


def _append_case(case: dict) -> Path:
    path = GOLDEN_DIR / "cases.jsonl"
    existing = path.read_text(encoding="utf-8").rstrip("\n")
    line = json.dumps(case, ensure_ascii=False)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text((existing + "\n" if existing else "") + line + "\n", encoding="utf-8")
    load_cases(tmp)
    tmp.replace(path)
    _update_manifest()
    return path


def _update_manifest() -> None:
    cases = load_cases()
    manifest = load_manifest()
    manifest["counts"] = {
        "total": len(cases),
        "by_mode": {
            "offline": len([case for case in cases if case.mode == "offline"]),
            "live": len([case for case in cases if case.mode == "live"]),
        },
        "by_suite": {
            suite: len([case for case in cases if case.suite == suite]) for suite in SUITES
        },
    }
    (GOLDEN_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote feedback into golden cases")
    parser.add_argument("--file", type=Path, help="feedback JSONL path")
    parser.add_argument("--summary", action="store_true", help="show queue counts")
    parser.add_argument("--list", action="store_true", help="list captured events")
    parser.add_argument("--id", help="feedback event id to promote")
    parser.add_argument("--expect-display", help="expected display name for a dish case")
    parser.add_argument("--expect-json", help="expect object for a recipe/flow case")
    parser.add_argument("--suite", choices=("dish", "recipe", "cart", "flow", "photo", "edge"))
    parser.add_argument("--mode", choices=("offline", "live"), default="live")
    parser.add_argument("--case-id", help="override the generated golden case id")
    parser.add_argument("--append", action="store_true", help="append to evals/golden/cases.jsonl")
    parser.add_argument("--out", type=Path, help="write the promoted case JSON to a file")
    args = parser.parse_args(argv)

    events = load_feedback(args.file)
    if args.summary:
        print(json.dumps(summarize(events), indent=2))
        return 0
    if args.list or not args.id:
        for event in events:
            summary = event.summary()
            print(
                f"{summary['id']:18} {summary['kind']:16} {summary['status']:16} "
                f"{summary['raw']!r} -> rejected={summary['rejected']!r} "
                f"accepted={summary['accepted']!r}"
            )
        print(f"\n{len(events)} event(s) | {sum(1 for e in events if e.review_pending)} pending review")
        return 0

    event = next((item for item in events if item.id == args.id), None)
    if event is None:
        raise SystemExit(f"feedback event {args.id!r} not found")

    case = _build_case(event, args)
    existing_ids = {item.id for item in load_cases()}
    if case["id"] in existing_ids:
        raise SystemExit(f"golden case {case['id']!r} already exists")

    line = json.dumps(case, ensure_ascii=False)
    if args.append:
        path = _append_case(case)
        print(f"appended {case['id']} to {path}")
    elif args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(line + "\n", encoding="utf-8")
        print(f"wrote {case['id']} to {args.out}")
    else:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
