from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .send_ledger import SendLedger


_DELIVERY_ID = re.compile(r"[0-9a-f]{32}\Z")
_SUCCESSFUL_RUN_STATUSES = frozenset({"published", "no_qualifying_items"})
_BEIJING = ZoneInfo("Asia/Shanghai")


def record_dispatched_delivery(
    payload: dict[str, Any],
    ledger_path: Path,
    now: datetime,
) -> date:
    """Persist a confirmed local delivery only for the current Beijing day."""
    delivery_date = payload.get("delivery_date")
    delivery_id = payload.get("delivery_id")
    run_status = payload.get("run_status")
    current_day = now.astimezone(_BEIJING).date()

    if (
        not isinstance(delivery_date, str)
        or delivery_date != current_day.isoformat()
        or not isinstance(delivery_id, str)
        or _DELIVERY_ID.fullmatch(delivery_id) is None
        or not isinstance(run_status, str)
        or run_status not in _SUCCESSFUL_RUN_STATUSES
    ):
        raise ValueError("invalid local delivery payload")

    SendLedger(ledger_path).record_day_success(
        current_day,
        run_status=run_status,
        target="feishu-daily",
        now=now,
    )
    return current_day


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record a confirmed local AI news delivery.",
    )
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid local delivery payload") from error
    if not isinstance(payload, dict):
        raise ValueError("invalid local delivery payload")

    recorded_day = record_dispatched_delivery(
        payload,
        args.ledger,
        datetime.now(UTC),
    )
    print(f"recorded_date={recorded_day.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
