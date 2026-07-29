import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ai_news_bot.models import (
    DailyDigest,
    DigestBoards,
    EditorialDigest,
    EditorialNewsItem,
    GlobalPipelineStats,
    NewsItem,
    PipelineStats,
    ScoreBreakdown,
)
from ai_news_bot.web_export import export_digest_for_web


def test_export_digest_for_web(tmp_path):
    digest = DailyDigest(
        generated_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        candidate_count=12,
        source_count=3,
        items=[
            NewsItem(
                original_title="Test model",
                title_en="Test model release",
                summary_en="This is a summary.",
                title_zh="测试模型发布",
                summary_zh="这是摘要。",
                url="https://example.com/model",
                source="Example",
                published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
                category="new_models",
                importance=88,
            )
        ],
    )
    output = tmp_path / "public" / "data" / "latest.json"

    export_digest_for_web(digest, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 12
    assert payload["items"][0]["title_zh"] == "测试模型发布"
    assert payload["items"][0]["title_en"] == "Test model release"


def test_digest_v2_serializes_published_and_empty_results() -> None:
    generated_at = datetime(2026, 7, 14, tzinfo=timezone.utc)
    item = NewsItem(
        original_title="Test model",
        title_zh="测试模型发布",
        summary_zh="这是摘要。",
        url="https://example.com/model",
        source="Example",
        published_at=generated_at,
        category="new_models",
        importance=88,
    )

    published = DailyDigest(
        generated_at=generated_at,
        candidate_count=1,
        source_count=1,
        items=[item],
    )
    empty = DailyDigest(
        generated_at=generated_at,
        candidate_count=0,
        source_count=0,
        run_status="no_qualifying_items",
        items=[],
    )

    assert published.model_dump()["schema_version"] == 2
    assert published.model_dump()["run_status"] == "published"
    assert published.items
    assert empty.model_dump()["schema_version"] == 2
    assert empty.model_dump()["run_status"] == "no_qualifying_items"
    assert empty.items == []


@pytest.mark.parametrize(
    ("run_status", "items"),
    [("published", []), ("no_qualifying_items", ["item"])],
)
def test_digest_v2_rejects_status_and_item_mismatches(
    run_status: str, items: list[NewsItem] | list[str]
) -> None:
    generated_at = datetime(2026, 7, 14, tzinfo=timezone.utc)
    if items == ["item"]:
        items = [
            NewsItem(
                original_title="Test model",
                title_zh="测试模型发布",
                summary_zh="这是摘要。",
                url="https://example.com/model",
                source="Example",
                published_at=generated_at,
                category="new_models",
                importance=88,
            )
        ]

    with pytest.raises(ValidationError):
        DailyDigest(
            generated_at=generated_at,
            candidate_count=len(items),
            source_count=len(items),
            run_status=run_status,
            items=items,
        )


def test_export_digest_for_web_serializes_schema_v4_boards_and_items(tmp_path) -> None:
    generated_at = datetime(2026, 7, 23, tzinfo=timezone.utc)
    story = EditorialNewsItem(
        candidate_id="model-x",
        board="must_read",
        original_title="Model X API price update",
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
        source="Example",
        published_at=generated_at,
        category="new_models",
        score=ScoreBreakdown(
            relevance=25,
            actionability=20,
            specificity=15,
            information_gain=15,
            evidence_quality=15,
            time_sensitivity=10,
        ),
    )
    digest = EditorialDigest(
        generated_at=generated_at,
        candidate_count=1,
        source_count=1,
        daily_narrative_zh="今天有一条技术情报通过核验。",
        global_pipeline_stats=GlobalPipelineStats(
            candidate_count=0,
            shortlist_count=0,
            source_verified_count=0,
            rejected_count=0,
        ),
        boards=DigestBoards(must_read=[story]),
        items=[story],
        pipeline_stats=PipelineStats(
            candidate_count=1,
            shortlist_count=1,
            source_verified_count=1,
            rejected_count=0,
        ),
    )
    output = tmp_path / "public" / "data" / "latest.json"

    export_digest_for_web(digest, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 4
    assert payload["boards"]["must_read"][0]["candidate_id"] == "model-x"
    assert payload["items"] == [payload["boards"]["must_read"][0]]
