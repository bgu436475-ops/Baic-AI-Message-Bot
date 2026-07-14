from datetime import UTC, datetime

from ai_news_bot.collectors import _entry_datetime


def test_undated_feed_entry_is_not_treated_as_current_news() -> None:
    now = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    assert _entry_datetime({}, now) is None


def test_feed_entry_uses_real_published_time() -> None:
    now = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    entry = {"published": "Mon, 13 Jul 2026 08:30:00 GMT"}
    assert _entry_datetime(entry, now) == datetime(2026, 7, 13, 8, 30, tzinfo=UTC)
