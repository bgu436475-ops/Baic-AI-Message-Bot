from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ai_news_bot.models import (
    DigestBoards,
    EditorialDigest,
    GlobalPipelineStats,
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
        daily_narrative_zh="今天没有技术情报通过核验。",
        global_pipeline_stats=GlobalPipelineStats(
            candidate_count=0,
            shortlist_count=0,
            source_verified_count=0,
            rejected_count=0,
        ),
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


def test_invalid_entries_are_skipped_while_valid_success_is_preserved(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily_sends.json"
    path.write_text(
        json.dumps(
            {
                "successful_sends": {
                    "2026-07-22|feishu-daily": {
                        "sent_at": "2026-07-22T01:00:00+00:00",
                        "run_status": "published",
                    },
                    "not-a-day|feishu-daily": {
                        "sent_at": "2026-07-22T01:00:00+00:00",
                        "run_status": "published",
                    },
                    "2026-07-23|bad-timestamp": {
                        "sent_at": "not-a-timestamp",
                        "run_status": "published",
                    },
                    "2026-07-23|bad-status": {
                        "sent_at": "2026-07-22T01:00:00+00:00",
                        "run_status": "failed",
                    },
                    "2026-07-23|bad-shape": "sent",
                }
            }
        ),
        encoding="utf-8",
    )
    ledger = SendLedger(path)

    assert ledger.was_sent(date(2026, 7, 22))
    assert not ledger.was_sent(
        date(2026, 7, 23),
        target="bad-timestamp",
    )
    ledger.record_success(empty_digest())

    stored = json.loads(path.read_text(encoding="utf-8"))[
        "successful_sends"
    ]
    assert set(stored) == {
        "2026-07-22|feishu-daily",
        "2026-07-23|feishu-daily",
    }


def test_state_write_uses_same_directory_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "daily_sends.json"
    calls: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def observed_replace(
        source: str | Path,
        target: str | Path,
    ) -> None:
        calls.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", observed_replace)

    SendLedger(path).record_success(empty_digest())

    assert len(calls) == 1
    source, target = calls[0]
    assert source.parent == path.parent
    assert target == path
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_replace_failure_preserves_old_ledger_and_cleans_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "daily_sends.json"
    old_payload = json.dumps(
        {
            "successful_sends": {
                "2026-07-22|feishu-daily": {
                    "sent_at": "2026-07-22T01:00:00+00:00",
                    "run_status": "published",
                }
            }
        }
    )
    path.write_text(old_payload, encoding="utf-8")

    def failed_replace(
        source: str | Path,
        target: str | Path,
    ) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", failed_replace)

    with pytest.raises(OSError, match="replace failed"):
        SendLedger(path).record_success(empty_digest())

    assert path.read_text(encoding="utf-8") == old_payload
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []
