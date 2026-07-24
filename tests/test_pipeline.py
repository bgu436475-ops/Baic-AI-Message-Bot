from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import pytest

from ai_news_bot.boards import ScoredEditorialCandidate, build_boards
from ai_news_bot.event_history import DuplicateAssessment
from ai_news_bot.gatekeeper import evaluate_gates
from ai_news_bot.models import (
    Candidate,
    ChangeFact,
    EvidenceAnchor,
    EvidenceRecord,
    GateDecision,
    ScoreBreakdown,
)
from ai_news_bot.pipeline import (
    PipelineDependencies,
    run_editorial_pipeline,
    write_audit,
)
from ai_news_bot.source_fetcher import (
    AllSourcesUnavailableError,
    FetchedSource,
)


NOW = datetime(2026, 7, 23, 1, 5, tzinfo=UTC)
FETCHED_TEXT = "Model-X API v2 is available now for one dollar."


def candidates() -> list[Candidate]:
    return [
        Candidate(
            id=candidate_id,
            title=f"Model-X API v2 launch {candidate_id}",
            summary="The API price is $1 and SDK v2 is available.",
            url=f"https://example.com/{candidate_id}",
            source="Acme",
            source_tier=1,
            source_weight=1,
            published_at=NOW,
            category_hints=["ai_coding"],
        )
        for candidate_id in ("qualifying", "rejected")
    ]


def fetched(candidate: Candidate, *, status: str = "verified") -> FetchedSource:
    return FetchedSource(
        candidate_id=candidate.id,
        requested_url=candidate.url,
        final_url=candidate.url,
        status=status,
        status_code=200 if status == "verified" else 403,
        title=candidate.title,
        text=FETCHED_TEXT if status == "verified" else "",
        fetched_at=NOW,
    )


def evidence(
    candidate: Candidate,
    *,
    source_type: str = "official_announcement",
    original_source_status: str | None = None,
) -> EvidenceRecord:
    is_rejected = candidate.id == "rejected"
    return EvidenceRecord(
        candidate_id=candidate.id,
        title_zh=f"{candidate.id}：Model-X API v2 已发布",
        summary_zh="Model-X API v2 已可使用，价格为一美元。",
        category="ai_coding",
        source_url=candidate.url,
        source_type=source_type,
        verification_status="verified",
        concrete_changes=[
            ChangeFact(
                change_type="release",
                statement="Model-X API v2 is available now for one dollar.",
                numbers=["v2", "$1"],
                entities=["Model-X"],
            )
        ],
        evidence_anchors=[
            EvidenceAnchor(
                quote="Model-X API v2 is available now for one dollar.",
                locator="Release notes / paragraph 2",
            )
        ],
        affected_audience=["API developers"],
        affected_area=["integration"],
        recommended_action=[] if is_rejected else ["Test API v2 this week"],
        event_entities=["Acme", "Model-X"],
        primary_entity="Acme",
        product_or_model="Model-X",
        change_signature="api-release",
        version_or_metric="v2-$1",
        relevance_signal="direct",
        action_horizon_days=3,
        resource_available=True,
        original_source_status=original_source_status,
    )


class FakeFetcher:
    def __init__(
        self,
        trace: list[str],
        *,
        all_fetches_fail: bool = False,
    ) -> None:
        self.trace = trace
        self.all_fetches_fail = all_fetches_fail

    def fetch_many(self, values: list[Candidate]) -> list[FetchedSource]:
        self.trace.append("fetch")
        if self.all_fetches_fail:
            raise AllSourcesUnavailableError("all sources failed")
        return [fetched(value) for value in values]


