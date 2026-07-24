from datetime import UTC, datetime

from ai_news_bot.feishu import build_card, digest_markdown, make_signature
from ai_news_bot.models import (
    DailyDigest,
    DigestBoards,
    EditorialDigest,
    EditorialNewsItem,
    NewsItem,
    PipelineStats,
    ScoreBreakdown,
)


def sample_digest() -> DailyDigest:
    return DailyDigest(
        generated_at=datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
        candidate_count=42,
        source_count=12,
        items=[
            NewsItem(
                original_title="Model X",
                title_zh="Model X 发布",
                summary_zh="这是摘要。",
                url="https://example.com/model-x",
                source="Example",
                published_at=datetime(2026, 7, 13, tzinfo=UTC),
                category="new_models",
                importance=95,
            )
        ],
    )


def editorial_item(
    candidate_id: str,
    board: str,
    *,
    verification_status: str = "verified",
) -> EditorialNewsItem:
    return EditorialNewsItem(
        candidate_id=candidate_id,
        board=board,
        original_title=f"{candidate_id} original title",
        title_zh=f"{candidate_id} 中文标题",
        summary_zh=f"{candidate_id} 的事实摘要。",
        concrete_change=f"{candidate_id} 的 API 价格从每百万 token 2 美元降至 1 美元。",
        affected_audience=["API 开发者"],
        affected_area=["推理成本"],
        recommended_action=["按当前调用量重新计算本月成本"],
        evidence_url=f"https://example.com/{candidate_id}",
        verification_status=verification_status,
        event_fingerprint=f"example|{candidate_id}|price|v2|2026-07-23",
        primary_entity="Example",
        event_entities=["Example", candidate_id],
        change_signature="price",
        version_or_metric="2-to-1-usd",
        source="Example",
        published_at=datetime(2026, 7, 23, tzinfo=UTC),
        category="ai_coding",
        score=ScoreBreakdown(
            relevance=25,
            actionability=20,
            specificity=15,
            information_gain=12,
            evidence_quality=12,
            time_sensitivity=8,
        ),
    )


def three_board_digest() -> EditorialDigest:
    must_read = editorial_item("model-api", "must_read")
    try_now = editorial_item("coding-agent", "try_now")
    watch = editorial_item(
        "research-preview",
        "watch",
        verification_status="blocked",
    )
    return EditorialDigest(
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=12,
        source_count=6,
        boards=DigestBoards(
            must_read=[must_read],
            try_now=[try_now],
            watch=[watch],
        ),
        items=[must_read, try_now, watch],
        pipeline_stats=PipelineStats(
            candidate_count=12,
            shortlist_count=8,
            source_verified_count=5,
            rejected_count=5,
        ),
    )


def legal_empty_digest() -> EditorialDigest:
    return EditorialDigest(
        run_status="no_qualifying_items",
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=12,
        source_count=3,
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=12,
            shortlist_count=6,
            source_verified_count=3,
            rejected_count=6,
            top_rejection_reasons={
                "missing_concrete_change": 3,
                "missing_action": 2,
            },
        ),
    )


def test_build_card_uses_v2_interactive_schema() -> None:
    card = build_card(sample_digest())
    assert card["msg_type"] == "interactive"
    assert card["card"]["schema"] == "2.0"
    assert "https://example.com/model-x" in digest_markdown(sample_digest())
    content = card["card"]["body"]["elements"][0]["content"]
    assert "\n" in content
    assert not content.startswith("# AI 每日新闻")


def test_signature_is_stable() -> None:
    assert make_signature(1_700_000_000, "secret") == make_signature(1_700_000_000, "secret")


def test_published_card_has_three_board_sections_and_action_evidence() -> None:
    content = build_card(three_board_digest())["card"]["body"]["elements"][0][
        "content"
    ]

    assert "今日必看" in content
    assert "值得试用" in content
    assert "观察项" in content
    assert "具体变化" in content
    assert "影响" in content
    assert "建议行动" in content
    assert "核查原文" in content
    assert "⚠ 原始来源暂不可核查" in content
    assert "这对行业具有重要意义" not in content


def test_only_non_empty_editorial_boards_are_rendered() -> None:
    must_read = editorial_item("model-api", "must_read")
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=1,
        source_count=1,
        boards=DigestBoards(must_read=[must_read]),
        items=[must_read],
        pipeline_stats=PipelineStats(
            candidate_count=1,
            shortlist_count=1,
            source_verified_count=1,
            rejected_count=0,
        ),
    )

    content = build_card(digest)["card"]["body"]["elements"][0]["content"]

    assert "今日必看" in content
    assert "值得试用" not in content
    assert "观察项" not in content


def test_legal_empty_card_is_sent_as_normal_success_content() -> None:
    card = build_card(legal_empty_digest())
    content = card["card"]["body"]["elements"][0]["content"]

    assert "今日无内容通过硬门槛" in content
    assert "候选 12 条" in content
    assert "粗筛 6 条" in content
    assert "已核查来源 3 条" in content
    assert "缺少具体变化：3" in content
    assert "缺少可执行行动：2" in content
    assert (
        card["card"]["header"]["subtitle"]["content"]
        == "严格筛选完成 · AI 增长内部群"
    )
