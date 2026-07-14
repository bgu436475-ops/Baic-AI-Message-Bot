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