def fakes(
    trace: list[str],
    *,
    qualifying: bool,
    all_fetches_fail: bool = False,
    record_factory: Callable[[Candidate], EvidenceRecord] = evidence,
    original_source_resolver: (
        Callable[[Candidate, FetchedSource], FetchedSource | None] | None
    ) = None,
) -> PipelineDependencies:
    traced: set[str] = set()

    def mark(stage: str) -> None:
        if stage not in traced:
            trace.append(stage)
            traced.add(stage)

    def shortlist(values: list[Candidate], now: datetime) -> list[Candidate]:
        mark("shortlist")
        return values

    def extract(
        candidate: Candidate,
        source: FetchedSource,
        original_source: FetchedSource | None,
    ) -> EvidenceRecord:
        mark("extract")
        return record_factory(candidate)

    def gates(
        record: EvidenceRecord,
        duplicate_status: str,
    ) -> GateDecision:
        mark("gates")
        if not qualifying:
            return GateDecision(
                eligible_main_try=False,
                eligible_watch=False,
                rejection_reasons=["missing_action"],
            )
        return evaluate_gates(record, duplicate_status)

    def classify(
        record: EvidenceRecord,
        now: datetime,
    ) -> DuplicateAssessment:
        mark("dedupe")
        return DuplicateAssessment(status="unique")

    def score(
        record: EvidenceRecord,
        assessment: DuplicateAssessment,
        published_at: datetime,
        now: datetime,
    ) -> ScoreBreakdown:
        mark("score")
        return ScoreBreakdown(
            relevance=25,
            actionability=20,
            specificity=15,
            information_gain=15,
            evidence_quality=15,
            time_sensitivity=10,
        )

    def boards(
        values: list[ScoredEditorialCandidate],
    ):
        mark("boards")
        return build_boards(values)

    return PipelineDependencies(
        shortlist=shortlist,
        source_fetcher=FakeFetcher(
            trace,
            all_fetches_fail=all_fetches_fail,
        ),
        extract=extract,
        gates=gates,
        classify=classify,
        score=score,
        boards=boards,
        original_source_resolver=original_source_resolver,
    )


def test_pipeline_shortlists_fetches_extracts_gates_scores_and_builds_digest(
    tmp_path: Path,
) -> None:
    trace: list[str] = []

    result = run_editorial_pipeline(
        candidates(),
        dependencies=fakes(trace, qualifying=True),
        now=NOW,
    )

    assert trace == [
        "shortlist",
        "fetch",
        "extract",
        "gates",
        "dedupe",
        "score",
        "boards",
    ]
    assert result.digest.run_status == "published"
    assert [item.candidate_id for item in result.digest.items] == ["qualifying"]
    assert [entry.candidate_id for entry in result.audit.rejected] == ["rejected"]
    assert result.digest.pipeline_stats.top_rejection_reasons == {
        "missing_action": 1
    }

    audit_path = tmp_path / "latest_audit.json"
    write_audit(result.audit, audit_path)
    serialized = audit_path.read_text(encoding="utf-8")
    assert "Release notes / paragraph 2" in serialized
    assert FETCHED_TEXT not in serialized


def test_successful_pipeline_with_zero_qualifiers_is_legal_empty() -> None:
    result = run_editorial_pipeline(
        candidates(),
        dependencies=fakes([], qualifying=False),
        now=NOW,
    )

    assert result.digest.run_status == "no_qualifying_items"
    assert result.digest.items == []


def test_all_fetches_failed_is_not_legal_empty() -> None:
    with pytest.raises(AllSourcesUnavailableError):
        run_editorial_pipeline(
            candidates(),
            dependencies=fakes(
                [],
                qualifying=True,
                all_fetches_fail=True,
            ),
            now=NOW,
        )


def test_model_cannot_invent_original_source_status_for_secondary_exception() -> None:
    def fabricated(candidate: Candidate) -> EvidenceRecord:
        return evidence(
            candidate,
            source_type="trusted_secondary",
            original_source_status="blocked",
        )

    result = run_editorial_pipeline(
        [candidates()[0]],
        dependencies=fakes(
            [],
            qualifying=True,
            record_factory=fabricated,
        ),
        now=NOW,
    )

    assert result.audit.entries[0].gate_reasons == [
        "unverified_primary_source"
    ]
    assert result.digest.run_status == "no_qualifying_items"


def test_explicit_fetched_original_source_can_enable_secondary_watch() -> None:
    candidate = candidates()[0]

    def secondary(value: Candidate) -> EvidenceRecord:
        return evidence(
            value,
            source_type="trusted_secondary",
            original_source_status="verified",
        )

    def original_source(
        value: Candidate,
        source: FetchedSource,
    ) -> FetchedSource:
        return fetched(value, status="blocked")

    result = run_editorial_pipeline(
        [candidate],
        dependencies=fakes(
            [],
            qualifying=True,
            record_factory=secondary,
            original_source_resolver=original_source,
        ),
        now=NOW,
    )

    assert [item.candidate_id for item in result.digest.boards.watch] == [
        candidate.id
    ]
    assert result.digest.items[0].verification_status == "blocked"
