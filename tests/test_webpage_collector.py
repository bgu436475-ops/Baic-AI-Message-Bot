from datetime import UTC, datetime

from ai_news_bot.collectors import WebPageCollector
from ai_news_bot.config import WebPageSource


class FakeResponse:
    text = """
    <a href="/news/model-x">
      <time>Jul 13, 2026</time>
      <h2>Introducing Model X</h2>
      <p>A new model for coding agents.</p>
    </a>
    """

    def raise_for_status(self) -> None:
        return None


def test_webpage_collector(monkeypatch) -> None:
    monkeypatch.setattr("ai_news_bot.collectors.requests.get", lambda *args, **kwargs: FakeResponse())
    source = WebPageSource(
        name="Official",
        url="https://example.com/news",
        tier=1,
        weight=1,
        category_hints=["new_models"],
        item_selector='a[href^="/news/"]',
        title_selector="h2",
        date_selector="time",
        summary_selector="p",
    )
    items = WebPageCollector().collect(
        [source], 36, now=datetime(2026, 7, 13, 12, tzinfo=UTC)
    )
    assert len(items) == 1
    assert items[0].title == "Introducing Model X"
    assert items[0].url == "https://example.com/news/model-x"
