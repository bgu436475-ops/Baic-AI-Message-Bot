from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_datetime

from .config import GitHubSources, RSSSource, WebPageSource
from .models import Candidate
from .text import canonicalize_url, clean_html, stable_id, truncate

LOGGER = logging.getLogger(__name__)

AI_KEYWORDS = (
    " ai ",
    "artificial intelligence",
    "llm",
    "large language model",
    "gpt",
    "openai",
    "claude",
    "anthropic",
    "gemini",
    "deepmind",
    "llama",
    "qwen",
    "deepseek",
    "mistral",
    "codex",
    "copilot",
    "cursor",
    "agent",
    "model context protocol",
    " mcp ",
    "skill",
    "image generation",
    "video generation",
    "diffusion",
    "comfyui",
    "multimodal",
    "transformer",
    "inference",
    "生成式",
    "人工智能",
    "大模型",
    "智能体",
)


def _entry_datetime(entry: Any, now: datetime) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(attr)
        if value:
            return datetime(*value[:6], tzinfo=UTC)
    for attr in ("published", "updated", "created"):
        value = entry.get(attr)
        if not value:
            continue
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def _looks_ai_related(title: str, summary: str) -> bool:
    haystack = f" {title} {summary} ".lower()
    return any(keyword in haystack for keyword in AI_KEYWORDS)


