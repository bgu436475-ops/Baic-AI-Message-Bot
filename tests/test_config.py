from pathlib import Path

from ai_news_bot.config import load_sources


def test_source_config_loads() -> None:
    config = load_sources(Path("config/sources.yaml"))
    assert len(config.rss) >= 10
    assert len(config.webpages) >= 1
    assert config.github.enabled is True
    assert any(source.name == "Anthropic News" for source in config.webpages)
