from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from typing import Any, Callable

from openai import OpenAI

from ai_news_bot.config import Settings
from ai_news_bot.evidence import extract_evidence
from ai_news_bot.model_backend import create_model_client
from ai_news_bot.models import Candidate, EvidenceRecord
from ai_news_bot.source_fetcher import FetchedSource


SMOKE_CANDIDATE_ID = "cloudflare-smoke-test"
SMOKE_STATEMENT = "Cloudflare smoke model v1 is available now."


def _safe_error_diagnostics(error: Exception) -> dict[str, str | int]:
    diagnostics: dict[str, str | int] = {
        "error_class": type(error).__name__,
    }
    cause = error.__cause__ or error.__context__
    if cause is None:
        return diagnostics
    diagnostics["cause_class"] = type(cause).__name__
    status_code = getattr(cause, "status_code", None)
    if isinstance(status_code, int) and 100 <= status_code <= 599:
        diagnostics["http_status"] = status_code
    api_error_code = getattr(cause, "code", None)
    if isinstance(api_error_code, int):
        diagnostics["api_error_code"] = api_error_code
    elif isinstance(api_error_code, str) and re.fullmatch(
        r"[A-Za-z0-9_.-]{1,64}", api_error_code
    ):
        diagnostics["api_error_code"] = api_error_code
    return diagnostics


def validate_backend(
    settings: Settings,
    client_factory: Callable[..., Any] = OpenAI,
) -> EvidenceRecord:
    backend = settings.ai_backend()
    client = create_model_client(
        backend,
        client_factory=client_factory,
        max_retries=0,
    )
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
    record = extract_evidence(
        candidate,
        source,
        client,
        backend,
        max_attempts=1,
    )
    if (
        record.candidate_id != SMOKE_CANDIDATE_ID
        or record.verification_status != "verified"
        or not record.concrete_changes
        or not record.evidence_anchors
    ):
        raise RuntimeError("AI backend smoke validation returned invalid evidence")
    return record


def main() -> int:
    provider = "unavailable"
    model = "unavailable"
    try:
        settings = Settings.from_env()
        backend = settings.ai_backend()
        model = backend.model
        provider = backend.provider_label
        validate_backend(settings)
    except Exception as error:
        diagnostics = _safe_error_diagnostics(error)
        print(
            json.dumps(
                {
                    "provider": provider,
                    "model": model,
                    "success": False,
                    **diagnostics,
                }
            ),
            file=sys.stderr,
        )
        return 1
    print(f"provider={provider} model={model} success=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