class RSSCollector:
    def __init__(self, timeout: int = 20, workers: int = 8) -> None:
        self.timeout = timeout
        self.workers = workers

    def collect(
        self, sources: list[RSSSource], lookback_hours: int, now: datetime | None = None
    ) -> list[Candidate]:
        now = now or datetime.now(UTC)
        results: list[Candidate] = []
        with ThreadPoolExecutor(max_workers=min(self.workers, max(1, len(sources)))) as pool:
            futures = {
                pool.submit(self._collect_source, source, lookback_hours, now): source
                for source in sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    items = future.result()
                    results.extend(items)
                    LOGGER.info("%s: collected %d candidate(s)", source.name, len(items))
                except Exception as exc:  # one broken feed must not stop the digest
                    LOGGER.warning("%s: collection failed: %s", source.name, exc)
        return results

    def _collect_source(
        self, source: RSSSource, lookback_hours: int, now: datetime
    ) -> list[Candidate]:
        response = requests.get(
            source.url,
            timeout=self.timeout,
            headers={"User-Agent": "AI-News-Bot/0.1 (+daily digest)"},
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"invalid feed: {parsed.bozo_exception}")

        cutoff = now - timedelta(hours=lookback_hours)
        candidates: list[Candidate] = []
        for entry in parsed.entries[:50]:
            url = entry.get("link", "").strip()
            title = clean_html(entry.get("title", ""), limit=300)
            if not url or not title:
                continue
            published = _entry_datetime(entry, now)
            if published is None:
                LOGGER.debug("%s: skipped undated entry %s", source.name, title)
                continue
            if published < cutoff or published > now + timedelta(hours=6):
                continue
            summary = clean_html(
                entry.get("summary", "")
                or entry.get("description", "")
                or " ".join(part.get("value", "") for part in entry.get("content", []))
            )
            if source.keyword_filter and not _looks_ai_related(title, summary):
                continue
            canonical_url = canonicalize_url(url)
            candidates.append(
                Candidate(
                    id=stable_id(canonical_url),
                    title=title,
                    summary=truncate(summary, 2400),
                    url=canonical_url,
                    source=source.name,
                    source_tier=source.tier,
                    source_weight=source.weight,
                    published_at=published,
                    category_hints=source.category_hints,
                )
            )
        return candidates


class WebPageCollector:
    """Collect structured listing pages for official sources that do not publish RSS."""

    def __init__(self, timeout: int = 20, workers: int = 4) -> None:
        self.timeout = timeout
        self.workers = workers

    def collect(
        self, sources: list[WebPageSource], lookback_hours: int, now: datetime | None = None
    ) -> list[Candidate]:
        now = now or datetime.now(UTC)
        if not sources:
            return []
        results: list[Candidate] = []
        with ThreadPoolExecutor(max_workers=min(self.workers, len(sources))) as pool:
            futures = {
                pool.submit(self._collect_source, source, lookback_hours, now): source
                for source in sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    items = future.result()
                    results.extend(items)
                    LOGGER.info("%s: collected %d candidate(s)", source.name, len(items))
                except Exception as exc:
                    LOGGER.warning("%s: collection failed: %s", source.name, exc)
        return results

    def _collect_source(
        self, source: WebPageSource, lookback_hours: int, now: datetime
    ) -> list[Candidate]:
        response = requests.get(
            source.url,
            timeout=self.timeout,
            headers={"User-Agent": "AI-News-Bot/0.1 (+daily digest)"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        cutoff = now - timedelta(hours=lookback_hours)
        candidates: list[Candidate] = []
        seen_urls: set[str] = set()

        for element in soup.select(source.item_selector):
            href = element.get("href", "").strip()
            title_node = element.select_one(source.title_selector)
            date_node = element.select_one(source.date_selector)
            if not href or title_node is None or date_node is None:
                continue
            url = canonicalize_url(urljoin(source.url, href))
            if url in seen_urls:
                continue
            try:
                published = parse_datetime(date_node.get_text(" ", strip=True))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=UTC)
                published = published.astimezone(UTC)
            except (TypeError, ValueError, OverflowError):
                continue
            if published < cutoff or published > now + timedelta(hours=6):
                continue

            summary_node = (
                element.select_one(source.summary_selector) if source.summary_selector else None
            )
            title = clean_html(title_node.get_text(" ", strip=True), limit=300)
            summary = clean_html(
                summary_node.get_text(" ", strip=True) if summary_node is not None else ""
            )
            if not title:
                continue
            candidates.append(
                Candidate(
                    id=stable_id(url),
                    title=title,
                    summary=truncate(summary, 2400),
                    url=url,
                    source=source.name,
                    source_tier=source.tier,
                    source_weight=source.weight,
                    published_at=published,
                    category_hints=source.category_hints,
                )
            )
            seen_urls.add(url)
        return candidates


class GitHubCollector:
    API_URL = "https://api.github.com/search/repositories"

    def __init__(self, token: str = "", timeout: int = 20) -> None:
        self.token = token
        self.timeout = timeout

    def collect(
        self, config: GitHubSources, now: datetime | None = None
    ) -> list[Candidate]:
        if not config.enabled:
            return []
        now = now or datetime.now(UTC)
        since = (now - timedelta(days=config.lookback_days)).date().isoformat()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AI-News-Bot/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        candidates: list[Candidate] = []
        for query in config.queries:
            try:
                response = requests.get(
                    self.API_URL,
                    params={
                        "q": query.query.format(since=since),
                        "sort": "stars",
                        "order": "desc",
                        "per_page": config.per_query,
                    },
                    headers=headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                LOGGER.warning("GitHub / %s: collection failed: %s", query.name, exc)
                continue

            for repo in response.json().get("items", []):
                url = canonicalize_url(repo["html_url"])
                stars = int(repo.get("stargazers_count", 0))
                forks = int(repo.get("forks_count", 0))
                description = clean_html(repo.get("description") or "", limit=1000)
                summary = f"{description} GitHub: {stars:,} stars, {forks:,} forks.".strip()
                published = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
                candidates.append(
                    Candidate(
                        id=stable_id(url),
                        title=repo["full_name"],
                        summary=summary,
                        url=url,
                        source=f"GitHub · {query.name}",
                        source_tier=2,
                        source_weight=min(1.0, 0.82 + stars / 5000),
                        published_at=published,
                        category_hints=query.category_hints,
                        metrics={"stars": stars, "forks": forks},
                    )
                )
            LOGGER.info("GitHub / %s: collected %d result(s)", query.name, len(response.json().get("items", [])))
        return candidates
