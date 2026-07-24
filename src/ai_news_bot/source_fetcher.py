from __future__ import annotations

import re
import socket
from datetime import UTC, datetime
from hashlib import sha256
from ipaddress import ip_address
from typing import Callable, Literal
from urllib.parse import (
    parse_qsl,
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


def _validated_public_https_url(url: str, resolver: Resolver) -> str:
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
        if any(not ip_address(address).is_global for address in addresses):
            raise UnsafeSourceUrlError("source hostname resolves outside the public Internet")
    except ValueError as error:
        raise UnsafeSourceUrlError("resolver returned an invalid address") from error
    return url


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
        timeout: int = 20,
        max_chars: int = 80_000,
        max_response_bytes: int = 1_000_000,
        max_redirects: int = 5,
        resolver: Resolver | None = None,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_chars = max_chars
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver or getattr(
            self.session,
            "resolve",
            _resolve_public_addresses,
        )
        self._drop_session_credentials()

    def _drop_session_credentials(self) -> None:
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

    def _get(self, url: str) -> requests.Response:
        self._drop_session_credentials()
        return self.session.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": "AI-News-Bot/0.2 (+evidence verification)"},
            stream=True,
            allow_redirects=False,
        )

    def _request_following_redirects(
        self,
        initial_url: str,
    ) -> tuple[requests.Response, str]:
        current_url = initial_url
        visited: set[str] = set()
        for hop in range(self.max_redirects + 1):
            _validated_public_https_url(current_url, self.resolver)
            if current_url in visited:
                raise UnsafeSourceUrlError("redirect loop")
            visited.add(current_url)
            response = self._get(current_url)
            if response.status_code not in REDIRECT_STATUSES:
                return response, current_url
            try:
                location = response.headers.get("location", "").strip()
                if not location:
                    raise UnsafeSourceUrlError("redirect has no location")
                next_url = urljoin(current_url, location)
                _validated_public_https_url(next_url, self.resolver)
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

    def _read_response_body(self, response: requests.Response) -> tuple[bytes, bool]:
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
        response: requests.Response | None = None
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
        except (requests.RequestException, ValueError, OSError) as error:
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
