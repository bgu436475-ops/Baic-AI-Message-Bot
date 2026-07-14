import json
from datetime import datetime, timezone

from ai_news_bot.models import DailyDigest, NewsItem
from ai_news_bot.web_export import export_digest_for_web


def test_export_digest_for_web(tmp_path):
    digest = DailyDigest(
        generated_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        candidate_count=12,
        source_count=3,
        items=[
            NewsItem(
                original_title="Test model",
                title_zh="测试模型发布",
                summary_zh="这是摘要。",
                url="https://example.com/model",
                source="Example",
                published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
                category="new_models",
                importance=88,
            )
        ],
    )
    output = tmp_path / "public" / "data" / "latest.json"

    export_digest_for_web(digest, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 12
    assert payload["items"][0]["title_zh"] == "测试模型发布"
