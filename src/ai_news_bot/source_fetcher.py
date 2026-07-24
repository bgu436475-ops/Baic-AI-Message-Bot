from __future__ import annotations

import http.client
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from ipaddress import ip_address
from typing import Any, Callable, Literal, Protocol
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

from .models import Candidate


RESPONSE_CHUNK_BYTES = 64 * 1024
SENSITIVE_QUERY_PARAMETERS = frozenset(
    {
        "token",
        "accesstoken",
        "apikey",
        "key",
        "signature",
        "sig",
        "secret",
        "auth",
        "authorization",
        "xamzsignature",
        "xgoogsignature",
        "credential",
        "securitytoken",
        "sessiontoken",
        "password",
        "clientsecret",
        "accesskey",
        "awsaccesskey",
        "awsaccesskeyid",
        "awssecretaccesskey",
        "awssecuritytoken",
        "awssessiontoken",
        "xamzcredential",
        "xamzsecuritytoken",
        "gcpcredential",
        "gcpsecuritytoken",
        "googleaccesstoken",
        "gcpaccesstoken",
        "googcredential",
        "googsecuritytoken",
        "xgoogcredential",
        "xgoogsecuritytoken",
    }
)
# Only known secret-bearing keys are redacted so arbitrary evidence URL parameters remain usable.
_PATH_TOKEN = re.compile(
    r"(?i)(?:"
    r"sk-[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}"
    r")"
)


class AllSourcesUnavailableError(RuntimeError):
    pass


class UnsafeSourceUrlError(ValueError):
    pass


Resolver = Callable[[str, int], list[str]]
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
REQUEST_PATH_SAFE = "/:@!$&'()*+,;=-._~%"
REQUEST_QUERY_SAFE = "/?:@!$&'()*+,;=-._~%"


@dataclass(frozen=True)
class ValidatedSourceTarget:
    url: str
    hostname: str
    ip_address: str
    port: int
    request_target: str
    host_header: str


class SourceResponse(Protocol):
    status_code: int
    headers: dict[str, str]

    def iter_content(self, *, chunk_size: int) -> Any: ...

    def raise_for_status(self) -> None: ...

    def close(self) -> None: ...


class SourceTransport(Protocol):
    def get(
        self,
        target: ValidatedSourceTarget,
        *,
        timeout: int,
        headers: dict[str, str],
    ) -> SourceResponse: ...


def _resolve_public_addresses(hostname: str, port: int) -> list[str]:
    return sorted(
        {
            str(sockaddr[0])
            for _family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        }
    )


def _validated_public_https_url(
    url: str,
    resolver: Resolver,
) -> ValidatedSourceTarget:
    if url != url.strip() or any(
        ord(character) < 32 or ord(character) == 127 for character in url
    ):
        raise UnsafeSourceUrlError("source URL contains unsafe whitespace")
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
        hostname = parsed.hostname
    except ValueError as error:
        raise UnsafeSourceUrlError("source URL is malformed") from error
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or hostname.casefold() == "localhost"
    ):
        raise UnsafeSourceUrlError("source URL must be public HTTPS")
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
        literal = ip_address(ascii_hostname.strip("[]"))
    except ValueError:
        literal = None
    except UnicodeError as error:
        raise UnsafeSourceUrlError("source hostname is malformed") from error
    try:
        addresses = [str(literal)] if literal is not None else resolver(ascii_hostname, port)
    except (OSError, socket.gaierror) as error:
        raise UnsafeSourceUrlError("source hostname could not be resolved") from error
    if not addresses:
        raise UnsafeSourceUrlError("source hostname has no addresses")
    try:
        normalized_addresses = sorted(
            {str(ip_address(address)) for address in addresses}
        )
        if any(
            not ip_address(address).is_global
            for address in normalized_addresses
        ):
            raise UnsafeSourceUrlError("source hostname resolves outside the public Internet")
    except ValueError as error:
        raise UnsafeSourceUrlError("resolver returned an invalid address") from error
    try:
        request_target = quote(
            parsed.path or "/",
            safe=REQUEST_PATH_SAFE,
        )
        if parsed.query:
            request_target = (
                f"{request_target}?"
                f"{quote(parsed.query, safe=REQUEST_QUERY_SAFE)}"
            )
    except UnicodeError as error:
        raise UnsafeSourceUrlError("source request target is malformed") from error
    bracketed_hostname = (
        f"[{ascii_hostname}]" if ":" in ascii_hostname else ascii_hostname
    )
    host_header = (
        bracketed_hostname
        if port == 443
        else f"{bracketed_hostname}:{port}"
    )
    return ValidatedSourceTarget(
        url=url,
        hostname=ascii_hostname,
        ip_address=normalized_addresses[0],
        port=port,
        request_target=request_target,
        host_header=host_header,
    )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        *,
        server_hostname: str,
        ip_address: str,
        port: int,
        timeout: int,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(
            server_hostname,
            port=port,
            timeout=timeout,
            context=context,
        )
        self._pinned_ip_address = ip_address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_ip_address, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except Exception:
            raw_socket.close()
            raise


