from ai_news_bot.text import canonicalize_url, normalized_title


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    assert (
        canonicalize_url("HTTPS://Example.COM/news/?utm_source=x&id=3#part")
        == "https://example.com/news?id=3"
    )


def test_normalized_title_removes_announcement_words() -> None:
    assert normalized_title("Introducing: New Agent SDK!") == "agent sdk"

