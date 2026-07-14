from datetime import UTC, datetime

from ai_news_bot.dedupe import hard_dedupe
from ai_news_bot.models import Candidate


def candidate(title: str, url: str, tier: int, weight: float) -> Candidate:
    return Candidate(
        id=url,
        title=title,
        url=url,
        source="test",
        source_tier=tier,
        source_weight=weight,
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
    )


def test_hard_dedupe_prefers_official_source() -> None:
    media = candidate("Company launches Model X", "https://media.test/model-x", 3, 0.7)
    official = candidate("Company launches Model X", "https://company.test/model-x", 1, 1.0)
    assert hard_dedupe([media, official]) == [official]


def test_hard_dedupe_strips_tracking_urls() -> None:
    first = candidate("Model X", "https://example.com/x?utm_source=a", 2, 0.8)
    second = candidate("Model X", "https://example.com/x?utm_source=b", 2, 0.8)
    assert len(hard_dedupe([first, second])) == 1

