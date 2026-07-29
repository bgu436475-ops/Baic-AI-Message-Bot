from datetime import UTC, datetime

import pytest

from ai_news_bot.event_history import DuplicateAssessment
from ai_news_bot.global_editor import GlobalEventExtractionError
from ai_news_bot.global_pipeline import (
    GlobalPipelineDependencies,
    run_global_pipeline,
)
from ai_news_bot.global_rules import (
    corroborate_global_records,
    evaluate_global_event,
    score_global_event,
    select_global_events,
)
from ai_news_bot.models import Candidate
from ai_news_bot.source_fetcher import FetchedSource
from tests.test_global_rules import valid_record


NOW = datetime(2026, 7, 29, 1, 5, tzinfo=UTC)


def candidates() -> list[Candidate]:
    return [
        Candidate(
            id=value,
            title="Acme releases Model X",
            url=f"https://example.com/{value}",
            source="Acme",
            source_tier=1,
            source_weight=1,
            published_at=NOW,
            lane_hints=["global"],
        )
        for value in ("selected", "rejected")
    ]


class Fetcher:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    def fetch_many(self, values: list[Candidate]) -> list[FetchedSource]:
        self.trace.append("fetch")
        return [
            FetchedSource(
                candidate_id=value.id,
                requested_url=value.url,
                final_url=value.url,
                status="verified",
                status_code=200,
                title=value.title,
                text="Acme officially released Model X.",
                fetched_at=NOW,
            )
            for value in values
        ]


def dependencies(
    trace: list[str],
    *,
    fail_all: bool = False,
) -> GlobalPipelineDependencies:
    def shortlist(values, now, limit=20):
        trace.append("shortlist")
        return values

    def extract(candidate, source):
        trace.append("extract")
        if fail_all:
            raise GlobalEventExtractionError("failed")
        return valid_record(
            candidate_id=candidate.id,
            source_url=candidate.url,
            material_change=candidate.id == "selected",
        )

    def corroborate(records):
        trace.append("corroborate")
        return corroborate_global_records(records)

    def classify(record, now):
        if "dedupe" not in trace:
            trace.append("dedupe")
        return DuplicateAssessment(status="unique")

    def gate(record, cluster, assessment, published_at, now):
        if "gate" not in trace:
            trace.append("gate")
        return evaluate_global_event(
            record, cluster, assessment, published_at, now
        )

    def score(record, cluster, assessment, published_at, now):
        if "score" not in trace:
            trace.append("score")
        return score_global_event(
            record, cluster, assessment, published_at, now
        )

    def select(values):
        trace.append("select")
        return select_global_events(values)

    return GlobalPipelineDependencies(
        shortlist=shortlist,
        source_fetcher=Fetcher(trace),
        extract=extract,
        classify=classify,
        corroborate=corroborate,
        gate=gate,
        score=score,
        select=select,
    )


def test_global_pipeline_runs_all_stages_and_audits_rejection() -> None:
    trace: list[str] = []

    result = run_global_pipeline(
        candidates(),
        dependencies(trace),
        NOW,
    )

    assert trace == [
        "shortlist",
        "fetch",
        "extract",
        "extract",
        "corroborate",
        "dedupe",
        "gate",
        "score",
        "select",
    ]
    assert [item.candidate_id for item in result.events] == ["selected"]
    assert result.stats.rejected_count == 1


def test_all_global_extraction_failures_raise() -> None:
    with pytest.raises(
        GlobalEventExtractionError,
        match="all global event extractions failed",
    ):
        run_global_pipeline(
            candidates(),
            dependencies([], fail_all=True),
            NOW,
        )
