from __future__ import annotations

from datetime import datetime

from .event_history import DuplicateAssessment
from .models import EvidenceRecord, ScoreBreakdown


RELEVANCE = {"direct": 25, "adjacent": 15, "low": 5}
INFORMATION_GAIN = {
    "unique": 15,
    "material_update": 10,
    "minor_update": 3,
    "duplicate": 0,
}
EVIDENCE = {
    "official_announcement": 15,
    "paper": 15,
    "model_card": 15,
    "repository": 14,
    "law_or_regulation": 15,
    "financial_filing": 15,
    "official_demo": 12,
    "trusted_secondary": 8,
}


def score_record(
    record: EvidenceRecord,
    assessment: DuplicateAssessment,
    published_at: datetime,
    now: datetime,
) -> ScoreBreakdown:
    actionability = (
        20
        if (
            record.resource_available
            and record.action_horizon_days is not None
            and record.action_horizon_days <= 7
        )
        else 14
        if record.recommended_action
        else 0
    )
    specificity = min(
        15,
        len(record.concrete_changes) * 7
        + (4 if record.version_or_metric else 0)
        + (4 if record.effective_date else 0),
    )
    age_hours = max(0, (now - published_at).total_seconds() / 3600)
    time_sensitivity = 10 if age_hours <= 24 else 7 if age_hours <= 72 else 2
    penalties = 0
    if assessment.status == "minor_update":
        penalties -= 20
    if not record.evidence_covers_full_claim:
        penalties -= 15
    if record.marketing_exaggeration:
        penalties -= 10
    if age_hours > 72 and not record.effective_date:
        penalties -= 10
    return ScoreBreakdown(
        relevance=RELEVANCE[record.relevance_signal],
        actionability=actionability,
        specificity=specificity,
        information_gain=INFORMATION_GAIN[assessment.status],
        evidence_quality=EVIDENCE[record.source_type],
        time_sensitivity=time_sensitivity,
        penalties=penalties,
    )
