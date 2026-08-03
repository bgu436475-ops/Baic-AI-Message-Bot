from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from openai import OpenAI

from ai_news_bot.config import Settings
from ai_news_bot.evidence import extract_evidence
from ai_news_bot.models import Candidate, EvidenceRecord
from ai_news_bot.source_fetcher import FetchedSource


SMOKE_CANDIDATE_ID = "cloudflare-smoke-test"
SMOKE_STATEMENT = "Cloudflare smoke model v1 is available now."


def validate_backend(
    settings: Settings,
    client_factory: Callable[..., Any] = OpenAI,
) -> EvidenceRecord:
    api_key, model, base_url, _provider = settings.ai_backend()
    client = client_factory(api_key=api_key, base_url=base_url)
    now = datetime.now(UTC)
    candidate = Candidate(
        id=SMOKE_CANDIDATE_ID,
        title="Cloudflare structured AI smoke test",
        summary=SMOKE_STATEMENT,
        url="https://example.test/cloudflare-smoke",
        source="AI news bot smoke test",
        source_tier=1,
        source_weight=1.0,
        published_at=now,
    )
    source = FetchedSource(
        candidate_id=SMOKE_CANDIDATE_ID,
        requested_url=candidate.url,
        final_url=candidate.url,
        status="verified",
        status_code=200,
        title=candidate.title,
        text=SMOKE_STATEMENT,
        fetched_at=now,
    )
    record = extract_evidence(candidate, source, client, model, base_url=base_url)
    if (
        record.candidate_id != SMOKE_CANDIDATE_ID
        or record.verification_status != "verified"
        or not record.concrete_changes
        or not record.evidence_anchors
    ):
        raise RuntimeError("AI backend smoke validation returned invalid evidence")
    return record


def main() -> int:
    settings = Settings.from_env()
    _api_key, model, _base_url, provider = settings.ai_backend()
    validate_backend(settings)
    print(f"provider={provider} model={model} success=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
