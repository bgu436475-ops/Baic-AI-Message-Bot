import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_news_bot import cli
from ai_news_bot.config import Settings, SourcesConfig
from ai_news_bot.models import Candidate, DailyDigest, NewsItem


def _args(web_output: Path) -> argparse.Namespace:
    return argparse.Namespace(
        sources=Path("config/sources.yaml"),
        dry_run=True,
        skip_ai=False,
        target_count=None,
        lookback_hours=None,
        web_output=web_output,
        send_existing=False,
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


def _published_digest() -> DailyDigest:
    generated_at = datetime(2026, 7, 14, tzinfo=UTC)
    return DailyDigest(
        generated_at=generated_at,
        candidate_count=1,
        source_count=1,
        items=[
            NewsItem(
                original_title="One",
                title_zh="一",
                summary_zh="摘要",
                url="https://example.com/one",
                source="Example",
                published_at=generated_at,
                category="new_models",
                importance=90,
            )
        ],
    )


def _send_existing_args(web_output: Path) -> argparse.Namespace:
    args = _args(web_output)
    args.send_existing = True
    return args


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


def test_send_existing_sends_published_digest_and_records_history_once(
    monkeypatch, tmp_path: Path
) -> None:
    web_output = tmp_path / "latest.json"
    web_output.write_text(_published_digest().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli.Settings, "from_env", lambda: _settings(tmp_path))
    sent = []
    recorded = []
    monkeypatch.setattr(cli, "send_to_feishu", lambda digest, *args: sent.append(digest))
    monkeypatch.setattr(cli.HistoryStore, "record", lambda self, items: recorded.append(items))

    assert cli.run(_send_existing_args(web_output)) == 0

    assert sent == [_published_digest()]
    assert recorded == [_published_digest().items]


def test_send_existing_skips_empty_result_without_sending_or_recording_history(
    monkeypatch, tmp_path: Path
) -> None:
    web_output = tmp_path / "latest.json"
    empty = DailyDigest(
        generated_at=datetime(2026, 7, 14, tzinfo=UTC),
        candidate_count=0,
        source_count=0,
        run_status="no_qualifying_items",
        items=[],
    )
    web_output.write_text(empty.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli.Settings, "from_env", lambda: _settings(tmp_path))
    monkeypatch.setattr(cli, "send_to_feishu", lambda *args: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(
        cli.HistoryStore,
        "record",
        lambda *args: (_ for _ in ()).throw(AssertionError()),
    )

    assert cli.run(_send_existing_args(web_output)) == 0


@pytest.mark.parametrize("payload", ["not json", "{}"])
def test_send_existing_rejects_missing_or_invalid_result_before_feishu(
    monkeypatch, tmp_path: Path, payload: str
) -> None:
    web_output = tmp_path / "latest.json"
    if payload != "{}":
        web_output.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(cli.Settings, "from_env", lambda: _settings(tmp_path))
    monkeypatch.setattr(cli, "send_to_feishu", lambda *args: (_ for _ in ()).throw(AssertionError()))

    with pytest.raises(ValueError, match="persisted daily result"):
        cli.run(_send_existing_args(web_output))