class _PinnedHTTPResponse:
    def __init__(
        self,
        response: http.client.HTTPResponse,
        connection: http.client.HTTPSConnection,
    ) -> None:
        self._response = response
        self._connection = connection
        self.status_code = response.status
        self.headers = {
            name.casefold(): value
            for name, value in response.getheaders()
        }

    def iter_content(self, *, chunk_size: int) -> Any:
        while True:
            chunk = self._response.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()


ConnectionFactory = Callable[
    [ValidatedSourceTarget, int, ssl.SSLContext],
    http.client.HTTPSConnection,
]


class PinnedHTTPSTransport:
    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._connection_factory = (
            connection_factory or self._create_connection
        )
        self._ssl_context = ssl_context or ssl.create_default_context()

    @staticmethod
    def _create_connection(
        target: ValidatedSourceTarget,
        timeout: int,
        context: ssl.SSLContext,
    ) -> http.client.HTTPSConnection:
        return _PinnedHTTPSConnection(
            server_hostname=target.hostname,
            ip_address=target.ip_address,
            port=target.port,
            timeout=timeout,
            context=context,
        )

    def get(
        self,
        target: ValidatedSourceTarget,
        *,
        timeout: int,
        headers: dict[str, str],
    ) -> SourceResponse:
        connection = self._connection_factory(
            target,
            timeout,
            self._ssl_context,
        )
        request_headers = {
            **headers,
            "Host": target.host_header,
            "Accept-Encoding": "identity",
        }
        try:
            connection.request(
                "GET",
                target.request_target,
                headers=request_headers,
            )
            response = connection.getresponse()
        except Exception:
            connection.close()
            raise
        return _PinnedHTTPResponse(response, connection)


class _SessionTransport:
    def __init__(self, session: requests.Session) -> None:
        self.session = session

    def get(
        self,
        target: ValidatedSourceTarget,
        *,
        timeout: int,
        headers: dict[str, str],
    ) -> SourceResponse:
        return self.session.get(
            target.url,
            timeout=timeout,
            headers=headers,
            stream=True,
            allow_redirects=False,
        )


class FetchedSource(BaseModel):
    candidate_id: str
    requested_url: str
    final_url: str
    status: Literal["verified", "unavailable", "blocked", "insufficient"]
    status_code: int | None = None
    title: str = ""
    text: str = ""
    truncated: bool = False
    fetched_at: datetime
    error: str = ""


