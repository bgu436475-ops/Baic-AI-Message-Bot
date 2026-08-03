from types import SimpleNamespace
from typing import Any

import pytest

from ai_news_bot.config import Settings
from ai_news_bot.evidence import EvidenceExtractionError
from ai_news_bot.models import ChangeFact, EvidenceAnchor, EvidenceRecord


def _smoke_record() -> EvidenceRecord:
    return EvidenceRecord(
        candidate_id="cloudflare-smoke-test",
        title_zh="Cloudflare 烟雾测试模型已验证",
        summary_zh="Cloudflare 烟雾测试已确认结构化证据提取可用。",
        category="ai_coding",
        source_url="https://example.test/cloudflare-smoke",
        source_type="official_announcement",
        verification_status="verified",
        concrete_changes=[
            ChangeFact(
                change_type="release",
                statement="Cloudflare smoke model v1 is available now.",
                numbers=["v1"],
                entities=["Cloudflare smoke model"],
            )
        ],
        evidence_anchors=[
            EvidenceAnchor(
                quote="Cloudflare smoke model v1 is available now.",
                locator="smoke statement",
            )
        ],
        affected_audience=["API developers"],
        affected_area=["structured extraction"],
        recommended_action=["Validate the provider connection"],
        event_entities=["Cloudflare"],
        primary_entity="Cloudflare",
        product_or_model="smoke model",
        change_signature="cloudflare-smoke-model-v1",
        version_or_metric="v1",
        relevance_signal="direct",
        action_horizon_days=0,
        resource_available=True,
    )


def test_validate_backend_uses_cloudflare_client_and_verified_anchor() -> None:
    from scripts.validate_ai_backend import validate_backend

    captured: dict[str, str | None] = {}
    calls = 0

    def fake_factory(**kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        captured.update(kwargs)

        def parse(**_request: Any) -> SimpleNamespace:
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=_smoke_record()))]
            )

        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    parse=parse
                )
            )
        )

    settings = Settings(
        cloudflare_account_id="account-123",
        cloudflare_ai_api_token="cf-token",
    )

    record = validate_backend(settings, client_factory=fake_factory)

    assert record.candidate_id == "cloudflare-smoke-test"
    assert record.verification_status == "verified"
    assert captured == {
        "api_key": "cf-token",
        "base_url": (
            "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1"
        ),
        "max_retries": 0,
    }
    assert calls == 1


def test_validate_backend_never_retries_a_model_parse_failure() -> None:
    from scripts.validate_ai_backend import validate_backend

    calls = 0

    def fake_factory(**_kwargs: Any) -> SimpleNamespace:
        def parse(**_request: Any) -> SimpleNamespace:
            nonlocal calls
            calls += 1
            raise ValueError("invalid structured response")

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
        )

    settings = Settings(
        cloudflare_account_id="account-123",
        cloudflare_ai_api_token="cf-token",
    )

    with pytest.raises(EvidenceExtractionError):
        validate_backend(settings, client_factory=fake_factory)

    assert calls == 1
