from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from .models import Candidate


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
    fetched_at: datetime
    error: str = ""


class SourceFetcher:
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 20,
        max_chars: int = 80_000,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_chars = max_chars

    def fetch_one(self, candidate: Candidate) -> FetchedSource:
        now = datetime.now(UTC)
        try:
            response = self.session.get(
                candidate.url,
                timeout=self.timeout,
                headers={"User-Agent": "AI-News-Bot/0.2 (+evidence verification)"},
            )
            status = response.status_code
            if status in {401, 403, 429}:
                return FetchedSource(
                    candidate_id=candidate.id,
                    requested_url=candidate.url,
                    final_url=response.url,
                    status="blocked",
                    status_code=status,
                    fetched_at=now,
                    error=f"HTTP {status}",
                )
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", "text/html").lower():
                raise ValueError("unsupported content type")
            soup = BeautifulSoup(response.text, "html.parser")
            for node in soup(["script", "style", "nav", "footer", "noscript"]):
                node.decompose()
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            text = "\n".join(
                part.strip() for part in soup.get_text("\n").splitlines() if part.strip()
            )[: self.max_chars]
            state = "verified" if len(text) >= 80 else "insufficient"
            return FetchedSource(
                candidate_id=candidate.id,
                requested_url=candidate.url,
                final_url=response.url,
                status=state,
                status_code=status,
                title=title,
                text=text,
                fetched_at=now,
            )
        except (requests.RequestException, ValueError) as error:
            return FetchedSource(
                candidate_id=candidate.id,
                requested_url=candidate.url,
                final_url=candidate.url,
                status="unavailable",
                fetched_at=now,
                error=type(error).__name__,
            )

    def fetch_many(self, candidates: list[Candidate]) -> list[FetchedSource]:
        results = [self.fetch_one(candidate) for candidate in candidates]
        if results and all(item.status != "verified" for item in results):
            raise AllSourcesUnavailableError("all shortlisted original sources failed")
        return results
