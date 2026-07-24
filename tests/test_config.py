from pathlib import Path

from ai_news_bot.config import Settings, load_sources


def test_source_config_loads() -> None:
    config = load_sources(Path("config/sources.yaml"))
    assert len(config.rss) >= 10
    assert len(config.webpages) >= 1
    assert config.github.enabled is True
    assert any(source.name == "Anthropic News" for source in config.webpages)


def test_ai_backend_prefers_openai_then_github_models() -> None:
    openai = Settings(openai_api_key="openai-key", github_token="github-token")
    assert openai.ai_backend() == ("openai-key", "gpt-5.6-luna", None, "OpenAI")

    github = Settings(github_token="github-token")
    assert github.ai_backend() == (
        "github-token",
        "openai/gpt-4o-mini",
        "https://models.github.ai/inference",
        "GitHub Models",
    )


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