class SourceFetcher:
    def __init__(
        self,
        session: requests.Session | None = None,
        transport: SourceTransport | None = None,
        timeout: int = 20,
        max_chars: int = 80_000,
        max_response_bytes: int = 1_000_000,
        max_redirects: int = 5,
        resolver: Resolver | None = None,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        if session is not None and transport is not None:
            raise ValueError("session and transport are mutually exclusive")
        self.session = session
        self.transport = (
            transport
            if transport is not None
            else (
                _SessionTransport(session)
                if session is not None
                else PinnedHTTPSTransport()
            )
        )
        self.timeout = timeout
        self.max_chars = max_chars
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver or getattr(
            session or self.transport,
            "resolve",
            _resolve_public_addresses,
        )
        self._drop_session_credentials()

    def _drop_session_credentials(self) -> None:
        if self.session is None:
            return
        if hasattr(self.session, "auth"):
            self.session.auth = None
        if hasattr(self.session, "trust_env"):
            self.session.trust_env = False
        headers = getattr(self.session, "headers", None)
        if headers is not None:
            headers.pop("Authorization", None)
            headers.pop("Cookie", None)
        cookies = getattr(self.session, "cookies", None)
        if cookies is not None:
            try:
                cookies.clear()
            except (AttributeError, KeyError):
                pass

    def _get(self, target: ValidatedSourceTarget) -> SourceResponse:
        self._drop_session_credentials()
        return self.transport.get(
            target,
            timeout=self.timeout,
            headers={"User-Agent": "AI-News-Bot/0.2 (+evidence verification)"},
        )

    def _request_following_redirects(
        self,
        initial_url: str,
    ) -> tuple[SourceResponse, str]:
        current_url = initial_url
        visited: set[str] = set()
        for hop in range(self.max_redirects + 1):
            if current_url in visited:
                raise UnsafeSourceUrlError("redirect loop")
            visited.add(current_url)
            target = _validated_public_https_url(current_url, self.resolver)
            response = self._get(target)
            if response.status_code not in REDIRECT_STATUSES:
                return response, current_url
            try:
                location = response.headers.get("location", "").strip()
                if not location:
                    raise UnsafeSourceUrlError("redirect has no location")
                next_url = urljoin(current_url, location)
                if next_url in visited:
                    raise UnsafeSourceUrlError("redirect loop")
                if hop >= self.max_redirects:
                    raise UnsafeSourceUrlError("too many redirects")
                current_url = next_url
            finally:
                try:
                    response.close()
                except Exception:
                    pass
        raise UnsafeSourceUrlError("too many redirects")

    def _read_response_body(self, response: SourceResponse) -> tuple[bytes, bool]:
        body = bytearray()
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
            if not chunk:
                continue
            remaining = self.max_response_bytes + 1 - len(body)
            body.extend(chunk[:remaining])
            if len(body) > self.max_response_bytes:
                del body[self.max_response_bytes :]
                return bytes(body), True
        return bytes(body), False

    def fetch_one(self, candidate: Candidate) -> FetchedSource:
        now = datetime.now(UTC)
        response_url = candidate.url
        status_code: int | None = None
        response: SourceResponse | None = None
        try:
            response, response_url = self._request_following_redirects(candidate.url)
            status = response.status_code
            status_code = status
            if status in {401, 403, 429}:
                return FetchedSource(
                    candidate_id=candidate.id,
                    requested_url=_sanitize_url(candidate.url),
                    final_url=_sanitize_url(response_url),
                    status="blocked",
                    status_code=status,
                    fetched_at=now,
                    error=f"HTTP {status}",
                )
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", "text/html").lower():
                raise ValueError("unsupported content type")
            body, truncated = self._read_response_body(response)
            soup = BeautifulSoup(body, "html.parser")
            for node in soup(["script", "style", "nav", "footer", "noscript"]):
                node.decompose()
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            text = "\n".join(
                part.strip() for part in soup.get_text("\n").splitlines() if part.strip()
            )[: self.max_chars]
            state = "verified" if not truncated and len(text) >= 80 else "insufficient"
            return FetchedSource(
                candidate_id=candidate.id,
                requested_url=_sanitize_url(candidate.url),
                final_url=_sanitize_url(response_url),
                status=state,
                status_code=status,
                title=title,
                text=text,
                truncated=truncated,
                fetched_at=now,
            )
        except (
            requests.RequestException,
            http.client.HTTPException,
            ValueError,
            OSError,
        ) as error:
            return FetchedSource(
                candidate_id=candidate.id,
                requested_url=_sanitize_url(candidate.url),
                final_url=_sanitize_url(response_url),
                status="unavailable",
                status_code=status_code,
                fetched_at=now,
                error=type(error).__name__,
            )
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    def fetch_many(self, candidates: list[Candidate]) -> list[FetchedSource]:
        results = [self.fetch_one(candidate) for candidate in candidates]
        if results and all(item.status != "verified" for item in results):
            raise AllSourcesUnavailableError("all shortlisted original sources failed")
        return results


def _sanitize_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        query = urlencode(
            [
                (
                    name,
                    "REDACTED"
                    if _normalize_parameter_name(name) in SENSITIVE_QUERY_PARAMETERS
                    else value,
                )
                for name, value in parse_qsl(parsed.query, keep_blank_values=True)
            ]
        )
        netloc = parsed.netloc.rsplit("@", maxsplit=1)[-1]
        return urlunsplit(
            (
                parsed.scheme,
                netloc,
                _sanitize_path(parsed.path),
                query,
                "",
            )
        )
    except Exception:
        return f"invalid-url:{sha256(url.encode('utf-8', 'surrogatepass')).hexdigest()[:12]}"


def _normalize_parameter_name(name: str) -> str:
    return name.casefold().replace("-", "").replace("_", "")


def _sanitize_path(path: str) -> str:
    segments = path.split("/")
    redact_next = False
    sanitized: list[str] = []
    for raw_segment in segments:
        decoded = unquote(raw_segment)
        if redact_next:
            sanitized.append("REDACTED")
            redact_next = False
            continue
        assignment = re.fullmatch(r"([^=:]+)([:=])(.*)", decoded)
        if (
            assignment is not None
            and _normalize_parameter_name(assignment.group(1))
            in SENSITIVE_QUERY_PARAMETERS
        ):
            sanitized.append(
                f"{assignment.group(1)}{assignment.group(2)}REDACTED"
            )
            continue
        normalized = _normalize_parameter_name(decoded)
        sanitized.append(
            "REDACTED"
            if _PATH_TOKEN.search(decoded)
            else raw_segment
        )
        redact_next = normalized in SENSITIVE_QUERY_PARAMETERS
    return "/".join(sanitized)
