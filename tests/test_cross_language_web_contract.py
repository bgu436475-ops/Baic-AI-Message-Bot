from pathlib import Path

from ai_news_bot.models import EditorialDigest


FIXTURE = (
    Path(__file__).parents[1]
    / "web"
    / "tests"
    / "fixtures"
    / "python-global-v4.json"
)


def test_python_generated_web_fixture_is_valid_schema_v4() -> None:
    digest = EditorialDigest.model_validate_json(FIXTURE.read_text(encoding="utf-8"))

    assert digest.schema_version == 4
    assert digest.global_events[0].category == "models_products"
    assert digest.items == digest.boards.flatten()
