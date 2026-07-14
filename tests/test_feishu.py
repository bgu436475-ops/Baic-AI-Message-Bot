from datetime import UTC, datetime

from ai_news_bot.feishu import build_card, digest_markdown, make_signature
from ai_news_bot.models import DailyDigest, NewsItem


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
