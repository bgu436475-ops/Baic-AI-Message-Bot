from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_news_bot.config import Settings, load_sources


def test_source_config_loads() -> None:
    config = load_sources(Path("config/sources.yaml"))
    assert len(config.rss) >= 10
    assert len(config.webpages) >= 1
    assert config.github.enabled is True
    assert any(source.name == "Anthropic News" for source in config.webpages)


def test_every_source_declares_a_lane_and_github_is_technical_only() -> None:
    config = load_sources(Path("config/sources.yaml"))

    assert all(source.lanes for source in [*config.rss, *config.webpages])
    assert all(query.lanes == ["technical"] for query in config.github.queries)
    assert any("global" in source.lanes for source in config.rss)


def test_ai_backend_prefers_complete_cloudflare_configuration() -> None:
    settings = Settings(
        cloudflare_account_id="account-123",
        cloudflare_ai_api_token="cf-token",
        openai_api_key="openai-key",
        github_token="github-token",
    )

    backend = settings.ai_backend()

    assert backend.provider_id == "cloudflare"
    assert backend.provider_label == "Cloudflare Workers AI"
    assert backend.api_key == "cf-token"
    assert backend.model == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert backend.base_url == (
        "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1"
    )


@pytest.mark.parametrize(
    "account_id",
    ["account-123/other", "account-123?query=other", "account-123#fragment"],
)
def test_ai_backend_rejects_account_ids_that_can_change_the_endpoint(
    account_id: str,
) -> None:
    settings = Settings(
        cloudflare_account_id=account_id,
        cloudflare_ai_api_token="cf-token",
    )

    with pytest.raises(ValueError, match="Cloudflare account ID"):
        settings.ai_backend()


def test_ai_backend_uses_openai_when_cloudflare_is_unconfigured() -> None:
    backend = Settings(openai_api_key="openai-key").ai_backend()

    assert backend.provider_id == "openai"
    assert backend.provider_label == "OpenAI"
    assert backend.api_key == "openai-key"
    assert backend.model == "gpt-5.6-luna"
    assert backend.base_url is None


def test_explicit_ollama_ignores_cloud_credentials() -> None:
    settings = Settings(
        ai_backend_name="ollama",
        ollama_base_url="http://127.0.0.1:11434/v1",
        ollama_model="qwen3:8b",
        cloudflare_account_id="wrong-cloud-account",
        cloudflare_ai_api_token="cloud-token",
    )

    backend = settings.ai_backend()

    assert backend.provider_id == "ollama"
    assert backend.api_key == "ollama"
    assert backend.model == "qwen3:8b"
    assert backend.base_url == "http://127.0.0.1:11434/v1"
    assert backend.chat_options == {"temperature": 0, "extra_body": {"think": False}}


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://192.168.1.5:11434/v1",
        "http://user:pass@127.0.0.1:11434/v1",
        "http://127.0.0.1:11434/v1?token=secret",
        "http://127.0.0.1:11434/api",
    ],
)
def test_ollama_rejects_non_loopback_or_malformed_urls(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        Settings(ai_backend_name="ollama", ollama_base_url=url).ai_backend()


@pytest.mark.parametrize(
    ("account_id", "token"),
    [("account-123", ""), ("", "cf-token")],
)
def test_ai_backend_rejects_partial_cloudflare_configuration(
    account_id: str,
    token: str,
) -> None:
    settings = Settings(
        cloudflare_account_id=account_id,
        cloudflare_ai_api_token=token,
        openai_api_key="openai-key",
    )

    with pytest.raises(ValueError, match="Cloudflare"):
        settings.ai_backend()


def test_github_token_alone_is_not_an_ai_backend() -> None:
    with pytest.raises(ValueError, match="(?i)cloudflare|openai"):
        Settings(github_token="github-token").ai_backend()


@pytest.mark.parametrize(
    ("model", "expected_model"),
    [
        (None, "@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
        ("@cf/custom/model", "@cf/custom/model"),
    ],
)
def test_environment_loads_stripped_cloudflare_settings_and_model(
    monkeypatch: pytest.MonkeyPatch,
    model: str | None,
    expected_model: str,
) -> None:
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", " account-123 ")
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", " cf-token ")
    monkeypatch.delenv("CLOUDFLARE_AI_MODEL", raising=False)
    if model is not None:
        monkeypatch.setenv("CLOUDFLARE_AI_MODEL", f" {model} ")

    settings = Settings.from_env()

    assert settings.cloudflare_account_id == "account-123"
    assert settings.cloudflare_ai_api_token == "cf-token"
    assert settings.cloudflare_ai_model == expected_model


def test_environment_loads_explicit_ollama_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BACKEND", " ollama ")
    monkeypatch.setenv("OLLAMA_BASE_URL", " http://localhost:11434/v1/ ")
    monkeypatch.setenv("OLLAMA_MODEL", " qwen3:8b ")

    backend = Settings.from_env().ai_backend()

    assert backend.provider_id == "ollama"
    assert backend.base_url == "http://localhost:11434/v1"
    assert backend.model == "qwen3:8b"


def test_editorial_state_paths_default_to_private_state_directory() -> None:
    settings = Settings()

    assert settings.state_path == Path(".state/history.json")
    assert settings.event_history_path == Path(".state/events.json")
    assert settings.send_ledger_path == Path(".state/daily_sends.json")
    assert settings.audit_path == Path(".state/latest_audit.json")


def test_editorial_state_paths_can_be_configured_from_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EVENT_HISTORY_PATH", "private/events.json")
    monkeypatch.setenv("SEND_LEDGER_PATH", "private/sends.json")
    monkeypatch.setenv("AUDIT_PATH", "private/audit.json")

    settings = Settings.from_env()

    assert settings.event_history_path == Path("private/events.json")
    assert settings.send_ledger_path == Path("private/sends.json")
    assert settings.audit_path == Path("private/audit.json")


@pytest.mark.parametrize("max_candidates", [81, 200])
def test_settings_rejects_candidate_caps_above_hard_eighty(
    max_candidates: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(max_candidates=max_candidates)


def test_environment_cannot_raise_candidate_cap_above_eighty(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MAX_CANDIDATES", "200")

    with pytest.raises(ValidationError):
        Settings.from_env()


def test_settings_has_no_legacy_target_news_count(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TARGET_NEWS_COUNT", "3")

    settings = Settings.from_env()

    assert "target_news_count" not in Settings.model_fields
    assert "target_news_count" not in settings.model_dump()
