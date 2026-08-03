from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import json

import pytest

from ai_news_bot.record_local_delivery import main, record_dispatched_delivery
from ai_news_bot.send_ledger import SendLedger


NOW = datetime(2026, 8, 3, 2, 0, tzinfo=UTC)


def test_records_only_current_beijing_day(tmp_path: Path) -> None:
    """A confirmed local delivery must suppress the matching cloud day."""
    payload = {
        "delivery_date": "2026-08-03",
        "delivery_id": "a" * 32,
        "run_status": "published",
    }

    day = record_dispatched_delivery(payload, tmp_path / "daily_sends.json", NOW)

    assert day == date(2026, 8, 3)
    assert SendLedger(tmp_path / "daily_sends.json").was_sent(day)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "delivery_date": "2026-08-02",
            "delivery_id": "a" * 32,
            "run_status": "published",
        },
        {
            "delivery_date": "2026-08-03",
            "delivery_id": "not-safe",
            "run_status": "published",
        },
        {
            "delivery_date": "2026-08-03",
            "delivery_id": "a" * 32,
            "run_status": "failed",
        },
        {
            "delivery_date": "2026-08-03",
            "delivery_id": "a" * 32,
            "run_status": [],
        },
    ],
)
def test_rejects_invalid_or_noncurrent_payload(
    payload: dict[str, object],
    tmp_path: Path,
) -> None:
    """Relaxing validation could let stale or forged dispatches block cloud sends."""
    with pytest.raises(ValueError):
        record_dispatched_delivery(payload, tmp_path / "daily_sends.json", NOW)


def test_cli_prints_only_the_recorded_date(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extra output would corrupt the workflow's state-only recording contract."""
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "delivery_date": "2026-08-03",
                "delivery_id": "a" * 32,
                "run_status": "no_qualifying_items",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ai_news_bot.record_local_delivery.datetime",
        FrozenDateTime,
    )

    assert main(["--payload", str(payload_path), "--ledger", str(tmp_path / "daily_sends.json")]) == 0

    assert capsys.readouterr().out == "recorded_date=2026-08-03\n"


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def]
        assert tz is UTC
        return NOW
