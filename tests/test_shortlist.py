from datetime import UTC, datetime, timedelta

from ai_news_bot.models import Candidate
from ai_news_bot.shortlist import shortlist_candidates


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def candidate(
    identifier: int,
    *,
    title: str,
    summary: str = "",
    tier: int = 1,
    hours_old: float = 1,
) -> Candidate:
    return Candidate(
        id=str(identifier),
        title=title,
        summary=summary,
        url=f"https://example.test/{identifier}",
        source="test",
        source_tier=tier,
        source_weight=1.0,
        published_at=NOW - timedelta(hours=hours_old),
    )


def test_shortlist_caps_at_twenty_and_is_stable() -> None:
    candidates = [candidate(i, title=f"Model {i} API price drops to ${i}") for i in range(30)]
    first = shortlist_candidates(candidates, NOW)
    second = shortlist_candidates(list(reversed(candidates)), NOW)
    assert len(first) == 20
    assert [item.id for item in first] == [item.id for item in second]


def test_shortlist_does_not_pad_weak_opinion_items_to_fifteen() -> None:
    strong = [candidate(i, title=f"SDK v{i} adds API support") for i in range(4)]
    weak = [
        candidate(100 + i, title="AI may transform the future", summary="A broad opinion.")
        for i in range(20)
    ]
    assert [item.id for item in shortlist_candidates(strong + weak, NOW)] == [
        item.id for item in strong
    ]


def test_shortlist_prefers_primary_recent_specific_sources() -> None:
    primary = candidate(1, title="API v2 price is $1", tier=1, hours_old=2)
    secondary = candidate(2, title="API v2 price is $1", tier=3, hours_old=2)
    old = candidate(3, title="API v3 price is $2", tier=1, hours_old=120)
    result = shortlist_candidates([secondary, old, primary], NOW)
    assert result[0].id == primary.id
