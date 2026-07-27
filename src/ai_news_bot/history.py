from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import EditorialNewsItem
from .text import canonicalize_url


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class HistoryStore:
    def __init__(self, path: Path, retention_days: int = 30) -> None:
        self.path = path
        self.retention_days = retention_days
        self._items = self._load()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(key): str(value) for key, value in data.get("sent", {}).items()}
        except (OSError, ValueError, TypeError):
            return {}

    def contains(self, url: str, now: datetime) -> bool:
        timestamp = self._items.get(canonicalize_url(url))
        if timestamp is None:
            return False
        try:
            recorded_at = _aware(datetime.fromisoformat(timestamp))
        except ValueError:
            return False
        current = _aware(now)
        cutoff = current - timedelta(days=self.retention_days)
        return cutoff <= recorded_at <= current

    def record(
        self,
        items: list[EditorialNewsItem],
        now: datetime | None = None,
    ) -> None:
        now = _aware(now or datetime.now(UTC))
        cutoff = now - timedelta(days=self.retention_days)
        fresh: dict[str, str] = {}
        for url, timestamp in self._items.items():
            try:
                parsed = _aware(datetime.fromisoformat(timestamp))
                if cutoff <= parsed <= now:
                    fresh[url] = parsed.isoformat()
            except ValueError:
                continue
        for item in items:
            fresh[canonicalize_url(item.evidence_url)] = now.isoformat()
        self._items = fresh
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"sent": fresh}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
