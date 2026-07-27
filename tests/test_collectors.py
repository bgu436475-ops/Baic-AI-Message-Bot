from datetime import UTC, datetime

import pytest
import requests

from ai_news_bot.collectors import (
    GitHubCollector,
    RSSCollector,
    WebPageCollector,
    _entry_datetime,
)
from ai_news_bot.config import (
    GitHubQuery,
    GitHubSources,
    RSSSource,
    WebPageSource,
)
from ai_news_bot.models import Candidate


def test_undated_feed_entry_is_not_treated_as_current_news() -> None:
    now = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    assert _entry_datetime({}, now) is None


def test_feed_entry_uses_real_published_time() -> None:
    now = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    entry = {"published": "Mon, 13 Jul 2026 08:30:00 GMT"}
    assert _entry_datetime(entry, now) == datetime(2026, 7, 13, 8, 30, tzinfo=UTC)


NOW = datetime(2026, 7, 23, 1, 5, tzinfo=UTC)


def _candidate(candidate_id: str) -> Candidate:
    return Candidate(
        id=candidate_id,
        title=f"Model API v2 {candidate_id}",
        summary="API v2 costs $1.",
        url=f"https://example.com/{candidate_id}",
        source="Example",
        source_tier=1,
        source_weight=1,
        published_at=NOW,
    )


def _rss(name: str) -> RSSSource:
    return RSSSource(
        name=name,
        url=f"https://example.com/{name}.xml",
        tier=1,
        weight=1,
    )


def _web(name: str) -> WebPageSource:
    return WebPageSource(
        name=name,
        url=f"https://example.com/{name}",
        tier=1,
        weight=1,
        item_selector="a",
        title_selector="h2",
        date_selector="time",
    )


@pytest.mark.parametrize(
    ("collector", "sources"),
    [
        (RSSCollector(), [_rss("one"), _rss("two")]),
        (WebPageCollector(), [_web("one"), _web("two")]),
    ],
)
def test_multi_source_collection_outcome_counts_total_failure(
    monkeypatch: pytest.MonkeyPatch,
    collector,
    sources,
) -> None:
    monkeypatch.setattr(
        collector,
        "_collect_source",
        lambda *args: (_ for _ in ()).throw(RuntimeError("down")),
    )

    outcome = collector.collect_with_health(sources, 36, now=NOW)

    assert outcome.candidates == []
    assert outcome.attempted == 2
    assert outcome.succeeded == 0
    assert collector.collect(sources, 36, now=NOW) == []


@pytest.mark.parametrize(
    ("collector", "sources"),
    [
        (RSSCollector(), [_rss("empty"), _rss("down")]),
        (WebPageCollector(), [_web("empty"), _web("down")]),
    ],
)
def test_multi_source_collection_outcome_distinguishes_successful_empty(
    monkeypatch: pytest.MonkeyPatch,
    collector,
    sources,
) -> None:
    def collect_source(source, *args):
        if source.name == "down":
            raise RuntimeError("down")
        return []

    monkeypatch.setattr(collector, "_collect_source", collect_source)

    outcome = collector.collect_with_health(sources, 36, now=NOW)

    assert outcome.candidates == []
    assert outcome.attempted == 2
    assert outcome.succeeded == 1


@pytest.mark.parametrize(
    ("collector", "sources"),
    [
        (RSSCollector(), [_rss("items"), _rss("down")]),
        (WebPageCollector(), [_web("items"), _web("down")]),
    ],
)
def test_multi_source_collection_outcome_keeps_partial_candidates(
    monkeypatch: pytest.MonkeyPatch,
    collector,
    sources,
) -> None:
    def collect_source(source, *args):
        if source.name == "down":
            raise RuntimeError("down")
        return [_candidate("kept")]

    monkeypatch.setattr(collector, "_collect_source", collect_source)

    outcome = collector.collect_with_health(sources, 36, now=NOW)

    assert outcome.candidates == [_candidate("kept")]
    assert outcome.attempted == 2
    assert outcome.succeeded == 1


class _GitHubResponse:
    def __init__(self, query: str) -> None:
        self.query = query

    def raise_for_status(self) -> None:
        if "down" in self.query:
            raise requests.ConnectionError("down")

    def json(self) -> dict[str, list[dict[str, object]]]:
        return {"items": []}


def test_github_collection_outcome_counts_queries_and_successful_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_news_bot.collectors.requests.get",
        lambda *args, **kwargs: _GitHubResponse(kwargs["params"]["q"]),
    )
    config = GitHubSources(
        queries=[
            GitHubQuery(name="ok", query="ok created:>{since}"),
            GitHubQuery(name="down", query="down created:>{since}"),
        ]
    )

    outcome = GitHubCollector().collect_with_health(config, now=NOW)

    assert outcome.candidates == []
    assert outcome.attempted == 2
    assert outcome.succeeded == 1


def test_disabled_or_unconfigured_collectors_attempt_nothing() -> None:
    assert RSSCollector().collect_with_health([], 36, now=NOW).attempted == 0
    assert WebPageCollector().collect_with_health([], 36, now=NOW).attempted == 0
    assert (
        GitHubCollector()
        .collect_with_health(GitHubSources(enabled=False), now=NOW)
        .attempted
        == 0
    )
