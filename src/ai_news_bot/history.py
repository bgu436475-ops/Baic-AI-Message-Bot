from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import NewsItem
from .text import canonicalize_url


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

    def contains(self, url: str) -> bool:
        return canonicalize_url(url) in self._items

    def record(self, items: list[NewsItem], now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=self.retention_days)
        fresh: dict[str, str] = {}
        for url, timestamp in self._items.items():
            try:
                parsed = datetime.fromisoformat(timestamp)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                if parsed >= cutoff:
                    fresh[url] = parsed.isoformat()
            except ValueError:
                continue
        for item in items:
            fresh[canonicalize_url(item.url)] = now.isoformat()
        self._items = fresh
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"sent": fresh}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

