from pathlib import Path

from ai_news_bot.models import EditorialDigest


FIXTURE = (
    Path(__file__).parents[1]
    / "web"
    / "tests"
    / "fixtures"
    / "python-empty-event-entities-v3.json"
)


def test_python_generated_web_fixture_is_valid_schema_v3() -> None:
    digest = EditorialDigest.model_validate_json(FIXTURE.read_text(encoding="utf-8"))

    assert digest.items[0].event_entities == []
    assert digest.items[1].event_entities == [""]
    assert digest.items == digest.boards.flatten()
