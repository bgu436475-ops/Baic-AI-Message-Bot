from __future__ import annotations

from difflib import SequenceMatcher

from .models import Candidate
from .text import canonicalize_url, normalized_title


def _title_tokens(value: str) -> set[str]:
    return {token for token in normalized_title(value).split() if len(token) > 1}


def _titles_similar(left: str, right: str) -> bool:
    left_norm = normalized_title(left)
    right_norm = normalized_title(right)
    if not left_norm or not right_norm:
        return False
    if SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.90:
        return True
    left_tokens, right_tokens = _title_tokens(left), _title_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) >= 0.82


def _priority(candidate: Candidate) -> tuple[float, float, float]:
    stars = float(candidate.metrics.get("stars", 0))
    return (-candidate.source_tier, candidate.source_weight, stars)


def hard_dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """Remove exact and near-exact duplicates, keeping the most authoritative item."""
    ordered = sorted(candidates, key=_priority, reverse=True)
    kept: list[Candidate] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    for candidate in ordered:
        url = canonicalize_url(candidate.url)
        title = normalized_title(candidate.title)
        if url in seen_urls or (title and title in seen_titles):
            continue
        if any(_titles_similar(candidate.title, item.title) for item in kept):
            continue
        seen_urls.add(url)
        if title:
            seen_titles.add(title)
        kept.append(candidate)
    return kept

