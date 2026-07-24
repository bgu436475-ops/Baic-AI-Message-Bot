from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_news_bot import cli
from ai_news_bot.history import HistoryStore
from ai_news_bot.models import Candidate


NOW = datetime(2026, 7, 24, 1, 5, tzinfo=UTC)


def _write_history(path: Path, entries: dict[str, str]) -> None:
    path.write_text(
        json.dumps({"sent": entries}),
        encoding="utf-8",
    )


def _candidate(url: str) -> Candidate:
    return Candidate(
        id="candidate",
        title="Model-X API v2 costs $1",
        summary="The SDK v2 is now available.",
        url=url,
        source="Example",
        source_tier=1,
        source_weight=1,
        published_at=NOW,
    )


def test_lookup_uses_explicit_thirty_day_boundary_and_ignores_bad_timestamps(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.json"
    recent = "https://example.com/recent"
    exact_cutoff = "https://example.com/exact-cutoff"
    expired = "https://example.com/expired"
    corrupt = "https://example.com/corrupt"
    _write_history(
        path,
        {
            recent: (NOW - timedelta(days=29, hours=23, minutes=59)).isoformat(),
            exact_cutoff: (NOW - timedelta(days=30)).isoformat(),
            expired: (NOW - timedelta(days=30, seconds=1)).isoformat(),
            corrupt: "not-a-timestamp",
        },
    )
    history = HistoryStore(path)

    assert history.contains(recent, now=NOW)
    assert history.contains(exact_cutoff, now=NOW)
    assert not history.contains(expired, now=NOW)
    assert not history.contains(corrupt, now=NOW)


def test_expired_url_never_blocks_candidates_without_a_record_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.json"
    url = "https://example.com/old-release"
    _write_history(
        path,
        {
            url: (NOW - timedelta(days=31)).isoformat(),
        },
    )
    candidate = _candidate(url)

    first = cli._prepare_candidates(
        [candidate],
        HistoryStore(path),
        max_candidates=80,
        now=NOW,
    )
    second = cli._prepare_candidates(
        [candidate],
        HistoryStore(path),
        max_candidates=80,
        now=NOW,
    )

    assert first == [candidate]
    assert second == [candidate]
