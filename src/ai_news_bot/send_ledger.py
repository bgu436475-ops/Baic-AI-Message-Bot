from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from .models import EditorialDigest


def _valid_success_entry(key: Any, value: Any) -> bool:
    if not isinstance(key, str) or not isinstance(value, dict):
        return False
    day_text, separator, target = key.partition("|")
    if not separator or not target.strip():
        return False
    try:
        date.fromisoformat(day_text)
    except ValueError:
        return False
    sent_at = value.get("sent_at")
    if not isinstance(sent_at, str):
        return False
    try:
        datetime.fromisoformat(sent_at)
    except ValueError:
        return False
    return value.get("run_status") in {
        "published",
        "no_qualifying_items",
    }


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
            successful_sends = value.get("successful_sends", {})
            if not isinstance(successful_sends, dict):
                return {}
            return {
                key: entry
                for key, entry in successful_sends.items()
                if _valid_success_entry(key, entry)
            }
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
        day = digest.generated_at.astimezone(self.zone).date()
        self.record_day_success(
            day,
            run_status=digest.run_status,
            target=target,
            now=now,
        )

    def record_day_success(
        self,
        day: date,
        *,
        run_status: Literal["published", "no_qualifying_items"],
        target: str = "feishu-daily",
        now: datetime | None = None,
    ) -> None:
        if run_status not in {"published", "no_qualifying_items"}:
            raise ValueError("unsupported successful run status")
        timestamp = now or datetime.now(UTC)
        data = self._load()
        data[f"{day.isoformat()}|{target}"] = {
            "sent_at": timestamp.isoformat(),
            "run_status": run_status,
        }
        self._write(data)

    def _write(self, data: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = (
            json.dumps(
                {"successful_sends": data},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
