"""Loader and validation for the curated QuickChef golden dataset.

The dataset is JSONL so each case stays reviewable in a diff. Cases marked
``mode: live`` need a Groq key (dish/recipe cases) or network access (photo
cases); ``mode: offline`` cases run deterministically with the LLM disabled.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
SUITES = ("dish", "recipe", "cart", "flow", "photo", "edge")
MODES = ("offline", "live")


@dataclass(frozen=True)
class GoldenCase:
    id: str
    suite: str
    mode: str
    input: dict
    expect: dict
    tags: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    @property
    def live(self) -> bool:
        return self.mode == "live"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "suite": self.suite,
            "mode": self.mode,
            "input": self.input,
            "expect": self.expect,
            "tags": list(self.tags),
            "notes": self.notes,
        }


def load_cases(path: Path | None = None) -> list[GoldenCase]:
    path = path or GOLDEN_DIR / "cases.jsonl"
    cases: list[GoldenCase] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            case = _validate(raw, path, line_no)
            if case.id in seen:
                raise ValueError(f"{path}:{line_no}: duplicate id {case.id!r}")
            seen.add(case.id)
            cases.append(case)
    return cases


def _validate(raw: dict, path: Path, line_no: int) -> GoldenCase:
    where = f"{path}:{line_no}"
    for key in ("id", "suite", "mode", "input", "expect"):
        if key not in raw:
            raise ValueError(f"{where}: missing {key!r}")
    if raw["suite"] not in SUITES:
        raise ValueError(f"{where}: unknown suite {raw['suite']!r}")
    if raw["mode"] not in MODES:
        raise ValueError(f"{where}: unknown mode {raw['mode']!r}")
    if not isinstance(raw["input"], dict) or not isinstance(raw["expect"], dict):
        raise ValueError(f"{where}: input/expect must be objects")
    tags = raw.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError(f"{where}: tags must be a list of strings")
    return GoldenCase(
        id=str(raw["id"]),
        suite=str(raw["suite"]),
        mode=str(raw["mode"]),
        input=raw["input"],
        expect=raw["expect"],
        tags=tuple(tags),
        notes=str(raw.get("notes") or ""),
    )


def load_manifest(path: Path | None = None) -> dict:
    path = path or GOLDEN_DIR / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def filter_cases(
    cases: list[GoldenCase],
    suites: list[str] | None = None,
    ids: list[str] | None = None,
    live: bool = False,
) -> list[GoldenCase]:
    if suites:
        cases = [case for case in cases if case.suite in suites]
    if ids:
        wanted = set(ids)
        cases = [case for case in cases if case.id in wanted]
    if not live:
        cases = [case for case in cases if not case.live]
    return cases
