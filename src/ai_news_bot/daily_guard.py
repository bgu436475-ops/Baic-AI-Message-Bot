from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _parse_generated_at(path: Path) -> datetime | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("generated_at")
        if not value:
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except (AttributeError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _parse_latest_history_sent_at(path: Path | None) -> datetime | None:
    if path is None or not path.exists():
        return None
    try:
        sent = json.loads(path.read_text(encoding="utf-8")).get("sent", {})
        timestamps = []
        for value in sent.values():
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            timestamps.append(parsed)
        return max(timestamps, default=None)
    except (AttributeError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def should_run_daily_digest(
    event_name: str,
    digest_path: Path,
    history_path: Path | None = None,
    timezone: str = "Asia/Shanghai",
    now: datetime | None = None,
) -> bool:
    """Allow manual runs, but skip a scheduled retry after today's digest exists."""
    if event_name != "schedule":
        return True

    zone = ZoneInfo(timezone)
    current = now or datetime.now(UTC)
    today = current.astimezone(zone).date()
    last_activity = [
        value
        for value in (
            _parse_generated_at(digest_path),
            _parse_latest_history_sent_at(history_path),
        )
        if value is not None
    ]
    return all(value.astimezone(zone).date() != today for value in last_activity)


def main() -> None:
    parser = argparse.ArgumentParser(description="Guard scheduled daily digest retries")
    parser.add_argument("--event", required=True)
    parser.add_argument("--digest", type=Path, required=True)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    args = parser.parse_args()
    should_run = should_run_daily_digest(
        args.event,
        args.digest,
        history_path=args.history,
        timezone=args.timezone,
    )
    print(f"should_run={'true' if should_run else 'false'}")


if __name__ == "__main__":
    main()
