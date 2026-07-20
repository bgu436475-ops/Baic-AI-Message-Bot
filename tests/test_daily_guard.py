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


def test_empty_result_blocks_automatic_events_but_not_manual_runs(tmp_path: Path) -> None:
    digest = tmp_path / "latest.json"
    digest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_status": "no_qualifying_items",
                "generated_at": "2026-07-15T00:59:00Z",
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 7, 15, 1, 22, tzinfo=UTC)

    assert not should_run_daily_digest("schedule", digest, now=now)
    assert not should_run_daily_digest("repository_dispatch", digest, now=now)
    assert should_run_daily_digest("workflow_dispatch", digest, now=now)


def test_missing_or_invalid_digest_does_not_block_schedule(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    invalid = tmp_path / "invalid.json"
    wrong_shape = tmp_path / "wrong-shape.json"
    invalid.write_text("not json", encoding="utf-8")
    wrong_shape.write_text("[]", encoding="utf-8")

    assert should_run_daily_digest("schedule", missing)
    assert should_run_daily_digest("schedule", invalid)
    assert should_run_daily_digest("schedule", wrong_shape)


def test_repository_dispatch_skips_digest_generated_today(tmp_path: Path) -> None:
    digest = tmp_path / "latest.json"
    _write_digest(digest, "2026-07-15T00:59:00Z")

    assert not should_run_daily_digest(
        "repository_dispatch",
        digest,
        now=datetime(2026, 7, 15, 1, 22, tzinfo=UTC),
    )


def test_repository_dispatch_runs_when_today_has_no_digest(tmp_path: Path) -> None:
    digest = tmp_path / "latest.json"
    _write_digest(digest, "2026-07-14T15:59:00Z")

    assert should_run_daily_digest(
        "repository_dispatch",
        digest,
        now=datetime(2026, 7, 15, 1, 5, tzinfo=UTC),
    )


def test_workflow_accepts_external_dispatch_and_preserves_fallbacks() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github/workflows/daily-ai-news.yml"
    ).read_text(encoding="utf-8")

    assert "repository_dispatch:" in workflow
    assert "types: [daily-ai-news]" in workflow
    assert 'cron: "5 1 * * *"' in workflow
    assert 'cron: "20 1 * * *"' in workflow
    assert "workflow_dispatch:" in workflow


def test_workflow_persists_before_send_and_separates_manual_concurrency() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github/workflows/daily-ai-news.yml"
    ).read_text(encoding="utf-8")

    generate_position = workflow.index("ai-news-bot --dry-run")
    persist_position = workflow.index("git add web/public/data/latest.json")
    send_position = workflow.index("ai-news-bot --send-existing")
    assert generate_position < persist_position < send_position
    send_step = workflow[workflow.rfind("- name:", 0, send_position) : send_position]
    assert "always()" not in send_step
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "github.run_id" in workflow
    assert "daily-ai-news-automatic" in workflow
    assert "cancel-in-progress: false" in workflow


def test_readme_documents_external_primary_and_github_fallback() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "Cloudflare Worker" in readme
    assert "09:05" in readme
    assert "09:20" in readme
    assert "GITHUB_DISPATCH_TOKEN" in readme
    assert 'cron: "7 9 * * *"' not in readme
    assert 'cron: "22 9 * * *"' not in readme
