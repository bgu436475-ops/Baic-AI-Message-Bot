import json
import os
import subprocess
import sys
from pathlib import Path
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


def test_validate_backend_uses_explicit_ollama_settings() -> None:
    from scripts.validate_ai_backend import validate_backend

    captured: dict[str, Any] = {}

    def fake_factory(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)

        def parse(**request: Any) -> SimpleNamespace:
            captured["request"] = request
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=_smoke_record()))]
            )

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
        )

    record = validate_backend(
        Settings(
            ai_backend_name="ollama",
            ollama_base_url="http://127.0.0.1:11434/v1",
            ollama_model="qwen3:8b",
            cloudflare_account_id="unrelated-cloud-account",
            cloudflare_ai_api_token="unrelated-cloud-token",
        ),
        client_factory=fake_factory,
    )

    assert record.candidate_id == "cloudflare-smoke-test"
    assert captured["api_key"] == "ollama"
    assert captured["base_url"] == "http://127.0.0.1:11434/v1"
    assert captured["request"]["model"] == "qwen3:8b"
    assert captured["request"]["temperature"] == 0
    assert captured["request"]["extra_body"] == {"think": False}


def test_main_sanitizes_backend_validation_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import validate_ai_backend

    settings = Settings(
        cloudflare_account_id="sensitive-account-id",
        cloudflare_ai_api_token="sensitive-api-token",
        cloudflare_ai_model="@cf/meta/llama-3.1-8b-instruct-fp8",
    )
    sensitive_error = (
        "sensitive-api-token response_body={'request_id': 'secret-request'}"
    )

    monkeypatch.setattr(
        validate_ai_backend.Settings,
        "from_env",
        classmethod(lambda cls: settings),
    )

    def fail_validation(_settings: Settings) -> EvidenceRecord:
        raise RuntimeError(sensitive_error)

    monkeypatch.setattr(validate_ai_backend, "validate_backend", fail_validation)

    assert validate_ai_backend.main() != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "provider": "Cloudflare Workers AI",
        "model": "@cf/meta/llama-3.1-8b-instruct-fp8",
        "success": False,
        "error_class": "RuntimeError",
    }
    combined_output = captured.out + captured.err
    for forbidden in (
        sensitive_error,
        "sensitive-api-token",
        "sensitive-account-id",
        "secret-request",
        "response_body",
        "Traceback",
    ):
        assert forbidden not in combined_output


def test_main_reports_safe_underlying_http_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import validate_ai_backend

    settings = Settings(
        cloudflare_account_id="sensitive-account-id",
        cloudflare_ai_api_token="sensitive-api-token",
        cloudflare_ai_model="@cf/meta/llama-3.1-8b-instruct-fast",
    )

    monkeypatch.setattr(
        validate_ai_backend.Settings,
        "from_env",
        classmethod(lambda cls: settings),
    )

    class PermissionDeniedError(RuntimeError):
        status_code = 403

    def fail_validation(_settings: Settings) -> EvidenceRecord:
        underlying = PermissionDeniedError(
            "sensitive-api-token response_body=secret-response"
        )
        raise EvidenceExtractionError("model evidence parsing failed") from underlying

    monkeypatch.setattr(validate_ai_backend, "validate_backend", fail_validation)

    assert validate_ai_backend.main() != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "provider": "Cloudflare Workers AI",
        "model": "@cf/meta/llama-3.1-8b-instruct-fast",
        "success": False,
        "error_class": "EvidenceExtractionError",
        "cause_class": "PermissionDeniedError",
        "http_status": 403,
    }
    for forbidden in (
        "sensitive-api-token",
        "sensitive-account-id",
        "secret-response",
        "response_body",
        "Traceback",
    ):
        assert forbidden not in captured.err


def test_main_reports_safe_symbolic_api_error_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import validate_ai_backend

    settings = Settings(
        cloudflare_account_id="sensitive-account-id",
        cloudflare_ai_api_token="sensitive-api-token",
    )
    monkeypatch.setattr(
        validate_ai_backend.Settings,
        "from_env",
        classmethod(lambda cls: settings),
    )

    class NotFoundError(RuntimeError):
        status_code = 404
        code = "model_not_found"

    def fail_validation(_settings: Settings) -> EvidenceRecord:
        raise EvidenceExtractionError("hidden wrapper") from NotFoundError(
            "sensitive response body"
        )

    monkeypatch.setattr(validate_ai_backend, "validate_backend", fail_validation)

    assert validate_ai_backend.main() != 0

    captured = capsys.readouterr()
    assert json.loads(captured.err)["api_error_code"] == "model_not_found"
    assert "sensitive response body" not in captured.err


def test_cli_sanitizes_incomplete_backend_configuration() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    sensitive_account_id = "sensitive-account-id"
    environment = os.environ.copy()
    environment.update(
        {
            "CLOUDFLARE_ACCOUNT_ID": sensitive_account_id,
            "CLOUDFLARE_AI_API_TOKEN": "",
            "OPENAI_API_KEY": "",
        }
    )

    result = subprocess.run(
        [sys.executable, "scripts/validate_ai_backend.py"],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "provider": "unavailable",
        "model": "unavailable",
        "success": False,
        "error_class": "ValueError",
    }
    for forbidden in (
        sensitive_account_id,
        "配置不完整",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_AI_API_TOKEN",
        "Traceback",
    ):
        assert forbidden not in result.stderr
