from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


class AllSourcesUnavailableError(RuntimeError):
    pass


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
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_chars = max_chars
        self.max_response_bytes = max_response_bytes

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
            response = self.session.get(
                candidate.url,
                timeout=self.timeout,
                headers={"User-Agent": "AI-News-Bot/0.2 (+evidence verification)"},
                stream=True,
            )
            response_url = response.url
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
        except (requests.RequestException, ValueError) as error:
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
                response.close()

    def fetch_many(self, candidates: list[Candidate]) -> list[FetchedSource]:
        results = [self.fetch_one(candidate) for candidate in candidates]
        if results and all(item.status != "verified" for item in results):
            raise AllSourcesUnavailableError("all shortlisted original sources failed")
        return results


def _sanitize_url(url: str) -> str:
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
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))


def _normalize_parameter_name(name: str) -> str:
    return name.casefold().replace("-", "").replace("_", "")
