from datetime import UTC, datetime
from hashlib import sha256

import pytest
import requests

from ai_news_bot.models import Candidate
from ai_news_bot.source_fetcher import (
    AllSourcesUnavailableError,
    SourceFetcher,
    _sanitize_url,
)


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


class FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        text: str,
        status_code: int = 200,
        content_type: str = "text/html; charset=utf-8",
        iter_content_error: requests.RequestException | None = None,
        close_error: Exception | None = None,
        location: str | None = None,
    ) -> None:
        self.url = url
        self._body = text.encode()
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        if location is not None:
            self.headers["location"] = location
        self.bytes_yielded = 0
        self.iter_content_chunk_sizes: list[int] = []
        self.iter_content_error = iter_content_error
        self.close_error = close_error
        self.closed = False
        self.close_calls = 0

    @property
    def text(self) -> str:
        raise AssertionError("SourceFetcher must read bounded response bytes, not response.text")

    def iter_content(self, *, chunk_size: int) -> object:
        self.iter_content_chunk_sizes.append(chunk_size)
        if self.iter_content_error:
            raise self.iter_content_error
        for index in range(0, len(self._body), chunk_size):
            chunk = self._body[index : index + chunk_size]
            self.bytes_yielded += len(chunk)
            yield chunk

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error:
            raise self.close_error
        self.closed = True

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse | requests.RequestException]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, int, dict[str, str], bool]] = []

    @staticmethod
    def resolve(hostname: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    def get(
        self,
        url: str,
        *,
        timeout: int,
        headers: dict[str, str],
        stream: bool,
        allow_redirects: bool = True,
    ) -> FakeResponse:
        self.calls.append((url, timeout, headers, stream))
        result = next(self.responses)
        if isinstance(result, requests.RequestException):
            raise result
        return result


def resolver(mapping: dict[str, list[str]]):
    def resolve(hostname: str, port: int) -> list[str]:
        return mapping.get(hostname, ["93.184.216.34"])

    return resolve


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
                url="https://example.test/one",
                text="",
                status_code=302,
                location="https://example.com/final",
            ),
            FakeResponse(
                url="https://example.com/final",
                text="<h1>Model X v2</h1><p>Input price is $1 per million tokens.</p>" * 2,
            )
        ]
    )

    result = SourceFetcher(session=session, timeout=5).fetch_many([one()])

    assert result[0].requested_url == "https://example.test/one"
    assert result[0].final_url == "https://example.com/final"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/news",
        "https://user:password@example.com/news",
        "https://127.0.0.1/news",
        "https://[::1]/news",
        "https://169.254.169.254/latest/meta-data",
        "https://0.0.0.0/news",
    ],
)
def test_fetch_rejects_non_public_initial_urls_before_request(url: str) -> None:
    session = FakeSession([])

    result = SourceFetcher(session=session).fetch_one(candidate("unsafe", url=url))

    assert result.status == "unavailable"
    assert result.error == "UnsafeSourceUrlError"
    assert session.calls == []


def test_fetch_rejects_hostname_that_resolves_to_private_address() -> None:
    session = FakeSession([])

    result = SourceFetcher(
        session=session,
        resolver=resolver({"example.test": ["10.0.0.7"]}),
    ).fetch_one(one())

    assert result.status == "unavailable"
    assert result.error == "UnsafeSourceUrlError"
    assert session.calls == []


@pytest.mark.parametrize(
    "location",
    [
        "https://127.0.0.1/private",
        "https://localhost/private",
        "http://example.test/insecure",
    ],
)
def test_fetch_rejects_unsafe_redirect_before_following(location: str) -> None:
    session = FakeSession([
        FakeResponse(
            url="https://example.test/one",
            text="",
            status_code=302,
            location=location,
        ),
    ])

    result = SourceFetcher(session=session).fetch_one(one())

    assert result.status == "unavailable"
    assert result.error == "UnsafeSourceUrlError"
    assert len(session.calls) == 1


def test_fetch_follows_relative_public_redirect_without_forwarding_credentials() -> None:
    session = FakeSession([
        FakeResponse(
            url="https://example.test/start",
            text="",
            status_code=302,
            location="/release",
        ),
        FakeResponse(
            url="https://example.test/release",
            text="<h1>Release</h1><p>API v2 costs $1 per million tokens.</p>" * 3,
        ),
    ])

    result = SourceFetcher(session=session).fetch_one(
        candidate("redirect", url="https://example.test/start")
    )

    assert result.status == "verified"
    assert [call[0] for call in session.calls] == [
        "https://example.test/start",
        "https://example.test/release",
    ]
    assert all("Authorization" not in call[2] and "Cookie" not in call[2] for call in session.calls)


