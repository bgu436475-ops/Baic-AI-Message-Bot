from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from .boards import ScoredEditorialCandidate
from .event_history import DuplicateAssessment, event_fingerprint
from .evidence import validate_anchors
from .models import (
    BoardName,
    Candidate,
    DigestBoards,
    EditorialDigest,
    EditorialDraft,
    EvidenceRecord,
    GateDecision,
    PipelineStats,
    RejectionCode,
    ScoreBreakdown,
    VerificationStatus,
)
from .source_fetcher import FetchedSource
from .text import truncate


DuplicateAuditStatus = Literal[
    "not_evaluated",
    "unique",
    "material_update",
    "minor_update",
    "duplicate",
]


class SourceFetcherLike(Protocol):
    def fetch_many(self, candidates: list[Candidate]) -> list[FetchedSource]: ...


ShortlistCallable = Callable[[list[Candidate], datetime], list[Candidate]]
ExtractCallable = Callable[
    [Candidate, FetchedSource, FetchedSource | None],
    EvidenceRecord,
]
GateCallable = Callable[[EvidenceRecord, str], GateDecision]
ClassifyCallable = Callable[
    [EvidenceRecord, datetime],
    DuplicateAssessment,
]
ScoreCallable = Callable[
    [EvidenceRecord, DuplicateAssessment, datetime, datetime],
    ScoreBreakdown,
]
BoardsCallable = Callable[[list[ScoredEditorialCandidate]], DigestBoards]
OriginalSourceResolver = Callable[
    [Candidate, FetchedSource],
    FetchedSource | None,
]


@dataclass(frozen=True)
class PipelineDependencies:
    shortlist: ShortlistCallable
    source_fetcher: SourceFetcherLike
    extract: ExtractCallable
    gates: GateCallable
    classify: ClassifyCallable
    score: ScoreCallable
    boards: BoardsCallable
    original_source_resolver: OriginalSourceResolver | None = None
    lookback_hours: int = 36
    fallback_used: bool = False


class AuditEntry(BaseModel):
    candidate_id: str
    source_url: str
    fetch_status: VerificationStatus
    anchor_locators: list[str] = Field(default_factory=list)
    gate_reasons: list[RejectionCode] = Field(default_factory=list)
    duplicate_status: DuplicateAuditStatus
    score_breakdown: ScoreBreakdown | None = None
    selected_board: BoardName | None = None


class PipelineAudit(BaseModel):
    generated_at: datetime
    entries: list[AuditEntry]
    rejected: list[AuditEntry]
    rejection_reason_counts: dict[str, int] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    digest: EditorialDigest
    audit: PipelineAudit


@dataclass
class _PreparedRecord:
    candidate: Candidate
    source: FetchedSource
    record: EvidenceRecord
    decision: GateDecision
    assessment: DuplicateAssessment | None = None
    score: ScoreBreakdown | None = None
    scored_candidate: ScoredEditorialCandidate | None = None


