from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ai_news_bot.config import Settings
from ai_news_bot.model_backend import BackendSpec, create_model_client, create_ollama_session


def test_explicit_openai_does_not_fall_back_to_cloudflare() -> None:
    settings = Settings(
        ai_backend_name="openai",
        openai_api_key="openai-key",
        cloudflare_account_id="account-123",
        cloudflare_ai_api_token="cf-token",
    )

    backend = settings.ai_backend()

    assert backend.provider_id == "openai"


def test_ollama_model_client_ignores_proxy_environment(
    monkeypatch,
) -> None:
    """A proxy inherited from the shell must not turn a loopback model call remote."""
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.test:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:8443")
    captured: dict[str, Any] = {}

    def fake_factory(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace()

    client = create_model_client(
        BackendSpec(
            provider_id="ollama",
            provider_label="Ollama",
            api_key="ollama",
            model="qwen3:8b",
            base_url="http://127.0.0.1:11434/v1",
        ),
        client_factory=fake_factory,
    )

    assert isinstance(client, SimpleNamespace)
    assert captured["http_client"]._trust_env is False
    captured["http_client"].close()


def test_ollama_tags_session_ignores_proxy_environment(monkeypatch) -> None:
    """Loopback health requests need the same proxy isolation as model requests."""
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.test:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:8443")

    session = create_ollama_session()

    try:
        assert session.trust_env is False
    finally:
        session.close()