def test_fetcher_disables_session_credentials_cookies_and_environment_auth() -> None:
    session = FakeSession([
        FakeResponse(
            url="https://example.test/one",
            text="x" * 100,
        ),
    ])

    class Cookies:
        def __init__(self) -> None:
            self.clear_calls = 0

        def clear(self) -> None:
            self.clear_calls += 1

    session.auth = ("user", "password")
    session.trust_env = True
    session.headers = {
        "Authorization": "Bearer inherited",
        "Cookie": "session=inherited",
    }
    session.cookies = Cookies()

    result = SourceFetcher(session=session).fetch_one(one())

    assert result.status == "verified"
    assert session.auth is None
    assert session.trust_env is False
    assert session.cookies.clear_calls >= 1
    assert "Authorization" not in session.headers
    assert "Cookie" not in session.headers


def test_fetch_rejects_redirect_loop() -> None:
    session = FakeSession([
        FakeResponse(
            url="https://example.test/one",
            text="",
            status_code=302,
            location="/two",
        ),
        FakeResponse(
            url="https://example.test/two",
            text="",
            status_code=302,
            location="/one",
        ),
    ])

    result = SourceFetcher(session=session).fetch_one(one())

    assert result.status == "unavailable"
    assert result.error == "UnsafeSourceUrlError"
    assert len(session.calls) == 2


def test_fetch_rejects_too_many_redirect_hops() -> None:
    session = FakeSession([
        FakeResponse(
            url=f"https://example.test/{index}",
            text="",
            status_code=302,
            location=f"/{index + 1}",
        )
        for index in range(7)
    ])

    result = SourceFetcher(session=session, max_redirects=5).fetch_one(
        candidate("redirects", url="https://example.test/0")
    )

    assert result.status == "unavailable"
    assert result.error == "UnsafeSourceUrlError"
    assert len(session.calls) == 6


def test_fetch_sources_keeps_success_when_another_source_times_out() -> None:
    session = FakeSession(
        [
            requests.Timeout("slow"),
            FakeResponse(
                url="https://example.test/two",
                text="",
                status_code=302,
                location="https://example.com/final",
            ),
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
                url="https://example.test/one",
                text="",
                status_code=302,
                location="https://example.com/final?visible=keep#fragment",
            ),
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
        text="<p>" + "Long original source text. " * 5_000 + "</p>",
    )
    session = FakeSession([response])

    result = SourceFetcher(session=session, max_response_bytes=100, max_chars=20).fetch_one(one())

    assert session.calls[0][3] is True
    assert response.bytes_yielded == 64 * 1024
    assert response.bytes_yielded <= 100 + 64 * 1024
    assert response.iter_content_chunk_sizes == [64 * 1024]
    assert result.truncated is True
    assert result.status == "insufficient"
    assert len(result.text) == 20


def test_fetch_sources_does_not_mark_an_exact_byte_limit_at_eof_as_truncated() -> None:
    response = FakeResponse(url="https://example.test/one", text="x" * 100)
    session = FakeSession([response])

    result = SourceFetcher(session=session, max_response_bytes=100).fetch_one(one())

    assert response.bytes_yielded == 100
    assert response.iter_content_chunk_sizes == [64 * 1024]
    assert result.truncated is False
    assert result.status == "verified"


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


def test_fetch_sources_redacts_presigned_credentials_and_sensitive_query_values() -> None:
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
        "aws-credential",
        "aws-security-token",
        "aws-access-key",
        "aws-secret-key",
        "aws-session-token",
        "gcp-credential",
        "gcp-security-token",
        "password-value",
        "client-secret-value",
        "access-key-value",
    ]
    requested_url = (
        "https://example.test/one?token=client-token"
        "&visible=keep&X-Amz-Signature=client-signature&aws_access_key_id=aws-access-key"
        "&aws-secret-access-key=aws-secret-key&AWS-SESSION-TOKEN=aws-session-token"
        "&Password=password-value&client-secret=client-secret-value"
        "&access_key=access-key-value#requested-fragment"
    )
    final_url = (
        "https://example.com/final?access_token=access-secret&api_key=api-secret"
        "&key=key-secret&signature=signature-secret&sig=sig-secret&secret=secret-value"
        "&auth=auth-value&authorization=authorization-value"
        "&X-Goog-Signature=goog-secret&X-Amz-Credential=aws-credential"
        "&X-Amz-Security-Token=aws-security-token&x_goog_credential=gcp-credential"
        "&X_GOOG_SECURITY_TOKEN=gcp-security-token&visible=final#response-fragment"
    )
    session = FakeSession([
        FakeResponse(
            url=requested_url,
            text="",
            status_code=302,
            location=final_url,
        ),
        FakeResponse(url=final_url, text="Not found", status_code=404),
    ])

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
    assert "aws_access_key_id=REDACTED" in result.requested_url
    assert "aws-secret-access-key=REDACTED" in result.requested_url
    assert "X-Amz-Credential=REDACTED" in result.final_url
    assert "X-Amz-Security-Token=REDACTED" in result.final_url
    assert "x_goog_credential=REDACTED" in result.final_url
    assert "X_GOOG_SECURITY_TOKEN=REDACTED" in result.final_url
    assert client_secret not in serialized
    assert "client-signature" not in serialized
    assert all(secret not in serialized for secret in response_secrets)
    assert "HTTPError" == result.error


