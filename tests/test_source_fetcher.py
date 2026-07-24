from datetime import UTC, datetime

import pytest
import requests

from ai_news_bot.models import Candidate
from ai_news_bot.source_fetcher import AllSourcesUnavailableError, SourceFetcher


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


class FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        text: str,
        status_code: int = 200,
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        self.url = url
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse | requests.RequestException]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, int, dict[str, str]]] = []

    def get(self, url: str, *, timeout: int, headers: dict[str, str]) -> FakeResponse:
        self.calls.append((url, timeout, headers))
        result = next(self.responses)
        if isinstance(result, requests.RequestException):
            raise result
        return result


def candidate(identifier: str) -> Candidate:
    return Candidate(
        id=identifier,
        title=f"Model {identifier}",
        url=f"https://example.test/{identifier}",
        source="Test source",
        source_tier=1,
        source_weight=1.0,
        published_at=NOW,
    )


def one() -> Candidate:
    return candidate("one")


def two() -> Candidate:
    return candidate("two")


def test_fetch_sources_cleans_html_before_verification() -> None:
    session = FakeSession(
        [
            FakeResponse(
                url="https://example.test/one",
                text="""
                    <html><head><title>Model X announcement</title><style>.ad {}</style></head>
                    <body><nav>Navigation</nav><h1>Model X v2</h1>
                    <p>Input price is $1 per million tokens.</p><script>alert('ad')</script>
                    <p>The new pricing takes effect today for all API customers worldwide.</p>
                    <footer>Footer</footer></body></html>
                """,
            )
        ]
    )

    result = SourceFetcher(session=session, timeout=5).fetch_many([one()])

    assert result[0].status == "verified"
    assert result[0].title == "Model X announcement"
    assert "Input price is $1 per million tokens." in result[0].text
    assert "Navigation" not in result[0].text
    assert "alert" not in result[0].text


def test_fetch_sources_retains_final_redirect_url() -> None:
    session = FakeSession(
        [
            FakeResponse(
                url="https://example.com/final",
                text="<h1>Model X v2</h1><p>Input price is $1 per million tokens.</p>" * 2,
            )
        ]
    )

    result = SourceFetcher(session=session, timeout=5).fetch_many([one()])

    assert result[0].requested_url == "https://example.test/one"
    assert result[0].final_url == "https://example.com/final"


def test_fetch_sources_keeps_success_when_another_source_times_out() -> None:
    session = FakeSession(
        [
            requests.Timeout("slow"),
            FakeResponse(
                url="https://example.com/final",
                text="<h1>Model X v2</h1><p>Input price is $1 per million tokens.</p>" * 2,
            ),
        ]
    )

    result = SourceFetcher(session=session, timeout=5).fetch_many([one(), two()])

    assert [item.status for item in result] == ["unavailable", "verified"]
    assert "Input price is $1" in result[1].text
    assert result[1].final_url == "https://example.com/final"


def test_fetch_sources_raises_when_every_original_is_unavailable() -> None:
    session = FakeSession([requests.Timeout("slow"), requests.ConnectionError("down")])

    with pytest.raises(AllSourcesUnavailableError):
        SourceFetcher(session=session, timeout=5).fetch_many([one(), two()])
