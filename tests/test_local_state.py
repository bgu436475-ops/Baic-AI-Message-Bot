from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ai_news_bot.local_state import (
    FallbackLedger,
    FallbackStateError,
    LocalRunAlreadyActive,
    exclusive_run_lock,
)


DAY = date(2026, 8, 3)
NOW = datetime(2026, 8, 3, 2, 0, tzinfo=UTC)


def test_uncertain_delivery_blocks_same_day_retry(tmp_path: Path) -> None:
    """Changing uncertain delivery to retryable would risk a duplicate card."""
    ledger = FallbackLedger(tmp_path / "fallback.json")

    ledger.mark_uncertain(DAY, at=NOW)

    assert ledger.blocks_send(DAY) is True


def test_sent_state_retains_delivery_metadata_while_pending_work_is_cleared(
    tmp_path: Path,
) -> None:
    """Clearing one completion flag must not erase the other recovery work."""
    ledger = FallbackLedger(tmp_path / "fallback.json")
    ledger.mark_sent(
        DAY,
        "a" * 32,
        "published",
        at=NOW,
        cloud_sync_pending=True,
        dashboard_pending=True,
    )

    ledger.mark_sync_complete(DAY, at=NOW)
    state = ledger.day_state(DAY)

    assert state is not None
    assert state.delivery_status == "sent"
    assert state.delivery_id == "a" * 32
    assert state.run_status == "published"
    assert state.cloud_sync_pending is False
    assert state.dashboard_pending is True


def test_exclusive_lock_rejects_second_process(tmp_path: Path) -> None:
    """Dropping nonblocking locking could allow two fallback processes to send."""
    with exclusive_run_lock(tmp_path / "run.lock"):
        with pytest.raises(LocalRunAlreadyActive):
            with exclusive_run_lock(tmp_path / "run.lock"):
                pass


def test_noncanonical_date_key_fails_closed(tmp_path: Path) -> None:
    """Accepting an alternate date key could hide a same-day terminal state."""
    path = tmp_path / "fallback.json"
    path.write_text(
        json.dumps(
            {
                "days": {
                    "20260803": {
                        "delivery_status": "uncertain_delivery",
                        "delivery_id": None,
                        "run_status": None,
                        "cloud_sync_pending": False,
                        "dashboard_pending": False,
                        "updated_at": NOW.isoformat(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FallbackStateError):
        FallbackLedger(path).blocks_send(DAY)
