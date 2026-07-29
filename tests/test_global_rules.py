from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from ai_news_bot.event_history import DuplicateAssessment
from ai_news_bot.global_rules import (
    ScoredGlobalEvent,
    corroborate_global_records,
    evaluate_global_event,
    global_event_fingerprint,
    score_global_event,
    select_global_events,
)
from ai_news_bot.models import (
    EvidenceAnchor,
    GlobalEventEvidence,
    GlobalEventScore,
)


NOW = datetime(2026, 7, 29, 1, 5, tzinfo=UTC)


def valid_record(
    *,
    candidate_id: str = "event",
    category: str = "models_products",
    source_url: str = "https://official.example/event",
    source_type: str = "official_announcement",
    verification_status: str = "verified",
    impact_scope: str = "global",
    geographic_scope: list[str] | None = None,
    **changes: object,
) -> GlobalEventEvidence:
    values: dict[str, object] = {
        "candidate_id": candidate_id,
        "occurred": True,
        "material_change": True,
        "category": category,
        "title_zh": "Acme 正式发布 Model X",
        "what_happened_zh": "Acme 正式发布 Model X，并向公众开放使用。",
        "why_it_matters_zh": "普通用户现在可以直接使用该模型的新能力。",
        "affected_groups_zh": ["普通用户", "企业采购者"],
        "key_facts": ["模型已经正式发布"],
        "evidence_anchors": [
            EvidenceAnchor(
                quote="Acme officially released Model X.",
                locator="Announcement",
            )
        ],
        "source_url": source_url,
        "source_type": source_type,
        "verification_status": verification_status,
        "primary_entity": "Acme",
        "product_or_policy": "Model X",
        "change_signature": "public-release",
        "version_or_metric": "Model X",
        "effective_date": "2026-07-29",
        "event_entities": ["Acme", "Model X"],
        "impact_scope": impact_scope,
        "geographic_scope": (
            geographic_scope
            if geographic_scope is not None
            else ["全球市场"]
        ),
    }
    values.update(changes)
    return GlobalEventEvidence.model_validate(values)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"occurred": False}, "not_occurred"),
        ({"material_change": False}, "missing_material_change"),
        ({"funding_only": True}, "funding_only"),
        ({"opinion_only": True}, "opinion_without_evidence"),
        (
            {"policy_claim": True, "policy_text_available": False},
            "policy_without_text",
        ),
        ({"title_body_conflict": True}, "title_body_conflict"),
        (
            {"scientific_claim": True, "scientific_verified": False},
            "scientific_claim_unverified",
        ),
    ],
)
def test_global_gate_rejects_invalid_event(
    changes: dict[str, object],
    reason: str,
) -> None:
    record = valid_record(**changes)

    decision = evaluate_global_event(
        record,
        [record],
        DuplicateAssessment(status="unique"),
        NOW,
        NOW,
    )

    assert not decision.eligible
    assert reason in decision.rejection_reasons


def test_verified_primary_source_passes_without_corroboration() -> None:
    record = valid_record()

    decision = evaluate_global_event(
        record,
        [record],
        DuplicateAssessment(status="unique"),
        NOW,
        NOW,
    )

    assert decision.eligible
    assert decision.rejection_reasons == []


def test_secondary_requires_two_independent_verified_hosts() -> None:
    first = valid_record(
        candidate_id="first",
        source_url="https://one.example/event",
        source_type="trusted_secondary",
    )
    same_host = valid_record(
        candidate_id="same-host",
        source_url="https://one.example/another",
        source_type="trusted_secondary",
    )
    second = valid_record(
        candidate_id="second",
        source_url="https://two.example/event",
        source_type="trusted_secondary",
    )

    failed = evaluate_global_event(
        first,
        [first, same_host],
        DuplicateAssessment(status="unique"),
        NOW,
        NOW,
    )
    passed = evaluate_global_event(
        first,
        [first, second],
        DuplicateAssessment(status="unique"),
        NOW,
        NOW,
    )

    assert not failed.eligible
    assert "insufficient_corroboration" in failed.rejection_reasons
    assert passed.eligible


def test_corroboration_groups_records_by_event_fingerprint() -> None:
    first = valid_record(candidate_id="first")
    second = valid_record(
        candidate_id="second",
        source_url="https://two.example/event",
    )
    other = valid_record(
        candidate_id="other",
        product_or_policy="Model Y",
    )

    clusters = corroborate_global_records([other, second, first])

    assert [item.candidate_id for item in clusters[global_event_fingerprint(first)]] == [
        "first",
        "second",
    ]
    assert len(clusters) == 2


def test_event_between_48_hours_and_seven_days_is_valid_fallback() -> None:
    record = valid_record()

    decision = evaluate_global_event(
        record,
        [record],
        DuplicateAssessment(status="unique"),
        NOW - timedelta(hours=49),
        NOW,
    )
    score = score_global_event(
        record,
        [record],
        DuplicateAssessment(status="unique"),
        NOW - timedelta(hours=49),
        NOW,
    )

    assert decision.eligible
    assert score.recency == 8


def test_event_older_than_seven_days_is_rejected() -> None:
    record = valid_record()

    decision = evaluate_global_event(
        record,
        [record],
        DuplicateAssessment(status="unique"),
        NOW - timedelta(hours=169),
        NOW,
    )

    assert not decision.eligible
    assert "outside_global_window" in decision.rejection_reasons


def test_duplicate_without_material_update_is_rejected() -> None:
    record = valid_record()

    decision = evaluate_global_event(
        record,
        [record],
        DuplicateAssessment(status="duplicate"),
        NOW,
        NOW,
    )

    assert not decision.eligible
    assert "duplicate_without_material_update" in decision.rejection_reasons


def test_global_score_totals_exactly_one_hundred_at_caps() -> None:
    record = valid_record()

    score = score_global_event(
        record,
        [record],
        DuplicateAssessment(status="unique"),
        NOW,
        NOW,
    )

    assert score.total == 100


def prepared_event(
    index: int,
    *,
    category: str,
    total: int,
) -> ScoredGlobalEvent:
    record = valid_record(
        candidate_id=f"event-{index}",
        category=category,
        product_or_policy=f"Model {index}",
        version_or_metric=f"v{index}",
        source_url=f"https://official.example/event-{index}",
    )
    score = GlobalEventScore(
        impact=min(30, total),
        global_relevance=min(20, max(0, total - 30)),
        recency=min(20, max(0, total - 50)),
        evidence_quality=min(15, max(0, total - 70)),
        information_gain=min(10, max(0, total - 85)),
        clarity=min(5, max(0, total - 95)),
    )
    return ScoredGlobalEvent(
        record=record,
        cluster=[record],
        assessment=DuplicateAssessment(status="unique"),
        source_name="Official",
        published_at=NOW - timedelta(minutes=index),
        score=score,
    )


def test_selection_enforces_threshold_category_cap_and_daily_limit() -> None:
    prepared = [
        prepared_event(
            index,
            category=(
                "models_products"
                if index < 4
                else "companies_business"
                if index < 7
                else "policy_regulation"
            ),
            total=100 - index,
        )
        for index in range(9)
    ]
    prepared.append(
        prepared_event(
            20,
            category="research_breakthroughs",
            total=64,
        )
    )

    selected = select_global_events(prepared)

    assert len(selected) == 5
    assert all(item.score.total >= 65 for item in selected)
    assert Counter(item.category for item in selected).most_common(1)[0][1] <= 2
