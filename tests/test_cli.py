import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from ai_news_bot import cli
from ai_news_bot.config import Settings, SourcesConfig
from ai_news_bot.models import Candidate


def _args(web_output: Path) -> argparse.Namespace:
    return argparse.Namespace(
        sources=Path("config/sources.yaml"),
        dry_run=True,
        skip_ai=False,
        target_count=None,
        lookback_hours=None,
        web_output=web_output,
        log_level="INFO",
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        openai_api_key="test-key",
        state_path=tmp_path / "state" / "history.json",
        target_news_count=1,
        max_candidates=10,
    )


def _candidate() -> Candidate:
    return Candidate(
        id="one",
        title="One",
        url="https://example.com/one",
        source="Example",
        source_tier=1,
        source_weight=1,
        published_at=datetime(2026, 7, 14, tzinfo=UTC),
    )


def test_no_candidates_persists_empty_daily_result_without_sending(
    monkeypatch, tmp_path: Path
) -> None:
    web_output = tmp_path / "latest.json"
    monkeypatch.setattr(cli.Settings, "from_env", lambda: _settings(tmp_path))
    monkeypatch.setattr(cli, "load_sources", lambda path: SourcesConfig(rss=[]))
    monkeypatch.setattr(cli, "_collect_candidates", lambda *args, **kwargs: [])
    sent = []
    monkeypatch.setattr(cli, "send_to_feishu", lambda *args, **kwargs: sent.append(True))

    assert cli.run(_args(web_output)) == 0

    payload = json.loads(web_output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["run_status"] == "no_qualifying_items"
    assert payload["items"] == []
    assert sent == []


def test_no_curated_items_persists_empty_daily_result_without_sending(
    monkeypatch, tmp_path: Path
) -> None:
    web_output = tmp_path / "latest.json"
    monkeypatch.setattr(cli.Settings, "from_env", lambda: _settings(tmp_path))
    monkeypatch.setattr(cli, "load_sources", lambda path: SourcesConfig(rss=[]))
    monkeypatch.setattr(cli, "_collect_candidates", lambda *args, **kwargs: [_candidate()])
    monkeypatch.setattr(cli, "select_with_openai", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "send_to_feishu", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    assert cli.run(_args(web_output)) == 0

    payload = json.loads(web_output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["run_status"] == "no_qualifying_items"
    assert payload["candidate_count"] == 1
    assert payload["source_count"] == 1
    assert payload["items"] == []
