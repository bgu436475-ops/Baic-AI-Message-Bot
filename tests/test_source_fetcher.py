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
        self._body = text.encode()
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.bytes_yielded = 0
        self.iter_content_chunk_sizes: list[int] = []

    @property
    def text(self) -> str:
        raise AssertionError("SourceFetcher must read bounded response bytes, not response.text")

    def iter_content(self, *, chunk_size: int) -> object:
        self.iter_content_chunk_sizes.append(chunk_size)
        for index in range(0, len(self._body), chunk_size):
            chunk = self._body[index : index + chunk_size]
            self.bytes_yielded += len(chunk)
            yield chunk

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse | requests.RequestException]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, int, dict[str, str], bool]] = []

    def get(
        self, url: str, *, timeout: int, headers: dict[str, str], stream: bool
    ) -> FakeResponse:
        self.calls.append((url, timeout, headers, stream))
        result = next(self.responses)
        if isinstance(result, requests.RequestException):
            raise result
        return result


def candidate(identifier: str, *, url: str | None = None) -> Candidate:
    return Candidate(
        id=identifier,
        title=f"Model {identifier}",
        url=url or f"https://example.test/{identifier}",
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


@pytest.mark.parametrize("status_code", [404, 500])
def test_fetch_sources_preserves_redirect_details_for_http_errors(status_code: int) -> None:
    session = FakeSession(
        [
            FakeResponse(
                url="https://example.com/final?visible=keep#fragment",
                text="Not found",
                status_code=status_code,
            )
        ]
    )

    result = SourceFetcher(session=session, timeout=5).fetch_one(one())

    assert result.status == "unavailable"
    assert result.status_code == status_code
    assert result.final_url == "https://example.com/final?visible=keep"


def test_fetch_sources_reads_only_the_configured_raw_byte_limit() -> None:
    response = FakeResponse(
        url="https://example.test/one",
        text="<p>" + "Long original source text. " * 20 + "</p>",
    )
    session = FakeSession([response])

    result = SourceFetcher(session=session, max_response_bytes=100, max_chars=20).fetch_one(one())

    assert session.calls[0][3] is True
    assert response.bytes_yielded == 100
    assert response.iter_content_chunk_sizes == [1]
    assert result.truncated is True
    assert result.status == "insufficient"
    assert len(result.text) == 20


def test_fetch_sources_marks_short_html_as_insufficient() -> None:
    session = FakeSession([FakeResponse(url="https://example.test/one", text="<p>Short</p>")])

    result = SourceFetcher(session=session).fetch_one(one())

    assert result.status == "insufficient"
    assert result.text == "Short"


def test_fetch_sources_marks_non_html_as_unavailable() -> None:
    session = FakeSession(
        [
            FakeResponse(
                url="https://example.test/one",
                text='{"answer": 42}',
                content_type="application/json",
            )
        ]
    )

    result = SourceFetcher(session=session).fetch_one(one())

    assert result.status == "unavailable"
    assert result.status_code == 200
    assert result.error == "ValueError"


def test_fetch_sources_redacts_sensitive_query_values_and_fragments() -> None:
    client_secret = "client-token"
    response_secrets = [
        "access-secret",
        "api-secret",
        "key-secret",
        "signature-secret",
        "sig-secret",
        "secret-value",
        "auth-value",
        "authorization-value",
        "goog-secret",
    ]
    requested_url = (
        "https://example.test/one?token=client-token&visible=keep"
        "&X-Amz-Signature=client-signature#requested-fragment"
    )
    final_url = (
        "https://example.com/final?access_token=access-secret&api_key=api-secret"
        "&key=key-secret&signature=signature-secret&sig=sig-secret&secret=secret-value"
        "&auth=auth-value&authorization=authorization-value"
        "&X-Goog-Signature=goog-secret&visible=final#response-fragment"
    )
    session = FakeSession([FakeResponse(url=final_url, text="Not found", status_code=404)])

    result = SourceFetcher(session=session).fetch_one(candidate("secret", url=requested_url))

    serialized = result.model_dump_json()
    assert result.status == "unavailable"
    assert result.status_code == 404
    assert "visible=keep" in result.requested_url
    assert "visible=final" in result.final_url
    assert "#" not in result.requested_url
    assert "#" not in result.final_url
    assert "token=REDACTED" in result.requested_url
    assert "X-Amz-Signature=REDACTED" in result.requested_url
    assert "access_token=REDACTED" in result.final_url
    assert "X-Goog-Signature=REDACTED" in result.final_url
    assert client_secret not in serialized
    assert "client-signature" not in serialized
    assert all(secret not in serialized for secret in response_secrets)
