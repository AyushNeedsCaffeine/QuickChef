"""Loader for the append-only feedback queue used to grow the golden dataset."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FEEDBACK_PATH = Path(__file__).resolve().parent / "golden" / "feedback.jsonl"
KINDS = ("dish_rejected", "dish_correction", "review_liked", "review_disliked")


@dataclass(frozen=True)
class FeedbackEvent:
    id: str
    kind: str
    captured_at: str
    needs_review: bool
    status: str
    data: dict

    @property
    def review_pending(self) -> bool:
        return self.needs_review and self.status == "pending_review"

    @property
    def raw_dish(self) -> str:
        dish = self.data.get("dish") or {}
        correction = self.data.get("correction") or {}
        return str(dish.get("raw") or correction.get("rejected_raw") or "").strip()

    def summary(self) -> dict:
        dish = self.data.get("dish") or {}
        correction = self.data.get("correction") or {}
        return {
            "id": self.id,
            "kind": self.kind,
            "captured_at": self.captured_at,
            "status": self.status,
            "needs_review": self.needs_review,
            "raw": self.raw_dish,
            "rejected": dish.get("suggested_dish") or correction.get("rejected_dish"),
            "accepted": correction.get("accepted_dish"),
        }


def load_feedback(path: Path | None = None) -> list[FeedbackEvent]:
    path = path or FEEDBACK_PATH
    if not path.exists():
        return []
    events: list[FeedbackEvent] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(raw, dict) or not raw.get("id") or raw.get("kind") not in KINDS:
                raise ValueError(f"{path}:{line_no}: invalid feedback event")
            events.append(
                FeedbackEvent(
                    id=str(raw["id"]),
                    kind=str(raw["kind"]),
                    captured_at=str(raw.get("captured_at") or ""),
                    needs_review=bool(raw.get("needs_review")),
                    status=str(raw.get("status") or ("pending_review" if raw.get("needs_review") else "recorded")),
                    data=raw,
                )
            )
    return events


def summarize(events: list[FeedbackEvent]) -> dict:
    by_kind = {kind: 0 for kind in KINDS}
    for event in events:
        by_kind[event.kind] = by_kind.get(event.kind, 0) + 1
    return {
        "total": len(events),
        "pending_review": sum(1 for event in events if event.review_pending),
        "by_kind": by_kind,
    }
