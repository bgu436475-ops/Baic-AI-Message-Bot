from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .collectors import GitHubCollector, RSSCollector, WebPageCollector
from .config import Settings, load_sources
from .curator import build_digest, select_with_openai, select_without_ai
from .dedupe import hard_dedupe
from .feishu import digest_markdown, send_to_feishu
from .history import HistoryStore
from .web_export import export_digest_for_web

LOGGER = logging.getLogger(__name__)


def _collect_candidates(sources, settings: Settings, lookback_hours: int, *, include_github: bool) -> list:
    collected = RSSCollector(timeout=settings.request_timeout).collect(
        sources.rss, lookback_hours
    )
    collected += WebPageCollector(timeout=settings.request_timeout).collect(
        sources.webpages, lookback_hours
    )
    if include_github:
        collected += GitHubCollector(
            token=settings.github_token, timeout=settings.request_timeout
        ).collect(sources.github)
    return collected


def _prepare_candidates(collected: list, history: HistoryStore, max_candidates: int) -> list:
    unseen = [candidate for candidate in collected if not history.contains(candidate.url)]
    unique = hard_dedupe(unseen)
    return sorted(
        unique,
        key=lambda item: (item.published_at, item.source_weight),
        reverse=True,
    )[:max_candidates]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and send the daily AI news digest")
    parser.add_argument("--sources", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="Generate but do not send")
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Preview with deterministic ranking; no Chinese rewrite or semantic dedupe",
    )
    parser.add_argument("--target-count", type=int, default=None)
    parser.add_argument("--lookback-hours", type=int, default=None)
    parser.add_argument(
        "--web-output",
        type=Path,
        default=Path("web/public/data/latest.json"),
        help="Write the digest JSON consumed by the website",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if args.target_count is not None:
        settings.target_news_count = args.target_count
    if args.lookback_hours is not None:
        settings.lookback_hours = args.lookback_hours
    sources = load_sources(args.sources)
    history = HistoryStore(settings.state_path)

    collected = _collect_candidates(
        sources, settings, settings.lookback_hours, include_github=True
    )
    unique = _prepare_candidates(collected, history, settings.max_candidates)
    fallback_used = False

    if (
        len(unique) < settings.target_news_count
        and settings.fallback_lookback_hours > settings.lookback_hours
    ):
        LOGGER.info(
            "Only %d current candidate(s); expanding lookback from %d to %d hours",
            len(unique),
            settings.lookback_hours,
            settings.fallback_lookback_hours,
        )
        older = _collect_candidates(
            sources,
            settings,
            settings.fallback_lookback_hours,
            include_github=False,
        )
        collected = hard_dedupe(collected + older)
        unique = _prepare_candidates(collected, history, settings.max_candidates)
        fallback_used = True
    LOGGER.info(
        "Collected %d; %d unseen unique candidate(s) remain", len(collected), len(unique)
    )

    if not unique:
        LOGGER.warning("No fresh AI news candidates; no message sent")
        return 0

    if args.skip_ai:
        items = select_without_ai(unique, settings.target_news_count)
    else:
        items = select_with_openai(
            unique,
            settings.target_news_count,
            settings.openai_api_key,
            settings.openai_model,
        )
    if not items:
        LOGGER.warning("Curation returned no items; no message sent")
        return 0

    digest = build_digest(
        unique,
        items,
        lookback_hours=(
            settings.fallback_lookback_hours if fallback_used else settings.lookback_hours
        ),
        fallback_used=fallback_used,
    )
    latest_path = settings.state_path.parent / "latest_digest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(digest.model_dump_json(indent=2), encoding="utf-8")
    export_digest_for_web(digest, args.web_output)
    print(digest_markdown(digest))

    if args.dry_run:
        LOGGER.info("Dry run complete; Feishu was not called and history was not changed")
        return 0

    send_to_feishu(
        digest,
        settings.feishu_webhook_url,
        settings.feishu_signing_secret,
        settings.request_timeout,
    )
    history.record(digest.items)
    LOGGER.info("Sent %d item(s) to Feishu", len(digest.items))
    return 0


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(run(args))
