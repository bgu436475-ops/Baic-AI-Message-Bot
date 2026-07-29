from __future__ import annotations

from datetime import datetime

from .models import Candidate


GLOBAL_WINDOW_HOURS = 48
GLOBAL_FALLBACK_HOURS = 168


def shortlist_global_candidates(
    candidates: list[Candidate],
    now: datetime,
    limit: int = 20,
) -> list[Candidate]:
    eligible = [
        item
        for item in candidates
        if "global" in item.lane_hints
        and 0
        <= (now - item.published_at).total_seconds()
        <= GLOBAL_FALLBACK_HOURS * 3600
    ]
    return sorted(
        eligible,
        key=lambda item: (
            (
                0
                if (now - item.published_at).total_seconds()
                <= GLOBAL_WINDOW_HOURS * 3600
                else 1
            ),
            item.source_tier,
            -item.source_weight,
            -item.published_at.timestamp(),
            item.id,
        ),
    )[: max(0, min(limit, 20))]
