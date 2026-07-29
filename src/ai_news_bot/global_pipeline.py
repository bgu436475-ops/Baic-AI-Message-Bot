from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from .event_history import DuplicateAssessment
from .global_editor import GlobalEventExtractionError
from .global_rules import ScoredGlobalEvent, global_event_fingerprint
from .models import (
    Candidate,
    GlobalEventEvidence,
    GlobalEventGateDecision,
    GlobalEventItem,
    GlobalEventScore,
    GlobalPipelineStats,
    VerificationStatus,
)
from .source_fetcher import FetchedSource


class SourceFetcherLike(Protocol):
    def fetch_many(self, values: list[Candidate]) -> list[FetchedSource]: ...


GlobalShortlistCallable = Callable[
    [list[Candidate], datetime],
    list[Candidate],
]
GlobalExtractCallable = Callable[
    [Candidate, FetchedSource],
    GlobalEventEvidence,
]
GlobalClassifyCallable = Callable[
    [GlobalEventEvidence, datetime],
    DuplicateAssessment,
]
GlobalCorroborateCallable = Callable[
    [list[GlobalEventEvidence]],
    dict[str, list[GlobalEventEvidence]],
]
GlobalGateCallable = Callable[
    [
        GlobalEventEvidence,
        list[GlobalEventEvidence],
        DuplicateAssessment,
        datetime,
        datetime,
    ],
    GlobalEventGateDecision,
]
GlobalScoreCallable = Callable[
    [
        GlobalEventEvidence,
        list[GlobalEventEvidence],
        DuplicateAssessment,
        datetime,
        datetime,
    ],
    GlobalEventScore,
]
GlobalSelectCallable = Callable[
    [list[ScoredGlobalEvent]],
    list[GlobalEventItem],
]
DuplicateAuditStatus = Literal[
    "not_evaluated",
    "unique",
    "material_update",
    "minor_update",
    "duplicate",
]


@dataclass(frozen=True)
class GlobalPipelineDependencies:
    shortlist: GlobalShortlistCallable
    source_fetcher: SourceFetcherLike
    extract: GlobalExtractCallable
    classify: GlobalClassifyCallable
    corroborate: GlobalCorroborateCallable
    gate: GlobalGateCallable
    score: GlobalScoreCallable
    select: GlobalSelectCallable


class GlobalAuditEntry(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=160)
    source_url: str = Field(max_length=1000)
    fetch_status: VerificationStatus
    corroborating_source_count: int = Field(ge=0, le=20)
    rejection_reasons: list[str] = Field(default_factory=list, max_length=20)
    duplicate_status: DuplicateAuditStatus = "not_evaluated"
    score: GlobalEventScore | None = None
    selected: bool = False


class GlobalPipelineAudit(BaseModel):
    generated_at: datetime
    entries: list[GlobalAuditEntry] = Field(default_factory=list, max_length=20)
    rejection_reason_counts: dict[str, int] = Field(default_factory=dict)


class GlobalPipelineResult(BaseModel):
    events: list[GlobalEventItem] = Field(default_factory=list, max_length=5)
    stats: GlobalPipelineStats
    audit: GlobalPipelineAudit
    fallback_used: bool = False


def run_global_pipeline(
    candidates: list[Candidate],
    dependencies: GlobalPipelineDependencies,
    now: datetime,
) -> GlobalPipelineResult:
    shortlisted = dependencies.shortlist(candidates, now)
    fetched = dependencies.source_fetcher.fetch_many(shortlisted)
    candidate_by_id = {item.id: item for item in shortlisted}
    source_by_id = {item.candidate_id: item for item in fetched}
    records: list[GlobalEventEvidence] = []
    failures: dict[str, GlobalAuditEntry] = {}
    last_error: GlobalEventExtractionError | None = None
    for source in fetched:
        candidate = candidate_by_id[source.candidate_id]
        try:
            records.append(dependencies.extract(candidate, source))
        except GlobalEventExtractionError as error:
            last_error = error
            failures[candidate.id] = GlobalAuditEntry(
                candidate_id=candidate.id,
                source_url=source.final_url,
                fetch_status=source.status,
                corroborating_source_count=0,
                rejection_reasons=["global_extraction_failed"],
            )
    if fetched and not records and failures:
        raise GlobalEventExtractionError(
            "all global event extractions failed"
        ) from last_error

    clusters = dependencies.corroborate(records)
    prepared: list[ScoredGlobalEvent] = []
    entries: list[GlobalAuditEntry] = []
    for record in records:
        candidate = candidate_by_id[record.candidate_id]
        source = source_by_id[record.candidate_id]
        cluster = clusters[global_event_fingerprint(record)]
        assessment = dependencies.classify(record, now)
        decision = dependencies.gate(
            record,
            cluster,
            assessment,
            candidate.published_at,
            now,
        )
        score = None
        if decision.eligible:
            score = dependencies.score(
                record,
                cluster,
                assessment,
                candidate.published_at,
                now,
            )
            prepared.append(
                ScoredGlobalEvent(
                    record=record,
                    cluster=cluster,
                    assessment=assessment,
                    source_name=candidate.source,
                    published_at=candidate.published_at,
                    score=score,
                )
            )
        entries.append(
            GlobalAuditEntry(
                candidate_id=candidate.id,
                source_url=record.source_url,
                fetch_status=source.status,
                corroborating_source_count=len(cluster),
                rejection_reasons=decision.rejection_reasons,
                duplicate_status=assessment.status,
                score=score,
            )
        )
    events = dependencies.select(prepared)
    selected_ids = {item.candidate_id for item in events}
    all_entries = [
        *entries,
        *(failures[key] for key in sorted(failures)),
    ]
    all_entries = [
        entry.model_copy(
            update={"selected": entry.candidate_id in selected_ids}
        )
        for entry in all_entries
    ]
    rejected = [entry for entry in all_entries if not entry.selected]
    reasons = Counter(
        reason
        for entry in rejected
        for reason in entry.rejection_reasons
    )
    audit = GlobalPipelineAudit(
        generated_at=now,
        entries=all_entries,
        rejection_reason_counts=dict(
            sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
        ),
    )
    return GlobalPipelineResult(
        events=events,
        stats=GlobalPipelineStats(
            candidate_count=len(candidates),
            shortlist_count=len(shortlisted),
            source_verified_count=sum(
                source.status == "verified" for source in fetched
            ),
            rejected_count=len(rejected),
            top_rejection_reasons=audit.rejection_reason_counts,
        ),
        audit=audit,
        fallback_used=any(
            48 * 3600
            < (now - event.published_at).total_seconds()
            <= 168 * 3600
            for event in events
        ),
    )
