from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_news_bot.event_history import EventHistoryStore, event_fingerprint
from ai_news_bot.models import (
    ChangeFact,
    DigestBoards,
    EditorialDigest,
    EditorialNewsItem,
    EvidenceAnchor,
    EvidenceRecord,
    PipelineStats,
    ScoreBreakdown,
)


NOW = datetime(2026, 7, 23, 1, 5, tzinfo=UTC)


def event(
    version_or_metric: str = "v2-$1",
    *,
    candidate_id: str = "event",
    primary_entity: str = "Acme",
    product_or_model: str = "Model-X",
    event_entities: list[str] | None = None,
    change_signature: str = "Price",
    effective_date: str | None = "2026-07-23",
    resource_available: bool = False,
    scientific_claim: bool = False,
    scientific_verified: bool = False,
    title_zh: str = "Model-X 价格更新",
) -> EvidenceRecord:
    return EvidenceRecord(
        candidate_id=candidate_id,
        title_zh=title_zh,
        summary_zh="Model-X 的价格已经更新。",
        category="new_models",
        source_url="https://example.com/pricing",
        source_type="official_announcement",
        verification_status="verified",
        concrete_changes=[
            ChangeFact(
                change_type="price",
                statement=f"Model-X now costs {version_or_metric}.",
                numbers=[version_or_metric],
                entities=["Acme", "Model-X"],
            )
        ],
        evidence_anchors=[
            EvidenceAnchor(
                quote="Model-X price is now one dollar.",
                locator="Pricing",
            )
        ],
        affected_audience=["API developers"],
        affected_area=["inference costs"],
        recommended_action=["Recalculate monthly cost"],
        event_entities=(
            event_entities
            if event_entities is not None
            else ["Model-X", "ACME", "Acme"]
        ),
        primary_entity=primary_entity,
        product_or_model=product_or_model,
        change_signature=change_signature,
        version_or_metric=version_or_metric,
        effective_date=effective_date,
        relevance_signal="direct",
        action_horizon_days=3,
        resource_available=resource_available,
        scientific_claim=scientific_claim,
        original_paper_or_independent_validation=scientific_verified,
    )


def editorial_item(record: EvidenceRecord) -> EditorialNewsItem:
    score = ScoreBreakdown(
        relevance=25,
        actionability=20,
        specificity=15,
        information_gain=15,
        evidence_quality=15,
        time_sensitivity=10,
    )
    return EditorialNewsItem(
        candidate_id=record.candidate_id,
        board="must_read",
        original_title="Model-X pricing update",
        title_zh=record.title_zh,
        summary_zh=record.summary_zh,
        concrete_change=record.concrete_changes[0].statement,
        affected_audience=record.affected_audience,
        affected_area=record.affected_area,
        recommended_action=record.recommended_action,
        evidence_url=record.source_url,
        verification_status=record.verification_status,
        event_fingerprint=event_fingerprint(record),
        primary_entity=record.primary_entity,
        product_or_model=record.product_or_model,
        event_entities=record.event_entities,
        change_signature=record.change_signature,
        version_or_metric=record.version_or_metric,
        effective_date=record.effective_date,
        resource_available=record.resource_available,
        scientific_verified=record.original_paper_or_independent_validation,
        source="Acme",
        published_at=NOW,
        category=record.category,
        score=score,
    )


def digest_with(record: EvidenceRecord) -> EditorialDigest:
    item = editorial_item(record)
    return EditorialDigest(
        generated_at=NOW,
        candidate_count=1,
        source_count=1,
        boards=DigestBoards(must_read=[item]),
        items=[item],
        pipeline_stats=PipelineStats(
            candidate_count=1,
            shortlist_count=1,
            source_verified_count=1,
            rejected_count=0,
        ),
    )


