from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_news_bot import daily_guard
from ai_news_bot.daily_guard import should_run_daily_digest


NOW = datetime(2026, 7, 23, 1, 22, tzinfo=UTC)


def _write_success(
    path: Path,
    *,
    day: str = "2026-07-23",
    target: str = "feishu-daily",
    run_status: str = "published",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "successful_sends": {
                    f"{day}|{target}": {
                        "sent_at": "2026-07-23T01:10:00+00:00",
                        "run_status": run_status,
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_generated_digest_without_successful_delivery_remains_runnable(
    tmp_path: Path,
) -> None:
    generated_digest = tmp_path / "latest.json"
    generated_digest.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-23T01:05:00+00:00",
                "run_status": "published",
            }
        ),
        encoding="utf-8",
    )
    missing_ledger = tmp_path / "daily_sends.json"

    assert should_run_daily_digest(
        "schedule",
        missing_ledger,
        now=NOW,
    )
    assert should_run_daily_digest(
        "repository_dispatch",
        missing_ledger,
        now=NOW,
    )


@pytest.mark.parametrize("event_name", ["schedule", "repository_dispatch"])
@pytest.mark.parametrize(
    "run_status",
    ["published", "no_qualifying_items"],
)
def test_today_successful_send_blocks_automatic_events(
    tmp_path: Path,
    event_name: str,
    run_status: str,
) -> None:
    ledger = tmp_path / "daily_sends.json"
    _write_success(ledger, run_status=run_status)

    assert not should_run_daily_digest(
        event_name,
        ledger,
        now=NOW,
    )


def test_previous_local_day_or_other_target_does_not_block_schedule(
    tmp_path: Path,
) -> None:
    previous = tmp_path / "previous.json"
    other_target = tmp_path / "other-target.json"
    _write_success(previous, day="2026-07-22")
    _write_success(other_target, target="feishu-test")

    assert should_run_daily_digest("schedule", previous, now=NOW)
    assert should_run_daily_digest("schedule", other_target, now=NOW)


def test_manual_run_is_always_allowed_after_success(tmp_path: Path) -> None:
    ledger = tmp_path / "daily_sends.json"
    _write_success(ledger)

    assert should_run_daily_digest(
        "workflow_dispatch",
        ledger,
        now=NOW,
    )


def test_guard_cli_requires_ledger_and_emits_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_guard",
            "--event",
            "schedule",
            "--ledger",
            str(tmp_path / "daily_sends.json"),
        ],
    )

    daily_guard.main()

    assert capsys.readouterr().out == "should_run=true\n"


def _workflow() -> str:
    return (
        Path(__file__).parents[1]
        / ".github/workflows/daily-ai-news.yml"
    ).read_text(encoding="utf-8")


def test_workflow_is_manual_diagnostics_only() -> None:
    workflow = _workflow()

    assert "workflow_dispatch:" in workflow
    assert "repository_dispatch:" not in workflow
    assert "schedule:" not in workflow
    assert "ai-news-bot --dry-run" not in workflow
    assert "ai-news-bot --send-existing" not in workflow
    assert "FEISHU_" not in workflow


def test_workflow_has_no_cloud_delivery_state_or_dashboard_write_steps() -> None:
    workflow = _workflow()

    assert "actions/cache/restore@v5" not in workflow
    assert "actions/cache/save@v5" not in workflow
    assert "daily_guard" not in workflow
    assert "SITE_DIGEST_" not in workflow
    assert "git push" not in workflow


def test_manual_workflow_keeps_validation_preview_and_web_checks() -> None:
    workflow = _workflow()

    assert "- name: Run Python validation" in workflow
    assert "- name: Validate AI backend without sending" in workflow
    assert "- name: Build no-send preview" in workflow
    assert "- name: Validate website" in workflow
    assert "- name: Upload no-send preview" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow
    assert "github.ref == 'refs/heads/main'" not in workflow


def test_workflow_serializes_manual_and_automatic_runs() -> None:
    workflow = _workflow()
    concurrency = workflow[
        workflow.index("concurrency:") :
        workflow.index("permissions:")
    ]

    assert "group: daily-ai-news" in concurrency
    assert "github.run_id" not in concurrency
    assert "cancel-in-progress: false" in concurrency


def test_readme_documents_local_primary_and_manual_cloud_diagnostics() -> None:
    readme = (
        Path(__file__).parents[1] / "README.md"
    ).read_text(encoding="utf-8")

    assert "本机单通道" in readme
    assert "GitHub Actions 仅保留手动诊断" in readme
    assert "09:05" in readme
    assert "09:20" not in readme
    assert "GitHub 与 Cloudflare 不会自动发送" in readme
