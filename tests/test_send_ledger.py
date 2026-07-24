from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ai_news_bot.models import (
    DigestBoards,
    EditorialDigest,
    PipelineStats,
)
from ai_news_bot.send_ledger import SendLedger


def empty_digest(
    generated_at: datetime = datetime(
        2026,
        7,
        22,
        16,
        30,
        tzinfo=UTC,
    ),
) -> EditorialDigest:
    return EditorialDigest(
        run_status="no_qualifying_items",
        generated_at=generated_at,
        candidate_count=0,
        source_count=0,
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=0,
            shortlist_count=0,
            source_verified_count=0,
            rejected_count=0,
        ),
    )


def test_record_success_uses_digest_day_in_configured_timezone(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state" / "daily_sends.json"
    ledger = SendLedger(path)

    ledger.record_success(
        empty_digest(),
        now=datetime(2026, 7, 22, 16, 31, tzinfo=UTC),
    )

    assert ledger.was_sent(date(2026, 7, 23))
    assert not ledger.was_sent(date(2026, 7, 22))
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "successful_sends": {
            "2026-07-23|feishu-daily": {
                "sent_at": "2026-07-22T16:31:00+00:00",
                "run_status": "no_qualifying_items",
            }
        }
    }


def test_targets_are_recorded_independently(tmp_path: Path) -> None:
    ledger = SendLedger(tmp_path / "daily_sends.json")
    digest = empty_digest()

    ledger.record_success(digest, target="feishu-test")

    assert ledger.was_sent(date(2026, 7, 23), target="feishu-test")
    assert not ledger.was_sent(date(2026, 7, 23))


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        '{"successful_sends": []}',
        '{"successful_sends": null}',
    ],
)
def test_malformed_ledger_recovers_on_record(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / "daily_sends.json"
    path.write_text(payload, encoding="utf-8")
    ledger = SendLedger(path)

    assert not ledger.was_sent(date(2026, 7, 23))
    ledger.record_success(empty_digest())

    assert ledger.was_sent(date(2026, 7, 23))