def test_fingerprint_and_persisted_fields_are_normalized_deterministically(
    tmp_path: Path,
) -> None:
    record = event()
    assert (
        event_fingerprint(record)
        == "acme|model-x|price|v2-$1|2026-07-23"
    )

    path = tmp_path / "events.json"
    EventHistoryStore(path).record([record], NOW)

    stored = json.loads(path.read_text(encoding="utf-8"))["events"]
    assert stored == [
        {
            "fingerprint": "acme|model-x|price|v2-$1|2026-07-23",
            "recorded_at": "2026-07-23T01:05:00+00:00",
            "entities": ["acme", "model-x"],
            "primary_entity": "acme",
            "product_or_model": "model-x",
            "change_signature": "price",
            "version_or_metric": "v2-$1",
            "effective_date": "2026-07-23",
            "resource_available": False,
            "scientific_verified": False,
            "source_url": "https://example.com/pricing",
        }
    ]


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            event(product_or_model="C++", event_entities=["Acme", "C++"]),
            event(product_or_model="C#", event_entities=["Acme", "C#"]),
        ),
        (
            event(version_or_metric="v1.2"),
            event(version_or_metric="v1-2"),
        ),
    ],
)
def test_fingerprint_preserves_meaningful_punctuation(
    left: EvidenceRecord,
    right: EvidenceRecord,
) -> None:
    assert event_fingerprint(left) != event_fingerprint(right)


def test_punctuation_distinct_metric_is_not_swallowed_by_exact_match(
    tmp_path: Path,
) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    old = event(version_or_metric="v1.2")
    store.record([old], NOW)

    result = store.classify(
        event(version_or_metric="v1-2"),
        NOW + timedelta(days=1),
    )

    assert result.status == "material_update"
    assert result.update_of == event_fingerprint(old)


def test_exact_event_with_no_new_fact_is_duplicate(tmp_path: Path) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    store.record([event()], NOW)

    result = store.classify(
        event(title_zh="同一事实的另一种标题写法"),
        NOW + timedelta(days=1),
    )

    assert result.status == "duplicate"
    assert result.update_of is None


def test_entity_signature_near_duplicate_is_minor_update(tmp_path: Path) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    store.record([event()], NOW)

    result = store.classify(
        event(product_or_model="Model X API", event_entities=["Acme", "Model-X"]),
        NOW + timedelta(days=1),
    )

    assert result.status == "minor_update"
    assert result.update_of == event_fingerprint(event())


@pytest.mark.parametrize(
    "changes",
    [
        {"version_or_metric": "v3-$1"},
        {"effective_date": "2026-08-01"},
        {"resource_available": True},
        {"scientific_claim": True, "scientific_verified": True},
    ],
)
def test_changed_fact_is_material_update(
    tmp_path: Path,
    changes: dict[str, object],
) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    old = event()
    store.record([old], NOW)

    result = store.classify(
        event(**changes),  # type: ignore[arg-type]
        NOW + timedelta(days=1),
    )

    assert result.status == "material_update"
    assert result.update_of == event_fingerprint(old)


def test_equal_near_duplicate_facts_are_not_promoted_to_material(
    tmp_path: Path,
) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    store.record([event(product_or_model="Model-X")], NOW)

    result = store.classify(
        event(product_or_model="Model X API", event_entities=["Acme", "Model-X"]),
        NOW + timedelta(days=1),
    )

    assert result.status == "minor_update"


def test_distinct_products_at_same_company_do_not_collapse(
    tmp_path: Path,
) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    store.record(
        [
            event(
                product_or_model="Model X",
                event_entities=["Acme", "Model X", "API"],
                change_signature="price",
            )
        ],
        NOW,
    )

    result = store.classify(
        event(
            product_or_model="Model Y",
            event_entities=["Acme", "Model Y", "API"],
            change_signature="price",
        ),
        NOW + timedelta(days=1),
    )

    assert result.status == "unique"


def test_empty_event_entities_still_persist_product_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.json"
    record = event(product_or_model="Model X", event_entities=[])

    EventHistoryStore(path).record([record], NOW)

    stored = json.loads(path.read_text(encoding="utf-8"))["events"][0]
    assert stored["product_or_model"] == "model%20x"
    assert "model%20x" in stored["entities"]


