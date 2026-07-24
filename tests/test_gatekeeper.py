from __future__ import annotations

import pytest

from ai_news_bot.gatekeeper import evaluate_gates
from ai_news_bot.models import ChangeFact, EvidenceAnchor, EvidenceRecord


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
            )
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
        action_horizon_days=0,
        resource_available=True,
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"funding_only": True}, "funding_only"),
        ({"opinion_only": True}, "opinion_without_evidence"),
        (
            {"policy_claim": True, "effective_date": "2026-08-01"},
            "policy_without_terms_or_date",
        ),
        (
            {"policy_claim": True, "policy_terms": ["API providers must register"]},
            "policy_without_terms_or_date",
        ),
        ({"vague_claim_without_evidence": True}, "vague_claim_without_evidence"),
        ({"title_body_conflict": True}, "title_body_conflict"),
        (
            {"scientific_claim": True, "original_paper_or_independent_validation": False},
            "scientific_claim_unverified",
        ),
        ({"concrete_changes": []}, "missing_concrete_change"),
        ({"recommended_action": []}, "missing_action"),
        ({"evidence_anchors": []}, "invalid_evidence_anchor"),
    ],
)
def test_forced_rejections(changes: dict, reason: str) -> None:
    decision = evaluate_gates(valid_record().model_copy(update=changes), "unique")

    assert not decision.eligible_main_try
    assert reason in decision.rejection_reasons


def test_unavailable_original_is_watch_only_with_verified_trusted_secondary() -> None:
    record = valid_record().model_copy(
        update={
            "source_type": "trusted_secondary",
            "verification_status": "verified",
            "original_source_status": "unavailable",
        }
    )

    decision = evaluate_gates(record, "unique")

    assert not decision.eligible_main_try
    assert decision.eligible_watch
    assert decision.rejection_reasons == ["unverified_primary_source"]


def test_policy_claim_with_terms_and_date_can_pass() -> None:
    record = valid_record().model_copy(
        update={
            "policy_claim": True,
            "policy_terms": ["API providers must register before deployment"],
            "effective_date": "2026-08-01",
        }
    )

    decision = evaluate_gates(record, "unique")

    assert decision.eligible_main_try
    assert decision.eligible_watch
    assert decision.rejection_reasons == []


@pytest.mark.parametrize(
    ("policy_terms", "effective_date"),
    [
        ([], "2026-08-01"),
        (["   "], "2026-08-01"),
        (["API providers must register"], None),
        (["API providers must register"], "   "),
        (["API providers must register"], "not-a-date"),
        (["API providers must register"], "2026-02-30"),
    ],
)
def test_policy_claim_requires_nonblank_terms_and_a_valid_iso_date(
    policy_terms: list[str], effective_date: str | None
) -> None:
    record = valid_record().model_copy(
        update={
            "policy_claim": True,
            "policy_terms": policy_terms,
            "effective_date": effective_date,
        }
    )

    decision = evaluate_gates(record, "unique")

    assert not decision.eligible_main_try
    assert decision.rejection_reasons == ["policy_without_terms_or_date"]


@pytest.mark.parametrize("secondary_status", ["unavailable", "blocked"])
def test_unverified_trusted_secondary_is_rejected_from_watch(
    secondary_status: str,
) -> None:
    record = valid_record().model_copy(
        update={
            "source_type": "trusted_secondary",
            "verification_status": secondary_status,
            "original_source_status": "unavailable",
        }
    )

    decision = evaluate_gates(record, "unique")

    assert not decision.eligible_main_try
    assert not decision.eligible_watch
    assert decision.rejection_reasons == ["unverified_primary_source"]


def test_trusted_secondary_without_original_source_status_is_rejected_from_watch() -> None:
    record = valid_record().model_copy(
        update={
            "source_type": "trusted_secondary",
            "verification_status": "verified",
        }
    )

    decision = evaluate_gates(record, "unique")

    assert not decision.eligible_main_try
    assert not decision.eligible_watch
    assert decision.rejection_reasons == ["unverified_primary_source"]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"funding_only": True}, "funding_only"),
        ({"opinion_only": True}, "opinion_without_evidence"),
        (
            {"policy_claim": True, "effective_date": "2026-08-01"},
            "policy_without_terms_or_date",
        ),
        (
            {"policy_claim": True, "policy_terms": ["API providers must register"]},
            "policy_without_terms_or_date",
        ),
        ({"vague_claim_without_evidence": True}, "vague_claim_without_evidence"),
        ({"title_body_conflict": True}, "title_body_conflict"),
        (
            {"scientific_claim": True, "original_paper_or_independent_validation": False},
            "scientific_claim_unverified",
        ),
        ({"concrete_changes": []}, "missing_concrete_change"),
        ({"recommended_action": []}, "missing_action"),
        ({"affected_audience": []}, "missing_affected_audience"),
        ({"affected_area": []}, "missing_affected_area"),
        ({"evidence_anchors": []}, "invalid_evidence_anchor"),
    ],
)
def test_trusted_secondary_watch_exception_does_not_bypass_fatal_rejections(
    changes: dict, reason: str
) -> None:
    record = valid_record().model_copy(
        update={
            "source_type": "trusted_secondary",
            "verification_status": "verified",
            "original_source_status": "blocked",
            **changes,
        }
    )

    decision = evaluate_gates(record, "unique")

    assert not decision.eligible_main_try
    assert not decision.eligible_watch
    assert reason in decision.rejection_reasons
    assert "unverified_primary_source" in decision.rejection_reasons


@pytest.mark.parametrize("duplicate_status", ["duplicate", "minor_update"])
def test_duplicate_without_material_update_is_rejected_everywhere(
    duplicate_status: str,
) -> None:
    decision = evaluate_gates(valid_record(), duplicate_status)  # type: ignore[arg-type]

    assert decision.rejection_reasons == ["duplicate_without_material_update"]
    assert not decision.eligible_main_try
    assert not decision.eligible_watch


def test_material_update_can_remain_eligible() -> None:
    decision = evaluate_gates(valid_record(), "material_update")

    assert decision.eligible_main_try
    assert decision.eligible_watch
    assert decision.rejection_reasons == []


def test_reasons_accumulate_once_in_fixed_order() -> None:
    record = valid_record().model_copy(
        update={
            "funding_only": True,
            "opinion_only": True,
            "concrete_changes": [],
            "recommended_action": [],
        }
    )

    decision = evaluate_gates(record, "duplicate")

    assert decision.rejection_reasons == [
        "funding_only",
        "opinion_without_evidence",
        "missing_concrete_change",
        "missing_action",
        "duplicate_without_material_update",
    ]


def test_claim_anchor_mismatch_is_rejected_as_invalid_evidence_anchor() -> None:
    record = valid_record().model_copy(
        update={"evidence_covers_full_claim": False}
    )

    decision = evaluate_gates(record, "unique")

    assert "invalid_evidence_anchor" in decision.rejection_reasons
    assert decision.eligible_main_try is False
