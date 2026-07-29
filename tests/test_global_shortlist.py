from datetime import UTC, datetime, timedelta

from ai_news_bot.global_shortlist import shortlist_global_candidates
from ai_news_bot.models import Candidate


NOW = datetime(2026, 7, 29, 1, 5, tzinfo=UTC)


def candidate(
    *,
    candidate_id: str = "event",
    title: str = "Commission adopts binding AI transparency rules",
    summary: str = "The rules take effect on 2 August.",
    source: str = "Official News",
    source_tier: int = 1,
    source_weight: float = 1,
    published_at: datetime = NOW,
    lanes: list[str] | None = None,
) -> Candidate:
    return Candidate(
        id=candidate_id,
        title=title,
        summary=summary,
        url=f"https://example.com/{candidate_id}",
        source=source,
        source_tier=source_tier,
        source_weight=source_weight,
        published_at=published_at,
        lane_hints=lanes if lanes is not None else ["global"],
    )


def test_global_shortlist_does_not_require_api_or_numeric_tokens() -> None:
    event = candidate()

    assert shortlist_global_candidates([event], NOW) == [event]


def test_global_shortlist_excludes_technical_and_items_older_than_seven_days() -> None:
    repository = candidate(
        candidate_id="repository",
        source="GitHub · AI 新项目",
        lanes=["technical"],
    )
    stale = candidate(
        candidate_id="stale",
        published_at=NOW - timedelta(days=8),
    )

    assert shortlist_global_candidates([repository, stale], NOW) == []


def test_global_shortlist_prefers_fresh_primary_sources_deterministically() -> None:
    fallback = candidate(
        candidate_id="fallback",
        published_at=NOW - timedelta(hours=72),
    )
    secondary = candidate(
        candidate_id="secondary",
        source_tier=2,
        source_weight=0.9,
        published_at=NOW - timedelta(hours=2),
    )
    primary = candidate(
        candidate_id="primary",
        published_at=NOW - timedelta(hours=4),
    )

    result = shortlist_global_candidates(
        [fallback, secondary, primary],
        NOW,
        limit=2,
    )

    assert [item.id for item in result] == ["primary", "secondary"]


def test_global_shortlist_never_returns_more_than_twenty() -> None:
    values = [
        candidate(candidate_id=f"event-{index:02d}")
        for index in range(25)
    ]

    assert len(shortlist_global_candidates(values, NOW, limit=100)) == 20
