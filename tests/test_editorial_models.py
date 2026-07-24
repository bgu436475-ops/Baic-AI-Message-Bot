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
