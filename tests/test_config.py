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

    assert settings.ai_backend() == (
        "cf-token",
        "@cf/meta/llama-3.1-8b-instruct-fp8",
        "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1",
        "Cloudflare Workers AI",
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
    assert Settings(openai_api_key="openai-key").ai_backend() == (
        "openai-key",
        "gpt-5.6-luna",
        None,
        "OpenAI",
    )


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
        (None, "@cf/meta/llama-3.1-8b-instruct-fp8"),
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
    if model is not None:
        monkeypatch.setenv("CLOUDFLARE_AI_MODEL", f" {model} ")

    settings = Settings.from_env()

    assert settings.cloudflare_account_id == "account-123"
    assert settings.cloudflare_ai_api_token == "cf-token"
    assert settings.cloudflare_ai_model == expected_model


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
