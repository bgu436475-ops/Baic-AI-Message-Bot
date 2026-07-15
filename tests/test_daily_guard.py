import json
from datetime import UTC, datetime
from pathlib import Path

from ai_news_bot.daily_guard import should_run_daily_digest


def _write_digest(path: Path, generated_at: str) -> None:
    path.write_text(json.dumps({"generated_at": generated_at}), encoding="utf-8")


def test_scheduled_retry_skips_digest_already_generated_today(tmp_path: Path) -> None:
    digest = tmp_path / "latest.json"
    _write_digest(digest, "2026-07-15T00:59:00Z")

    assert not should_run_daily_digest(
        "schedule",
        digest,
        now=datetime(2026, 7, 15, 1, 22, tzinfo=UTC),
    )


def test_scheduled_retry_skips_after_today_was_recorded_in_history(tmp_path: Path) -> None:
    digest = tmp_path / "missing.json"
    history = tmp_path / "history.json"
    history.write_text(
        json.dumps({"sent": {"https://example.com/news": "2026-07-15T01:10:00+00:00"}}),
        encoding="utf-8",
    )

    assert not should_run_daily_digest(
        "schedule",
        digest,
        history_path=history,
        now=datetime(2026, 7, 15, 1, 22, tzinfo=UTC),
    )


def test_scheduled_run_proceeds_for_previous_local_day(tmp_path: Path) -> None:
    digest = tmp_path / "latest.json"
    _write_digest(digest, "2026-07-14T15:59:00Z")

    assert should_run_daily_digest(
        "schedule",
        digest,
        now=datetime(2026, 7, 15, 1, 7, tzinfo=UTC),
    )


def test_manual_run_is_always_allowed(tmp_path: Path) -> None:
    digest = tmp_path / "latest.json"
    _write_digest(digest, "2026-07-15T00:59:00Z")

    assert should_run_daily_digest(
        "workflow_dispatch",
        digest,
        now=datetime(2026, 7, 15, 1, 22, tzinfo=UTC),
    )


def test_missing_or_invalid_digest_does_not_block_schedule(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    invalid = tmp_path / "invalid.json"
    wrong_shape = tmp_path / "wrong-shape.json"
    invalid.write_text("not json", encoding="utf-8")
    wrong_shape.write_text("[]", encoding="utf-8")

    assert should_run_daily_digest("schedule", missing)
    assert should_run_daily_digest("schedule", invalid)
    assert should_run_daily_digest("schedule", wrong_shape)
