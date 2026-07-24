from __future__ import annotations

import math
import re
from datetime import datetime

from .models import Candidate


SPECIFIC = re.compile(
    r"(?ix)(\b(?:api|sdk|model|benchmark|license|pricing|price|tokens?|"
    r"parameters?|revenue|customers?|effective|v\d+(?:\.\d+)*)\b|"
    r"\d+(?:\.\d+)?\s*(?:%|x|b|m|k|usd|dollars?|tokens?|params?))"
)
WEAK_ONLY = re.compile(r"(?i)\b(?:may|might|could|potential|future|有望|预示|潜力|值得关注)\b")


def _rough_score(item: Candidate, now: datetime) -> tuple[float, str]:
    text = f"{item.title} {item.summary}"
    age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600)
    freshness = max(0.0, 30 - min(30, age_hours / 4))
    authority = {1: 40, 2: 25, 3: 10}[item.source_tier]
    specificity = 25 if SPECIFIC.search(text) else 0
    repository = min(10, math.log10(float(item.metrics.get("stars", 0)) + 1) * 3)
    return authority + freshness + specificity + item.source_weight * 5 + repository, item.id


def shortlist_candidates(
    candidates: list[Candidate], now: datetime, limit: int = 20
) -> list[Candidate]:
    effective_limit = max(0, min(limit, 20))
    eligible = []
    for item in candidates:
        text = f"{item.title} {item.summary}"
        if not SPECIFIC.search(text):
            continue
        if WEAK_ONLY.search(text) and not re.search(r"\d|\b(?:api|sdk|v\d)\b", text, re.I):
            continue
        eligible.append(item)
    return sorted(eligible, key=lambda item: (-_rough_score(item, now)[0], item.id))[
        :effective_limit
    ]
