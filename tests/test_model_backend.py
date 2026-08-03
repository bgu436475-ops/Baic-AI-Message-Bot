from ai_news_bot.config import Settings


def test_explicit_openai_does_not_fall_back_to_cloudflare() -> None:
    settings = Settings(
        ai_backend_name="openai",
        openai_api_key="openai-key",
        cloudflare_account_id="account-123",
        cloudflare_ai_api_token="cf-token",
    )

    backend = settings.ai_backend()

    assert backend.provider_id == "openai"
