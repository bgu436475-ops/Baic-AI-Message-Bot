from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .models import EditorialDigest, EditorialNewsItem, EvidenceRecord


BEIJING = ZoneInfo("Asia/Shanghai")
RETENTION_DAYS = 7
_WORD_TOKEN = re.compile(r"[$€£¥]?\w+%?", flags=re.UNICODE)


class DuplicateAssessment(BaseModel):
    status: Literal["unique", "material_update", "minor_update", "duplicate"]
    update_of: str | None = None


def _slug(value: str) -> str:
    normalized = value.casefold().replace("_", " ")
    return "-".join(_WORD_TOKEN.findall(normalized))


def event_fingerprint(record: EvidenceRecord) -> str:
    parts = [
        record.primary_entity,
        record.product_or_model,
        record.change_signature,
        record.version_or_metric,
        record.effective_date or "",
    ]
    return "|".join(_slug(part) for part in parts)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _recorded_at(entry: dict[str, Any]) -> datetime:
    return _aware(datetime.fromisoformat(str(entry["recorded_at"])))


def _is_active(entry: dict[str, Any], now: datetime) -> bool:
    recorded_day = _recorded_at(entry).astimezone(BEIJING).date()
    current_day = _aware(now).astimezone(BEIJING).date()
    return (current_day - recorded_day).days <= RETENTION_DAYS


def _entities(
    event_entities: list[str],
    primary_entity: str,
    product_or_model: str,
) -> list[str]:
    values = event_entities or [primary_entity, product_or_model]
    return sorted({_slug(value) for value in values if _slug(value)})


def _scientific_verified(record: EvidenceRecord | EditorialNewsItem) -> bool:
    if isinstance(record, EvidenceRecord):
        return record.original_paper_or_independent_validation
    return record.scientific_verified


def _snapshot(
    record: EvidenceRecord | EditorialNewsItem,
    now: datetime,
) -> dict[str, Any]:
    if isinstance(record, EvidenceRecord):
        fingerprint = event_fingerprint(record)
        source_url = record.source_url
        product_or_model = record.product_or_model
    else:
        fingerprint = record.event_fingerprint
        source_url = record.evidence_url
        product_or_model = ""
    return {
        "fingerprint": fingerprint,
        "recorded_at": _aware(now).isoformat(),
        "entities": _entities(
            record.event_entities,
            record.primary_entity,
            product_or_model,
        ),
        "change_signature": _slug(record.change_signature),
        "version_or_metric": _slug(record.version_or_metric),
        "effective_date": _slug(record.effective_date or ""),
        "resource_available": record.resource_available,
        "scientific_verified": _scientific_verified(record),
        "source_url": source_url,
    }


class EventHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        events = payload.get("events", [])
        if not isinstance(events, list):
            raise ValueError("event history events must be a list")
        return events

    def _active(self, now: datetime) -> list[dict[str, Any]]:
        return [entry for entry in self._load() if _is_active(entry, now)]

    def classify(
        self,
        record: EvidenceRecord,
        now: datetime,
    ) -> DuplicateAssessment:
        current = _snapshot(record, now)
        active = sorted(
            self._active(now),
            key=lambda entry: (_recorded_at(entry), str(entry["fingerprint"])),
            reverse=True,
        )
        exact = next(
            (
                entry
                for entry in active
                if entry["fingerprint"] == current["fingerprint"]
            ),
            None,
        )
        if exact is not None:
            newly_material = (
                current["resource_available"]
                and not exact.get("resource_available", False)
            ) or (
                current["scientific_verified"]
                and not exact.get("scientific_verified", False)
            )
            return DuplicateAssessment(
                status="material_update" if newly_material else "duplicate",
                update_of=(
                    str(exact["fingerprint"]) if newly_material else None
                ),
            )

        current_entities = set(current["entities"])
        for entry in active:
            same_event = (
                bool(current_entities.intersection(entry.get("entities", [])))
                and entry.get("change_signature") == current["change_signature"]
            )
            if not same_event:
                continue
            material_update = (
                entry.get("version_or_metric", "")
                != current["version_or_metric"]
                or entry.get("effective_date", "") != current["effective_date"]
                or (
                    current["resource_available"]
                    and not entry.get("resource_available", False)
                )
                or (
                    current["scientific_verified"]
                    and not entry.get("scientific_verified", False)
                )
            )
            return DuplicateAssessment(
                status="material_update" if material_update else "minor_update",
                update_of=str(entry["fingerprint"]),
            )
        return DuplicateAssessment(status="unique")

    def record(self, records: list[EvidenceRecord], now: datetime) -> None:
        events = self._active(now)
        for record in records:
            snapshot = _snapshot(record, now)
            events = [
                entry
                for entry in events
                if entry.get("fingerprint") != snapshot["fingerprint"]
            ]
            events.append(snapshot)
        self._write(events)

    def record_digest(
        self,
        digest: EditorialDigest,
        now: datetime | None = None,
    ) -> None:
        recorded_at = now or datetime.now(UTC)
        events = self._active(recorded_at)
        for item in digest.items:
            snapshot = _snapshot(item, recorded_at)
            events = [
                entry
                for entry in events
                if entry.get("fingerprint") != snapshot["fingerprint"]
            ]
            events.append(snapshot)
        self._write(events)

    def _write(self, events: list[dict[str, Any]]) -> None:
        ordered = sorted(
            events,
            key=lambda entry: (_recorded_at(entry), str(entry["fingerprint"])),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"events": ordered}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
