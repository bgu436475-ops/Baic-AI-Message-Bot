from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .models import (
    EditorialDigest,
    EditorialNewsItem,
    EvidenceRecord,
    GlobalEventEvidence,
    GlobalEventItem,
)


BEIJING = ZoneInfo("Asia/Shanghai")
RETENTION_DAYS = 7
GENERIC_EVENT_ENTITIES = frozenset(
    {"ai", "api", "sdk", "model", "agent", "release", "update"}
)


class DuplicateAssessment(BaseModel):
    status: Literal["unique", "material_update", "minor_update", "duplicate"]
    update_of: str | None = None


def _slug(value: str) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )
    return quote(normalized, safe="-$")


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


def _valid_entry(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    string_fields = (
        "fingerprint",
        "recorded_at",
        "change_signature",
        "version_or_metric",
        "effective_date",
        "source_url",
    )
    if any(not isinstance(value.get(field), str) for field in string_fields):
        return False
    if "lane" in value and value["lane"] not in {"global", "technical"}:
        return False
    entities = value.get("entities")
    if not isinstance(entities, list) or not all(
        isinstance(entity, str) for entity in entities
    ):
        return False
    for field in ("resource_available", "scientific_verified"):
        if field in value and not isinstance(value[field], bool):
            return False
    for field in ("primary_entity", "product_or_model"):
        if field in value and not isinstance(value[field], str):
            return False
    if "source_type" in value and not isinstance(value["source_type"], str):
        return False
    geographic_scope = value.get("geographic_scope", [])
    if not isinstance(geographic_scope, list) or not all(
        isinstance(region, str) for region in geographic_scope
    ):
        return False
    try:
        _recorded_at(value)
    except (TypeError, ValueError):
        return False
    return True


def _is_active(entry: dict[str, Any], now: datetime) -> bool:
    recorded_day = _recorded_at(entry).astimezone(BEIJING).date()
    current_day = _aware(now).astimezone(BEIJING).date()
    age_days = (current_day - recorded_day).days
    return 0 <= age_days <= RETENTION_DAYS


def _entities(
    event_entities: list[str],
    primary_entity: str,
    product_or_model: str,
) -> list[str]:
    values = [*event_entities, primary_entity, product_or_model]
    return sorted({_slug(value) for value in values if _slug(value)})


def _scientific_verified(record: EvidenceRecord | EditorialNewsItem) -> bool:
    if isinstance(record, EvidenceRecord):
        return record.original_paper_or_independent_validation
    return record.scientific_verified


def _global_fingerprint(
    record: GlobalEventEvidence | GlobalEventItem,
) -> str:
    if isinstance(record, GlobalEventItem):
        return record.event_id
    return "|".join(
        _slug(part)
        for part in (
            record.primary_entity,
            record.product_or_policy,
            record.change_signature,
            record.version_or_metric,
            record.effective_date or "",
        )
    )


def _snapshot(
    record: (
        EvidenceRecord
        | EditorialNewsItem
        | GlobalEventEvidence
        | GlobalEventItem
    ),
    now: datetime,
) -> dict[str, Any]:
    if isinstance(record, (GlobalEventEvidence, GlobalEventItem)):
        fingerprint = _global_fingerprint(record)
        source_url = record.source_url
        product_or_model = record.product_or_policy
        lane = "global"
        resource_available = False
        scientific_verified = (
            record.scientific_verified
            if isinstance(record, GlobalEventEvidence)
            else False
        )
        source_type = (
            record.source_type
            if isinstance(record, GlobalEventEvidence)
            else ""
        )
        geographic_scope = (
            [_slug(region) for region in record.geographic_scope]
            if isinstance(record, GlobalEventEvidence)
            else []
        )
    elif isinstance(record, EvidenceRecord):
        fingerprint = event_fingerprint(record)
        source_url = record.source_url
        product_or_model = record.product_or_model
        lane = "technical"
        resource_available = record.resource_available
        scientific_verified = _scientific_verified(record)
        source_type = record.source_type
        geographic_scope = []
    else:
        fingerprint = record.event_fingerprint
        source_url = record.evidence_url
        product_or_model = record.product_or_model
        lane = "technical"
        resource_available = record.resource_available
        scientific_verified = _scientific_verified(record)
        source_type = ""
        geographic_scope = []
    return {
        "fingerprint": fingerprint,
        "lane": lane,
        "recorded_at": _aware(now).isoformat(),
        "entities": _entities(
            record.event_entities,
            record.primary_entity,
            product_or_model,
        ),
        "primary_entity": _slug(record.primary_entity),
        "product_or_model": _slug(product_or_model),
        "change_signature": _slug(record.change_signature),
        "version_or_metric": _slug(record.version_or_metric),
        "effective_date": _slug(record.effective_date or ""),
        "resource_available": resource_available,
        "scientific_verified": scientific_verified,
        "source_type": source_type,
        "geographic_scope": geographic_scope,
        "source_url": source_url,
    }


class EventHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        events = payload.get("events", [])
        if not isinstance(events, list):
            return []
        normalized: list[dict[str, Any]] = []
        for entry in events:
            if not _valid_entry(entry):
                continue
            current = dict(entry)
            current.setdefault("lane", "technical")
            current.setdefault("source_type", "")
            current.setdefault("geographic_scope", [])
            normalized.append(current)
        return normalized

    def _active(self, now: datetime) -> list[dict[str, Any]]:
        return [entry for entry in self._load() if _is_active(entry, now)]

    def classify(
        self,
        record: EvidenceRecord,
        now: datetime,
    ) -> DuplicateAssessment:
        current = _snapshot(record, now)
        active = sorted(
            (
                entry
                for entry in self._active(now)
                if entry.get("lane", "technical") == "technical"
            ),
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
            current_product = current.get("product_or_model", "")
            entry_product = entry.get("product_or_model", "")
            current_primary = current.get("primary_entity", "")
            entry_primary = entry.get("primary_entity", "")
            shared_non_company_entities = (
                current_entities.intersection(entry.get("entities", []))
                - {current_primary, entry_primary, "", *GENERIC_EVENT_ENTITIES}
            )
            same_primary = (
                bool(current_primary)
                and bool(entry_primary)
                and current_primary == entry_primary
            )
            same_specific_product = (
                bool(current_product)
                and bool(entry_product)
                and current_product == entry_product
                and current_product not in GENERIC_EVENT_ENTITIES
            )
            identity_agrees = same_primary and (
                same_specific_product or bool(shared_non_company_entities)
            )
            same_event = (
                identity_agrees
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

    def classify_global(
        self,
        record: GlobalEventEvidence,
        now: datetime,
    ) -> DuplicateAssessment:
        current = _snapshot(record, now)
        active = sorted(
            (
                entry
                for entry in self._active(now)
                if entry.get("lane") == "global"
            ),
            key=lambda entry: (
                _recorded_at(entry),
                str(entry["fingerprint"]),
            ),
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
            geographic_expansion = bool(
                set(current.get("geographic_scope", []))
                - set(exact.get("geographic_scope", []))
            )
            primary_confirmation = (
                current.get("source_type") != "trusted_secondary"
                and exact.get("source_type") == "trusted_secondary"
            )
            if geographic_expansion or primary_confirmation:
                return DuplicateAssessment(
                    status="material_update",
                    update_of=str(exact["fingerprint"]),
                )
            return DuplicateAssessment(status="duplicate")

        current_entities = set(current["entities"])
        for entry in active:
            same_primary = (
                bool(current["primary_entity"])
                and current["primary_entity"]
                == entry.get("primary_entity", "")
            )
            shared_entities = current_entities.intersection(
                entry.get("entities", [])
            )
            same_change = (
                current["change_signature"]
                == entry.get("change_signature", "")
            )
            if not (same_primary and shared_entities and same_change):
                continue
            material_update = (
                current["version_or_metric"]
                != entry.get("version_or_metric", "")
                or current["effective_date"]
                != entry.get("effective_date", "")
                or bool(
                    set(current.get("geographic_scope", []))
                    - set(entry.get("geographic_scope", []))
                )
                or (
                    current.get("source_type") != "trusted_secondary"
                    and entry.get("source_type") == "trusted_secondary"
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

    def record_global(
        self,
        records: list[GlobalEventEvidence],
        now: datetime,
    ) -> None:
        events = self._active(now)
        for record in records:
            snapshot = _snapshot(record, now)
            events = [
                entry
                for entry in events
                if not (
                    entry.get("lane") == "global"
                    and entry.get("fingerprint") == snapshot["fingerprint"]
                )
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
        for item in [*digest.global_events, *digest.items]:
            snapshot = _snapshot(item, recorded_at)
            events = [
                entry
                for entry in events
                if not (
                    entry.get("lane", "technical") == snapshot["lane"]
                    and entry.get("fingerprint") == snapshot["fingerprint"]
                )
            ]
            events.append(snapshot)
        self._write(events)

    def _write(self, events: list[dict[str, Any]]) -> None:
        ordered = sorted(
            events,
            key=lambda entry: (_recorded_at(entry), str(entry["fingerprint"])),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = (
            json.dumps({"events": ordered}, ensure_ascii=False, indent=2) + "\n"
        )
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