@pytest.mark.parametrize(
    ("raw_url", "expected_path"),
    [
        (
            "https://example.test/hooks/access_token/path-secret/releases",
            "/hooks/access_token/REDACTED/releases",
        ),
        (
            "https://example.test/download/api_key=assignment-secret/file",
            "/download/api_key=REDACTED/file",
        ),
        (
            "https://example.test/artifacts/"
            "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890/file",
            "/artifacts/REDACTED/file",
        ),
    ],
)
def test_url_sanitizer_redacts_path_carried_credentials(
    raw_url: str,
    expected_path: str,
) -> None:
    sanitized = _sanitize_url(raw_url)

    assert sanitized == f"https://example.test{expected_path}"
    assert "path-secret" not in sanitized
    assert "assignment-secret" not in sanitized
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890" not in sanitized


@pytest.mark.parametrize(
    ("response", "fetcher_kwargs", "expected_status"),
    [
        (FakeResponse(url="https://example.test/blocked", text="", status_code=403), {}, "blocked"),
        (FakeResponse(url="https://example.test/missing", text="", status_code=404), {}, "unavailable"),
        (
            FakeResponse(
                url="https://example.test/json",
                text="{}",
                content_type="application/json",
            ),
            {},
            "unavailable",
        ),
        (
            FakeResponse(url="https://example.test/capped", text="x" * 200),
            {"max_response_bytes": 100},
            "insufficient",
        ),
        (FakeResponse(url="https://example.test/success", text="x" * 100), {}, "verified"),
    ],
)
def test_fetch_sources_closes_responses_on_every_result_path(
    response: FakeResponse, fetcher_kwargs: dict[str, int], expected_status: str
) -> None:
    result = SourceFetcher(session=FakeSession([response]), **fetcher_kwargs).fetch_one(one())

    assert result.status == expected_status
    assert response.closed is True
    assert response.close_calls == 1


def test_fetch_sources_closes_response_after_streaming_exception() -> None:
    response = FakeResponse(
        url="https://example.test/stream",
        text="x" * 100,
        iter_content_error=requests.ConnectionError("stream interrupted"),
    )

    result = SourceFetcher(session=FakeSession([response])).fetch_one(one())

    assert result.status == "unavailable"
    assert result.error == "ConnectionError"
    assert response.closed is True
    assert response.close_calls == 1


def test_fetch_sources_uses_safe_placeholder_for_malformed_url_and_continues() -> None:
    malformed_url = "https://[not-an-ipv6]/?token=malformed-secret"
    good_response = FakeResponse(url="https://example.test/two", text="x" * 100)
    session = FakeSession([good_response])

    result = SourceFetcher(session=session).fetch_many(
        [candidate("bad", url=malformed_url), two()]
    )

    expected_placeholder = f"invalid-url:{sha256(malformed_url.encode()).hexdigest()[:12]}"
    assert [item.status for item in result] == ["unavailable", "verified"]
    assert result[0].requested_url == expected_placeholder
    assert result[0].final_url == expected_placeholder
    assert "malformed-secret" not in result[0].model_dump_json()
    assert good_response.closed is True


def test_fetch_sources_continues_after_response_close_error() -> None:
    close_fails = FakeResponse(
        url="https://example.test/one",
        text="x" * 100,
        close_error=RuntimeError("close failed"),
    )
    later_success = FakeResponse(url="https://example.test/two", text="x" * 100)

    result = SourceFetcher(session=FakeSession([close_fails, later_success])).fetch_many([one(), two()])

    assert [item.status for item in result] == ["verified", "verified"]
    assert close_fails.close_calls == 1
    assert close_fails.closed is False
    assert later_success.closed is True
