from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from .event_history import DuplicateAssessment
from .models import (
    DigestBoards,
    EditorialDraft,
    EditorialNewsItem,
    EvidenceRecord,
    GateDecision,
)


class ScoredEditorialCandidate(BaseModel):
    record: EvidenceRecord
    decision: GateDecision
    assessment: DuplicateAssessment
    draft: EditorialDraft


def _sort_key(
    candidate: ScoredEditorialCandidate,
) -> tuple[int, int, int, float, str]:
    score = candidate.draft.score
    return (
        -score.total,
        -score.information_gain,
        -score.evidence_quality,
        -candidate.draft.published_at.timestamp(),
        candidate.draft.event_fingerprint,
    )


def _eligible_must(candidate: ScoredEditorialCandidate) -> bool:
    score = candidate.draft.score
    return (
        candidate.decision.eligible_main_try
        and score.total >= 75
        and score.evidence_quality >= 12
        and score.information_gain >= 10
    )


def _eligible_try(candidate: ScoredEditorialCandidate) -> bool:
    score = candidate.draft.score
    record = candidate.record
    return (
        candidate.decision.eligible_main_try
        and score.total >= 62
        and score.actionability >= 14
        and record.resource_available
        and record.action_horizon_days is not None
        and record.action_horizon_days <= 7
    )


def _eligible_watch(candidate: ScoredEditorialCandidate) -> bool:
    return (
        candidate.decision.eligible_watch
        and candidate.draft.score.total >= 50
    )


def _company_key(candidate: ScoredEditorialCandidate) -> str:
    return " ".join(candidate.record.primary_entity.casefold().split())


def _to_item(
    candidate: ScoredEditorialCandidate,
    board: Literal["must_read", "try_now", "watch"],
) -> EditorialNewsItem:
    values = candidate.draft.model_dump()
    values["update_of"] = candidate.assessment.update_of
    return EditorialNewsItem(**values, board=board)


def build_boards(
    items_with_decisions: list[ScoredEditorialCandidate],
) -> DigestBoards:
    ordered = sorted(items_with_decisions, key=_sort_key)
    selected_fingerprints: set[str] = set()
    main_try_company_counts: dict[str, int] = {}

    def allocate(
        *,
        board: Literal["must_read", "try_now", "watch"],
        limit: int,
        eligible: Callable[[ScoredEditorialCandidate], bool],
        enforce_company_cap: bool,
    ) -> list[EditorialNewsItem]:
        selected: list[EditorialNewsItem] = []
        for candidate in ordered:
            if len(selected) >= limit:
                break
            fingerprint = candidate.draft.event_fingerprint
            if fingerprint in selected_fingerprints or not eligible(candidate):
                continue
            company = _company_key(candidate)
            if (
                enforce_company_cap
                and main_try_company_counts.get(company, 0) >= 2
            ):
                continue
            selected.append(_to_item(candidate, board))
            selected_fingerprints.add(fingerprint)
            if enforce_company_cap:
                main_try_company_counts[company] = (
                    main_try_company_counts.get(company, 0) + 1
                )
        return selected

    must_read = allocate(
        board="must_read",
        limit=5,
        eligible=_eligible_must,
        enforce_company_cap=True,
    )
    try_now = allocate(
        board="try_now",
        limit=3,
        eligible=_eligible_try,
        enforce_company_cap=True,
    )
    watch = allocate(
        board="watch",
        limit=3,
        eligible=_eligible_watch,
        enforce_company_cap=False,
    )
    return DigestBoards(
        must_read=must_read,
        try_now=try_now,
        watch=watch,
    )
