from __future__ import annotations

from typing import Literal

from .models import EvidenceRecord, GateDecision, RejectionCode


DuplicateStatus = Literal["unique", "material_update", "minor_update", "duplicate"]


def evaluate_gates(
    record: EvidenceRecord,
    duplicate_status: DuplicateStatus,
) -> GateDecision:
    """Apply editorial eligibility rules without allowing downstream bypasses."""
    reasons: list[RejectionCode] = []
    checks: list[tuple[bool, RejectionCode]] = [
        (record.funding_only, "funding_only"),
        (record.opinion_only, "opinion_without_evidence"),
        (
            record.policy_claim and (not record.policy_terms or not record.effective_date),
            "policy_without_terms_or_date",
        ),
        (record.vague_claim_without_evidence, "vague_claim_without_evidence"),
        (record.title_body_conflict, "title_body_conflict"),
        (
            record.scientific_claim
            and not record.original_paper_or_independent_validation,
            "scientific_claim_unverified",
        ),
        (not record.concrete_changes, "missing_concrete_change"),
        (not record.recommended_action, "missing_action"),
        (not record.affected_audience, "missing_affected_audience"),
        (not record.affected_area, "missing_affected_area"),
        (not record.evidence_anchors, "invalid_evidence_anchor"),
        (
            duplicate_status in {"duplicate", "minor_update"},
            "duplicate_without_material_update",
        ),
    ]
    reasons.extend(code for failed, code in checks if failed)

    verified_primary = (
        record.verification_status == "verified"
        and record.source_type != "trusted_secondary"
    )
    if not verified_primary:
        reasons.append("unverified_primary_source")

    fatal_watch = set(reasons) - {"unverified_primary_source"}
    trusted_watch = (
        record.source_type == "trusted_secondary"
        and record.verification_status == "verified"
        and record.original_source_status in {"unavailable", "blocked"}
        and bool(record.concrete_changes)
        and bool(record.evidence_anchors)
    )

    return GateDecision(
        eligible_main_try=verified_primary and not reasons,
        eligible_watch=not fatal_watch and (verified_primary or trusted_watch),
        rejection_reasons=list(dict.fromkeys(reasons)),
    )
