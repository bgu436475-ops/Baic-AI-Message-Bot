from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .send_ledger import SendLedger


AUTOMATED_EVENTS = frozenset({"schedule", "repository_dispatch"})


def should_run_daily_digest(
    event_name: str,
    ledger_path: Path,
    timezone: str = "Asia/Shanghai",
    now: datetime | None = None,
) -> bool:
    """Allow manual runs and block automatic retries only after delivery."""
    if event_name not in AUTOMATED_EVENTS:
        return True

    zone = ZoneInfo(timezone)
    current = now or datetime.now(UTC)
    return not SendLedger(ledger_path, timezone).was_sent(
        current.astimezone(zone).date()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Guard scheduled daily digest retries")
    parser.add_argument("--event", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    args = parser.parse_args()
    should_run = should_run_daily_digest(
        args.event,
        args.ledger,
        timezone=args.timezone,
    )
    print(f"should_run={'true' if should_run else 'false'}")


if __name__ == "__main__":
    main()
