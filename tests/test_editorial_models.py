from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_news_bot.models import (
    ChangeFact,
    DigestBoards,
    EditorialDigest,
    EditorialNewsItem,
    EvidenceAnchor,
    PipelineStats,
    ScoreBreakdown,
)


def item(board: str = "must_read") -> EditorialNewsItem:
    return EditorialNewsItem(
        candidate_id="model-x",
        board=board,
        original_title="Model X API price update",
        title_en="Model X API price update",
        summary_en="Input price falls from $2 to $1 per million tokens.",
        title_zh="Model X API 输入价格减半",
        summary_zh="输入价格从每百万 token 2 美元降至 1 美元。",
        concrete_change="输入价格从每百万 token 2 美元降至 1 美元。",
        affected_audience=["API 开发者"],
        affected_area=["推理成本"],
        recommended_action=["按当前调用量重新计算月成本"],
        evidence_url="https://example.com/pricing",
        verification_status="verified",
        event_fingerprint="example|model-x|price|v2|2026-07-23",
        primary_entity="Example",
        event_entities=["Example", "Model X"],
        change_signature="price",
        version_or_metric="v2-$1",
        resource_available=True,
        source="Example",
        published_at=datetime(2026, 7, 23, tzinfo=UTC),
        category="new_models",
        score=ScoreBreakdown(
            relevance=25,
            actionability=20,
            specificity=15,
            information_gain=15,
            evidence_quality=15,
            time_sensitivity=10,
            penalties=0,
        ),
    )


def test_schema_v3_flattens_mutually_exclusive_boards() -> None:
    story = item()
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, tzinfo=UTC),
        candidate_count=80,
        source_count=20,
        boards=DigestBoards(must_read=[story]),
        items=[story],
        pipeline_stats=PipelineStats(
            candidate_count=80,
            shortlist_count=18,
            source_verified_count=15,
            rejected_count=17,
        ),
    )
    assert digest.schema_version == 3
    assert digest.items == digest.boards.flatten()
    assert digest.run_status == "published"
    assert digest.items[0].score.total == 100


def test_schema_v3_accepts_legal_empty_digest() -> None:
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, tzinfo=UTC),
        candidate_count=12,
        source_count=7,
        run_status="no_qualifying_items",
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=12,
            shortlist_count=4,
            source_verified_count=3,
            rejected_count=4,
            top_rejection_reasons={"missing_concrete_change": 3},
        ),
    )
    assert digest.items == []


def test_schema_v3_rejects_duplicate_or_mismatched_boards() -> None:
    story = item()
    with pytest.raises(ValidationError):
        EditorialDigest(
            generated_at=datetime(2026, 7, 23, tzinfo=UTC),
            candidate_count=1,
            source_count=1,
            boards=DigestBoards(
                must_read=[story],
                try_now=[story.model_copy(update={"board": "try_now"})],
            ),
            items=[story],
            pipeline_stats=PipelineStats(
                candidate_count=1,
                shortlist_count=1,
                source_verified_count=1,
                rejected_count=0,
            ),
        )


def test_schema_v3_rejects_item_in_wrong_named_board() -> None:
    with pytest.raises(ValidationError):
        DigestBoards(must_read=[item(board="try_now")])


@pytest.mark.parametrize(
    "evidence_url",
    [
        "http://127.0.0.1/evidence",
        "http://example.com/evidence",
        "https://user:password@example.com/evidence",
        "https://example.com/" + "x" * 240,
    ],
)
def test_editorial_item_rejects_unsafe_or_overlong_evidence_url(
    evidence_url: str,
) -> None:
    with pytest.raises(ValidationError):
        item().model_copy(update={"evidence_url": evidence_url}).__class__.model_validate(
            {**item().model_dump(), "evidence_url": evidence_url}
        )


@pytest.mark.parametrize(
    "effective_date",
    ["2026-02-30", "2026-2-03", "not-a-date"],
)
def test_editorial_item_rejects_invalid_effective_date(
    effective_date: str,
) -> None:
    with pytest.raises(ValidationError):
        EditorialNewsItem.model_validate(
            {**item().model_dump(), "effective_date": effective_date}
        )


def test_editorial_item_accepts_valid_https_url_and_calendar_date() -> None:
    validated = EditorialNewsItem.model_validate(
        {
            **item().model_dump(),
            "evidence_url": "https://example.com/evidence",
            "effective_date": "2024-02-29",
        }
    )

    assert validated.evidence_url == "https://example.com/evidence"
    assert validated.effective_date == "2024-02-29"
