from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_news_bot.event_history import DuplicateAssessment
from ai_news_bot.models import ChangeFact, EvidenceAnchor, EvidenceRecord
from ai_news_bot.scoring import score_record


NOW = datetime(2026, 7, 23, 1, 5, tzinfo=UTC)


def valid_record() -> EvidenceRecord:
    return EvidenceRecord(
        candidate_id="one",
        title_zh="Model X API 输入价格调整",
        summary_zh="输入价格为每百万 token 1 美元。",
        category="new_models",
        source_url="https://model.example/pricing",
        source_type="official_announcement",
        verification_status="verified",
        concrete_changes=[
            ChangeFact(
                change_type="pricing",
                statement="输入价格为每百万 token 1 美元。",
                numbers=["$1"],
                entities=["Model X"],
            ),
            ChangeFact(
                change_type="pricing",
                statement="批处理价格为每百万 token 0.5 美元。",
                numbers=["$0.50"],
                entities=["Model X"],
            ),
        ],
        evidence_anchors=[
            EvidenceAnchor(
                quote="Input price is $1 per million tokens.",
                locator="Pricing",
            )
        ],
        affected_audience=["API developers"],
        affected_area=["inference cost"],
        recommended_action=["Recalculate usage cost"],
        event_entities=["Example", "Model X"],
        primary_entity="Example",
        product_or_model="Model X",
        change_signature="api-input-price",
        version_or_metric="$1 / million tokens",
        relevance_signal="direct",
        action_horizon_days=3,
        resource_available=True,
    )


def test_score_maps_factual_signals_and_penalties_exactly() -> None:
    score = score_record(
        valid_record().model_copy(
            update={
                "marketing_exaggeration": True,
                "evidence_covers_full_claim": False,
            }
        ),
        DuplicateAssessment(status="material_update"),
        published_at=NOW - timedelta(hours=80),
        now=NOW,
    )

    assert score.model_dump() == {
        "relevance": 25,
        "actionability": 20,
        "specificity": 15,
        "information_gain": 10,
        "evidence_quality": 15,
        "time_sensitivity": 2,
        "penalties": -35,
        "total": 52,
    }
    assert score.total == 52


@pytest.mark.parametrize(
    ("signal", "expected"),
    [("direct", 25), ("adjacent", 15), ("low", 5)],
)
def test_relevance_mapping_is_exact(signal: str, expected: int) -> None:
    record = valid_record().model_copy(update={"relevance_signal": signal})

    result = score_record(
        record,
        DuplicateAssessment(status="unique"),
        published_at=NOW,
        now=NOW,
    )

    assert result.relevance == expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("unique", 15),
        ("material_update", 10),
        ("minor_update", 3),
        ("duplicate", 0),
    ],
)
def test_information_gain_mapping_is_exact(
    status: str,
    expected: int,
) -> None:
    result = score_record(
        valid_record(),
        DuplicateAssessment(status=status),  # type: ignore[arg-type]
        published_at=NOW,
        now=NOW,
    )

    assert result.information_gain == expected


@pytest.mark.parametrize(
    ("source_type", "expected"),
    [
        ("official_announcement", 15),
        ("paper", 15),
        ("model_card", 15),
        ("repository", 14),
        ("law_or_regulation", 15),
        ("financial_filing", 15),
        ("official_demo", 12),
        ("trusted_secondary", 8),
    ],
)
def test_evidence_quality_mapping_is_exact(
    source_type: str,
    expected: int,
) -> None:
    record = valid_record().model_copy(update={"source_type": source_type})

    result = score_record(
        record,
        DuplicateAssessment(status="unique"),
        published_at=NOW,
        now=NOW,
    )

    assert result.evidence_quality == expected


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"resource_available": True, "action_horizon_days": 7}, 20),
        ({"resource_available": True, "action_horizon_days": 8}, 14),
        ({"resource_available": False, "action_horizon_days": 1}, 14),
        ({"resource_available": True, "action_horizon_days": None}, 14),
        (
            {
                "resource_available": False,
                "action_horizon_days": None,
                "recommended_action": [],
            },
            0,
        ),
    ],
)
def test_actionability_uses_resource_horizon_then_recommendation(
    changes: dict[str, object],
    expected: int,
) -> None:
    result = score_record(
        valid_record().model_copy(update=changes),
        DuplicateAssessment(status="unique"),
        published_at=NOW,
        now=NOW,
    )

    assert result.actionability == expected


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {
                "concrete_changes": [],
                "version_or_metric": "",
                "effective_date": None,
            },
            0,
        ),
        (
            {
                "concrete_changes": valid_record().concrete_changes[:1],
                "version_or_metric": "",
                "effective_date": None,
            },
            7,
        ),
        (
            {
                "concrete_changes": valid_record().concrete_changes[:1],
                "version_or_metric": "v2",
                "effective_date": None,
            },
            11,
        ),
        (
            {
                "concrete_changes": valid_record().concrete_changes[:1],
                "version_or_metric": "",
                "effective_date": "2026-08-01",
            },
            11,
        ),
        (
            {
                "concrete_changes": valid_record().concrete_changes,
                "version_or_metric": "v2",
                "effective_date": "2026-08-01",
            },
            15,
        ),
    ],
)
def test_specificity_adds_concrete_version_and_date_signals_with_cap(
    changes: dict[str, object],
    expected: int,
) -> None:
    result = score_record(
        valid_record().model_copy(update=changes),
        DuplicateAssessment(status="unique"),
        published_at=NOW,
        now=NOW,
    )

    assert result.specificity == expected


@pytest.mark.parametrize(
    ("age_hours", "expected"),
    [(-1, 10), (24, 10), (24.01, 7), (72, 7), (72.01, 2)],
)
def test_time_sensitivity_has_inclusive_24_and_72_hour_boundaries(
    age_hours: float,
    expected: int,
) -> None:
    result = score_record(
        valid_record(),
        DuplicateAssessment(status="unique"),
        published_at=NOW - timedelta(hours=age_hours),
        now=NOW,
    )

    assert result.time_sensitivity == expected


@pytest.mark.parametrize(
    ("assessment", "changes", "age_hours", "expected"),
    [
        ("minor_update", {}, 1, -20),
        ("unique", {"evidence_covers_full_claim": False}, 1, -15),
        ("unique", {"marketing_exaggeration": True}, 1, -10),
        ("unique", {"effective_date": None}, 73, -10),
        ("unique", {"effective_date": "2026-08-01"}, 73, 0),
    ],
)
def test_each_penalty_is_applied_only_under_its_bound_condition(
    assessment: str,
    changes: dict[str, object],
    age_hours: int,
    expected: int,
) -> None:
    result = score_record(
        valid_record().model_copy(update=changes),
        DuplicateAssessment(status=assessment),  # type: ignore[arg-type]
        published_at=NOW - timedelta(hours=age_hours),
        now=NOW,
    )

    assert result.penalties == expected


def test_computed_total_never_falls_below_zero() -> None:
    record = valid_record().model_copy(
        update={
            "relevance_signal": "low",
            "recommended_action": [],
            "resource_available": False,
            "concrete_changes": [],
            "version_or_metric": "",
            "evidence_covers_full_claim": False,
            "marketing_exaggeration": True,
        }
    )

    result = score_record(
        record,
        DuplicateAssessment(status="minor_update"),
        published_at=NOW - timedelta(hours=80),
        now=NOW,
    )

    assert result.total == 0