def test_legacy_history_without_product_is_not_used_for_near_match(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.json"
    store = EventHistoryStore(path)
    store.record([event(product_or_model="Model X")], NOW)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["events"][0].pop("product_or_model", None)
    payload["events"][0].pop("primary_entity", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = store.classify(
        event(
            product_or_model="Model X API",
            event_entities=["Acme", "Model-X"],
        ),
        NOW + timedelta(days=1),
    )

    assert result.status == "unique"


def test_retention_uses_beijing_calendar_days_instead_of_elapsed_hours(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 22, 16, 1, tzinfo=UTC)  # Jul 23 in Beijing
    store = EventHistoryStore(tmp_path / "events.json")
    store.record(
        [event(candidate_id="old")],
        datetime(2026, 7, 15, 15, 59, tzinfo=UTC),  # Jul 15 in Beijing
    )

    assert store.classify(event(candidate_id="new"), now).status == "unique"


def test_event_exactly_seven_beijing_days_old_still_dedupes(
    tmp_path: Path,
) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    store.record([event()], NOW - timedelta(days=7))

    assert store.classify(event(), NOW).status == "duplicate"


@pytest.mark.parametrize("future_days", [1, 365])
def test_future_events_do_not_participate_in_dedupe(
    tmp_path: Path,
    future_days: int,
) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    store.record([event()], NOW + timedelta(days=future_days))

    assert store.classify(event(), NOW).status == "unique"


def test_record_prunes_future_events_from_persisted_state(tmp_path: Path) -> None:
    path = tmp_path / "events.json"
    store = EventHistoryStore(path)
    store.record([event()], NOW + timedelta(days=365))
    current = event(version_or_metric="v3-$1")

    store.record([current], NOW)

    stored = json.loads(path.read_text(encoding="utf-8"))["events"]
    assert [entry["fingerprint"] for entry in stored] == [
        event_fingerprint(current)
    ]


def test_record_prunes_events_older_than_seven_beijing_days(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.json"
    store = EventHistoryStore(path)
    store.record([event(candidate_id="old")], NOW - timedelta(days=8))
    current = event(candidate_id="current", version_or_metric="v3-$1")

    store.record([current], NOW)

    stored = json.loads(path.read_text(encoding="utf-8"))["events"]
    assert [entry["fingerprint"] for entry in stored] == [
        event_fingerprint(current)
    ]


def test_record_digest_writes_selected_post_send_state(tmp_path: Path) -> None:
    record = event()
    store = EventHistoryStore(tmp_path / "events.json")

    assert store.classify(record, NOW).status == "unique"
    store.record_digest(digest_with(record), now=NOW)

    assert store.classify(record, NOW + timedelta(days=1)).status == "duplicate"


@pytest.mark.parametrize(
    "payload",
    [
        '{"events": [',
        "[]",
        '{"events": {}}',
    ],
)
def test_corrupt_or_wrong_root_history_recovers_on_next_record(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / "events.json"
    path.write_text(payload, encoding="utf-8")
    store = EventHistoryStore(path)

    assert store.classify(event(), NOW).status == "unique"
    store.record([event()], NOW)

    assert json.loads(path.read_text(encoding="utf-8"))["events"][0][
        "fingerprint"
    ] == event_fingerprint(event())


def test_invalid_entries_are_skipped_without_losing_valid_entries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.json"
    store = EventHistoryStore(path)
    old = event(version_or_metric="v1-$2")
    store.record([old], NOW)
    valid = json.loads(path.read_text(encoding="utf-8"))["events"][0]
    invalid_entries = [
        None,
        "not-an-entry",
        {},
        {**valid, "recorded_at": "not-a-datetime"},
        {**valid, "recorded_at": 123},
        {**valid, "fingerprint": ["not", "a", "string"]},
        {**valid, "entities": "acme"},
        {**valid, "resource_available": "yes"},
    ]
    path.write_text(
        json.dumps({"events": [*invalid_entries, valid]}),
        encoding="utf-8",
    )

    assert store.classify(old, NOW).status == "duplicate"
    current = event(version_or_metric="v2-$1")
    store.record([current], NOW)

    stored = json.loads(path.read_text(encoding="utf-8"))["events"]
    assert {entry["fingerprint"] for entry in stored} == {
        event_fingerprint(old),
        event_fingerprint(current),
    }


def test_state_write_uses_same_directory_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "events.json"
    calls: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def observed_replace(source: str | Path, target: str | Path) -> None:
        calls.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", observed_replace)

    EventHistoryStore(path).record([event()], NOW)

    assert len(calls) == 1
    source, target = calls[0]
    assert source.parent == path.parent
    assert target == path
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_atomic_write_cleans_temp_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "events.json"

    def failed_replace(source: str | Path, target: str | Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", failed_replace)

    with pytest.raises(OSError, match="replace failed"):
        EventHistoryStore(path).record([event()], NOW)

    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []
