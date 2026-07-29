from __future__ import annotations

import unicodedata
from collections import Counter
from datetime import datetime
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, Field

from .event_history import DuplicateAssessment
from .models import (
    GlobalEventEvidence,
    GlobalEventGateDecision,
    GlobalEventItem,
    GlobalEventScore,
)


IMPACT = {
    "global": 30,
    "multi_market": 24,
    "single_market": 16,
    "niche": 8,
}
INFORMATION_GAIN = {
    "unique": 10,
    "material_update": 7,
    "minor_update": 0,
    "duplicate": 0,
}


class ScoredGlobalEvent(BaseModel):
    record: GlobalEventEvidence
    cluster: list[GlobalEventEvidence] = Field(min_length=1)
    assessment: DuplicateAssessment
    source_name: str = Field(min_length=1, max_length=120)
    published_at: datetime
    score: GlobalEventScore


def _slug(value: str) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )
    return quote(normalized, safe="-$")


def global_event_fingerprint(
    record: GlobalEventEvidence | GlobalEventItem,
) -> str:
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


def corroborate_global_records(
    records: list[GlobalEventEvidence],
) -> dict[str, list[GlobalEventEvidence]]:
    grouped: dict[str, list[GlobalEventEvidence]] = {}
    for record in records:
        grouped.setdefault(global_event_fingerprint(record), []).append(record)
    return {
        fingerprint: sorted(
            values,
            key=lambda item: (
                item.candidate_id,
                item.source_url,
            ),
        )
        for fingerprint, values in sorted(grouped.items())
    }


def _verified_primary(record: GlobalEventEvidence) -> bool:
    return (
        record.source_type != "trusted_secondary"
        and record.verification_status == "verified"
    )


def _independent_secondary_hosts(
    cluster: list[GlobalEventEvidence],
) -> set[str]:
    return {
        hostname
        for item in cluster
        if item.source_type == "trusted_secondary"
        and item.verification_status == "verified"
        and (hostname := urlsplit(item.source_url).hostname)
    }


def evaluate_global_event(
    record: GlobalEventEvidence,
    cluster: list[GlobalEventEvidence],
    duplicate: DuplicateAssessment,
    published_at: datetime,
    now: datetime,
) -> GlobalEventGateDecision:
    age_hours = (now - published_at).total_seconds() / 3600
    reasons: list[str] = []
    checks = (
        (not record.occurred or age_hours < 0, "not_occurred"),
        (not record.material_change, "missing_material_change"),
        (record.funding_only, "funding_only"),
        (record.opinion_only, "opinion_without_evidence"),
        (
            record.policy_claim and not record.policy_text_available,
            "policy_without_text",
        ),
        (record.title_body_conflict, "title_body_conflict"),
        (
            record.scientific_claim and not record.scientific_verified,
            "scientific_claim_unverified",
        ),
        (not record.evidence_anchors, "invalid_evidence_anchor"),
        (age_hours > 168, "outside_global_window"),
        (
            duplicate.status in {"duplicate", "minor_update"},
            "duplicate_without_material_update",
        ),
    )
    reasons.extend(reason for failed, reason in checks if failed)
    has_evidence = _verified_primary(record) or (
        len(_independent_secondary_hosts(cluster)) >= 2
    )
    if not has_evidence:
        reasons.append("insufficient_corroboration")
    return GlobalEventGateDecision(
        eligible=not reasons,
        rejection_reasons=list(dict.fromkeys(reasons)),
    )


def _recency(age_hours: float) -> int:
    return 20 if age_hours <= 24 else 16 if age_hours <= 48 else 8


def _evidence_quality(
    record: GlobalEventEvidence,
    cluster: list[GlobalEventEvidence],
) -> int:
    if _verified_primary(record):
        return 15
    return 12 if len(_independent_secondary_hosts(cluster)) >= 2 else 0


def _global_relevance(record: GlobalEventEvidence) -> int:
    if record.impact_scope == "global":
        return 20
    markets = {
        " ".join(value.casefold().split())
        for value in record.geographic_scope
        if value.strip()
    }
    if len(markets) >= 2:
        return 16
    if len(markets) == 1:
        return 8
    return 4


def score_global_event(
    record: GlobalEventEvidence,
    cluster: list[GlobalEventEvidence],
    duplicate: DuplicateAssessment,
    published_at: datetime,
    now: datetime,
) -> GlobalEventScore:
    age_hours = max(0, (now - published_at).total_seconds() / 3600)
    return GlobalEventScore(
        impact=IMPACT[record.impact_scope],
        global_relevance=_global_relevance(record),
        recency=_recency(age_hours),
        evidence_quality=_evidence_quality(record, cluster),
        information_gain=INFORMATION_GAIN[duplicate.status],
        clarity=5,
    )


def _to_item(value: ScoredGlobalEvent) -> GlobalEventItem:
    supporting_urls = list(
        dict.fromkeys(
            item.source_url
            for item in value.cluster
            if item.source_url != value.record.source_url
        )
    )[:2]
    record = value.record
    return GlobalEventItem(
        event_id=global_event_fingerprint(record),
        candidate_id=record.candidate_id,
        category=record.category,
        title_zh=record.title_zh,
        what_happened_zh=record.what_happened_zh,
        why_it_matters_zh=record.why_it_matters_zh,
        affected_groups_zh=record.affected_groups_zh,
        key_facts=record.key_facts,
        source_name=value.source_name,
        source_url=record.source_url,
        supporting_urls=supporting_urls,
        published_at=value.published_at,
        primary_entity=record.primary_entity,
        product_or_policy=record.product_or_policy,
        change_signature=record.change_signature,
        version_or_metric=record.version_or_metric,
        effective_date=record.effective_date,
        event_entities=record.event_entities,
        score=value.score,
    )


def select_global_events(
    prepared: list[ScoredGlobalEvent],
    limit: int = 5,
) -> list[GlobalEventItem]:
    ordered = sorted(
        (
            value
            for value in prepared
            if value.score.total >= 65
            and value.assessment.status in {"unique", "material_update"}
        ),
        key=lambda value: (
            -value.score.total,
            -value.score.recency,
            -value.score.evidence_quality,
            -value.published_at.timestamp(),
            global_event_fingerprint(value.record),
        ),
    )
    category_counts: Counter[str] = Counter()
    selected: list[GlobalEventItem] = []
    for value in ordered:
        if len(selected) >= max(0, min(limit, 5)):
            break
        if category_counts[value.record.category] >= 2:
            continue
        selected.append(_to_item(value))
        category_counts[value.record.category] += 1
    return selected
