from datetime import UTC, datetime, timedelta

from ai_news_bot.curator import build_digest
from ai_news_bot.models import Candidate, NewsItem


def test_digest_reports_freshness_without_rewriting_old_dates() -> None:
    now = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    published = now - timedelta(days=2)
    candidate = Candidate(
        id="one",
        title="Earlier release",
        url="https://example.com/earlier",
        source="Official",
        source_tier=1,
        source_weight=1,
        published_at=published,
    )
    item = NewsItem(
        original_title=candidate.title,
        title_en=candidate.title,
        summary_en="Earlier official release.",
        title_zh="较早的官方发布",
        summary_zh="这是此前发布的重要信息。",
        url=candidate.url,
        source=candidate.source,
        published_at=published,
        category="industry_business",
        importance=70,
    )

    digest = build_digest(
        [candidate], [item], lookback_hours=168, fallback_used=True, now=now
    )

    assert digest.generated_at == now
    assert digest.latest_published_at == published
    assert digest.fresh_count_24h == 0
    assert digest.fallback_used is True
    assert digest.lookback_hours == 168