def _record_by_candidate(
    candidates: list[Candidate],
) -> dict[str, Candidate]:
    by_id = {candidate.id: candidate for candidate in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("shortlisted candidate IDs must be unique")
    return by_id


def _prepare_draft(
    candidate: Candidate,
    record: EvidenceRecord,
    assessment: DuplicateAssessment,
    score: ScoreBreakdown,
) -> EditorialDraft:
    return EditorialDraft(
        candidate_id=candidate.id,
        original_title=candidate.title,
        title_en=truncate(candidate.title, 120),
        summary_en=truncate(
            candidate.summary or "No summary was provided by the source.",
            320,
        ),
        title_zh=truncate(record.title_zh, 80),
        summary_zh=truncate(record.summary_zh, 220),
        concrete_change="；".join(
            change.statement for change in record.concrete_changes
        ),
        affected_audience=record.affected_audience,
        affected_area=record.affected_area,
        recommended_action=record.recommended_action,
        evidence_url=record.source_url,
        verification_status=(
            record.original_source_status
            if (
                record.source_type == "trusted_secondary"
                and record.original_source_status
                in {"unavailable", "blocked"}
            )
            else record.verification_status
        ),
        event_fingerprint=event_fingerprint(record),
        update_of=assessment.update_of,
        primary_entity=record.primary_entity,
        event_entities=record.event_entities,
        change_signature=record.change_signature,
        version_or_metric=record.version_or_metric,
        effective_date=record.effective_date,
        resource_available=record.resource_available,
        scientific_verified=record.original_paper_or_independent_validation,
        source=candidate.source,
        published_at=candidate.published_at,
        category=record.category,
        extra_categories=[
            category
            for category in record.extra_categories
            if category != record.category
        ][:3],
        score=score,
    )


def _audit_entry(
    value: _PreparedRecord,
    selected_boards: dict[str, BoardName],
) -> AuditEntry:
    return AuditEntry(
        candidate_id=value.candidate.id,
        source_url=value.source.final_url,
        fetch_status=value.source.status,
        anchor_locators=[
            anchor.locator for anchor in value.record.evidence_anchors
        ],
        gate_reasons=value.decision.rejection_reasons,
        duplicate_status=(
            value.assessment.status
            if value.assessment is not None
            else "not_evaluated"
        ),
        score_breakdown=value.score,
        selected_board=selected_boards.get(value.candidate.id),
    )


def run_editorial_pipeline(
    candidates: list[Candidate],
    dependencies: PipelineDependencies,
    now: datetime,
) -> PipelineResult:
    shortlisted = dependencies.shortlist(candidates, now)
    fetched_sources = dependencies.source_fetcher.fetch_many(shortlisted)
    candidate_by_id = _record_by_candidate(shortlisted)

    prepared: list[_PreparedRecord] = []
    seen_source_ids: set[str] = set()
    for source in fetched_sources:
        if source.candidate_id in seen_source_ids:
            raise ValueError("fetched source candidate IDs must be unique")
        seen_source_ids.add(source.candidate_id)
        try:
            candidate = candidate_by_id[source.candidate_id]
        except KeyError as error:
            raise ValueError(
                "fetched source does not match a shortlisted candidate"
            ) from error
        original_source = (
            dependencies.original_source_resolver(candidate, source)
            if dependencies.original_source_resolver is not None
            else None
        )
        if (
            original_source is not None
            and original_source.candidate_id != candidate.id
        ):
            raise ValueError(
                "resolved original source does not match the candidate"
            )
        record = dependencies.extract(candidate, source, original_source)
        if record.candidate_id != candidate.id:
            raise ValueError(
                "extracted evidence does not match the candidate"
            )
        record = validate_anchors(record, source).model_copy(
            update={
                "original_source_status": (
                    original_source.status
                    if original_source is not None
                    else None
                )
            }
        )
        prepared.append(
            _PreparedRecord(
                candidate=candidate,
                source=source,
                record=record,
                decision=dependencies.gates(record, "unique"),
            )
        )

    for value in prepared:
        if not (
            value.decision.eligible_main_try
            or value.decision.eligible_watch
        ):
            continue
        value.assessment = dependencies.classify(value.record, now)
        value.decision = dependencies.gates(
            value.record,
            value.assessment.status,
        )

    scored_candidates: list[ScoredEditorialCandidate] = []
    for value in prepared:
        if value.assessment is None or not (
            value.decision.eligible_main_try
            or value.decision.eligible_watch
        ):
            continue
        value.score = dependencies.score(
            value.record,
            value.assessment,
            value.candidate.published_at,
            now,
        )
        value.scored_candidate = ScoredEditorialCandidate(
            record=value.record,
            decision=value.decision,
            assessment=value.assessment,
            draft=_prepare_draft(
                value.candidate,
                value.record,
                value.assessment,
                value.score,
            ),
        )
        scored_candidates.append(value.scored_candidate)

    boards = dependencies.boards(scored_candidates)
    items = boards.flatten()
    selected_boards = {
        item.candidate_id: item.board
        for item in items
    }
    entries = [
        _audit_entry(value, selected_boards)
        for value in prepared
    ]
    rejected = [
        entry for entry in entries if entry.selected_board is None
    ]
    rejection_counts = Counter(
        reason
        for entry in rejected
        for reason in entry.gate_reasons
    )

    digest = EditorialDigest(
        run_status="published" if items else "no_qualifying_items",
        generated_at=now,
        candidate_count=len(candidates),
        source_count=len({candidate.source for candidate in candidates}),
        latest_published_at=max(
            (item.published_at for item in items),
            default=None,
        ),
        fresh_count_24h=sum(
            1
            for item in items
            if (now - item.published_at).total_seconds() <= 24 * 3600
        ),
        lookback_hours=dependencies.lookback_hours,
        fallback_used=dependencies.fallback_used,
        boards=boards,
        items=items,
        pipeline_stats=PipelineStats(
            candidate_count=len(candidates),
            shortlist_count=len(shortlisted),
            source_verified_count=sum(
                source.status == "verified"
                for source in fetched_sources
            ),
            rejected_count=len(rejected),
            top_rejection_reasons=dict(
                sorted(
                    rejection_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
        ),
    )
    audit = PipelineAudit(
        generated_at=now,
        entries=entries,
        rejected=rejected,
        rejection_reason_counts=digest.pipeline_stats.top_rejection_reasons,
    )
    return PipelineResult(digest=digest, audit=audit)


def write_audit(audit: PipelineAudit, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            audit.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
