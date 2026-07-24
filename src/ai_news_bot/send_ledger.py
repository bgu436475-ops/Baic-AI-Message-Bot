from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import EditorialDigest


class SendLedger:
    def __init__(
        self,
        path: Path,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self.path = path
        self.zone = ZoneInfo(timezone)

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(value.get("successful_sends", {}))
        except (
            AttributeError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
        ):
            return {}

    def was_sent(
        self,
        day: date,
        target: str = "feishu-daily",
    ) -> bool:
        return f"{day.isoformat()}|{target}" in self._load()

    def record_success(
        self,
        digest: EditorialDigest,
        target: str = "feishu-daily",
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        day = digest.generated_at.astimezone(self.zone).date()
        data = self._load()
        data[f"{day.isoformat()}|{target}"] = {
            "sent_at": timestamp.isoformat(),
            "run_status": digest.run_status,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"successful_sends": data},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
