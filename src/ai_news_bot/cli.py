from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from .boards import build_boards
from .collectors import (
    AllCollectorsUnavailableError,
    CollectionOutcome,
    GitHubCollector,
    RSSCollector,
    WebPageCollector,
)
from .config import Settings, load_sources
from .dedupe import hard_dedupe
from .event_history import EventHistoryStore
from .evidence import extract_evidence
from .feishu import send_to_feishu
from .gatekeeper import evaluate_gates
from .global_editor import extract_global_event
from .global_pipeline import (
    GlobalPipelineDependencies,
    run_global_pipeline,
)
from .global_rules import (
    corroborate_global_records,
    evaluate_global_event,
    score_global_event,
    select_global_events,
)
from .global_shortlist import shortlist_global_candidates
from .history import HistoryStore
from .models import Candidate, EditorialDigest
from .briefing import compose_daily_briefing
from .pipeline import (
    PipelineDependencies,
    run_editorial_pipeline,
)
from .scoring import score_record
from .send_ledger import SendLedger
from .shortlist import shortlist_candidates
from .source_fetcher import SourceFetcher
from .web_export import export_digest_for_web

LOGGER = logging.getLogger(__name__)
ModelClientProvider = Callable[[], tuple[Any, str, str | None]]


def _collect_candidates(
    sources,
    settings: Settings,
    lookback_hours: int,
    *,
    include_github: bool,
) -> CollectionOutcome:
    outcomes = [
        RSSCollector(timeout=settings.request_timeout).collect_with_health(
            sources.rss,
            lookback_hours,
        ),
        WebPageCollector(
            timeout=settings.request_timeout
        ).collect_with_health(
            sources.webpages,
            lookback_hours,
        ),
    ]
    if include_github:
        outcomes.append(
            GitHubCollector(
                token=settings.github_token,
                timeout=settings.request_timeout,
            ).collect_with_health(sources.github)
        )
    outcome = CollectionOutcome(
        candidates=[
            candidate
            for value in outcomes
            for candidate in value.candidates
        ],
        attempted=sum(value.attempted for value in outcomes),
        succeeded=sum(value.succeeded for value in outcomes),
    )
    if outcome.attempted > 0 and outcome.succeeded == 0:
        raise AllCollectorsUnavailableError(
            f"all {outcome.attempted} configured sources/queries failed"
        )
    return outcome


def _prepare_candidates(
    collected: list,
    history: HistoryStore,
    max_candidates: int,
    now: datetime,
) -> list:
    unseen = [
        candidate
        for candidate in collected
        if not history.contains(candidate.url, now)
    ]
    unique = hard_dedupe(unseen)
    return sorted(
        unique,
        key=lambda item: (item.published_at, item.source_weight),
        reverse=True,
    )[: max(0, min(max_candidates, 80))]


def _should_expand_lookback(
    candidates: list,
    now: datetime,
) -> bool:
    return not shortlist_candidates(candidates, now)


def _merge_fallback_candidates(
    current: list[Candidate],
    older: list[Candidate],
    history: HistoryStore,
    max_candidates: int,
    now: datetime,
) -> list[Candidate]:
    cap = max(0, min(max_candidates, 80))
    unseen = [
        candidate
        for candidate in current + older
        if not history.contains(candidate.url, now)
    ]
    unique = hard_dedupe(unseen)
    priority = shortlist_candidates(unique, now)
    priority_ids = {candidate.id for candidate in priority}
    remaining = sorted(
        (
            candidate
            for candidate in unique
            if candidate.id not in priority_ids
        ),
        key=lambda candidate: (
            -candidate.published_at.timestamp(),
            -candidate.source_weight,
            candidate.id,
        ),
    )
    return (priority + remaining)[:cap]


def _build_pipeline_dependencies(
    settings: Settings,
    event_history: EventHistoryStore,
    *,
    lookback_hours: int,
    fallback_used: bool,
    client_provider: ModelClientProvider | None = None,
) -> PipelineDependencies:
    get_client = client_provider or _build_model_client_provider(settings)

    def extract(candidate, source, original_source):
        client, model, base_url = get_client()
        return extract_evidence(
            candidate,
            source,
            client,
            model,
            base_url,
            original_source=original_source,
        )

    return PipelineDependencies(
        shortlist=shortlist_candidates,
        source_fetcher=SourceFetcher(timeout=settings.request_timeout),
        extract=extract,
        gates=evaluate_gates,
        classify=event_history.classify,
        score=score_record,
        boards=build_boards,
        lookback_hours=lookback_hours,
        fallback_used=fallback_used,
    )


def _build_model_client_provider(
    settings: Settings,
) -> ModelClientProvider:
    client: OpenAI | None = None
    model = ""
    base_url: str | None = None

    def get_client() -> tuple[Any, str, str | None]:
        nonlocal client, model, base_url
        if client is None:
            api_key, model, base_url, provider = settings.ai_backend()
            LOGGER.info(
                "Extracting structured evidence with %s (%s)",
                provider,
                model,
            )
            client = OpenAI(api_key=api_key, base_url=base_url)
        return client, model, base_url

    return get_client


def _build_global_pipeline_dependencies(
    settings: Settings,
    event_history: EventHistoryStore,
    *,
    client_provider: ModelClientProvider | None = None,
) -> GlobalPipelineDependencies:
    get_client = client_provider or _build_model_client_provider(settings)

    def extract(candidate, source):
        client, model, base_url = get_client()
        return extract_global_event(
            candidate,
            source,
            client,
            model,
            base_url,
        )

    return GlobalPipelineDependencies(
        shortlist=shortlist_global_candidates,
        source_fetcher=SourceFetcher(timeout=settings.request_timeout),
        extract=extract,
        classify=event_history.classify_global,
        corroborate=corroborate_global_records,
        gate=evaluate_global_event,
        score=score_global_event,
        select=select_global_events,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and send the daily AI news digest")
    parser.add_argument("--sources", type=Path, default=Path("config/sources.yaml"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Generate but do not send")
    mode.add_argument(
        "--send-existing",
        action="store_true",
        help="Send a previously persisted daily result without collecting again",
    )
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Unsupported by the evidence-verified editorial pipeline",
    )
    parser.add_argument("--lookback-hours", type=int, default=None)
    parser.add_argument(
        "--web-output",
        type=Path,
        default=Path("web/public/data/latest.json"),
        help="Write the digest JSON consumed by the website",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def _write_digest(
    digest: EditorialDigest,
    settings: Settings,
    web_output: Path,
) -> None:
    latest_path = settings.state_path.parent / "latest_digest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(digest.model_dump_json(indent=2), encoding="utf-8")
    export_digest_for_web(digest, web_output)


def _send_existing_daily_result(args: argparse.Namespace, settings: Settings) -> int:
    try:
        digest = EditorialDigest.model_validate_json(
            args.web_output.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise ValueError("Could not load a valid persisted daily result") from error

    send_to_feishu(
        digest,
        settings.feishu_webhook_url,
        settings.feishu_signing_secret,
        settings.request_timeout,
    )
    SendLedger(settings.send_ledger_path).record_success(
        digest,
        "feishu-daily",
    )
    if digest.items:
        try:
            HistoryStore(settings.state_path).record_digest(digest)
        except Exception as error:
            LOGGER.warning(
                "Could not record sent URL history after successful delivery: %s",
                error,
            )
        try:
            EventHistoryStore(
                settings.event_history_path
            ).record_digest(digest)
        except Exception as error:
            LOGGER.warning(
                "Could not record sent event history after successful delivery: %s",
                error,
            )
    LOGGER.info(
        "Sent %d persisted item(s) to Feishu",
        len(digest.global_events) + len(digest.items),
    )
    return 0


def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if args.send_existing:
        return _send_existing_daily_result(args, settings)
    if args.lookback_hours is not None:
        settings.lookback_hours = args.lookback_hours
    if args.skip_ai:
        raise ValueError(
            "--skip-ai is unavailable for the evidence-verified editorial pipeline"
        )
    sources = load_sources(args.sources)
    history = HistoryStore(settings.state_path)
    generation_now = datetime.now(UTC)

    current_outcome = _collect_candidates(
        sources, settings, settings.lookback_hours, include_github=True
    )
    collected = current_outcome.candidates
    unique = _prepare_candidates(
        collected,
        history,
        settings.max_candidates,
        generation_now,
    )
    fallback_used = False

    if (
        _should_expand_lookback(unique, generation_now)
        and settings.fallback_lookback_hours > settings.lookback_hours
    ):
        LOGGER.info(
            "No current candidate passed shortlist; expanding lookback "
            "from %d to %d hours",
            settings.lookback_hours,
            settings.fallback_lookback_hours,
        )
        try:
            older_outcome = _collect_candidates(
                sources,
                settings,
                settings.fallback_lookback_hours,
                include_github=False,
            )
        except AllCollectorsUnavailableError as error:
            LOGGER.warning(
                "Expanded-lookback collection failed after a healthy "
                "current collection: %s",
                error,
            )
        else:
            unique = _merge_fallback_candidates(
                collected,
                older_outcome.candidates,
                history,
                settings.max_candidates,
                generation_now,
            )
            collected = hard_dedupe(
                collected + older_outcome.candidates
            )
            fallback_used = older_outcome.succeeded > 0
    LOGGER.info(
        "Collected %d; %d unseen unique candidate(s) remain", len(collected), len(unique)
    )
    lookback_hours = (
        settings.fallback_lookback_hours
        if fallback_used
        else settings.lookback_hours
    )
    event_history = EventHistoryStore(settings.event_history_path)
    client_provider = _build_model_client_provider(settings)
    technical_dependencies = _build_pipeline_dependencies(
        settings,
        event_history,
        lookback_hours=lookback_hours,
        fallback_used=fallback_used,
        client_provider=client_provider,
    )
    global_dependencies = _build_global_pipeline_dependencies(
        settings,
        event_history,
        client_provider=client_provider,
    )
    technical = run_editorial_pipeline(
        unique,
        dependencies=technical_dependencies,
        now=generation_now,
    )
    global_result = run_global_pipeline(
        unique,
        dependencies=global_dependencies,
        now=generation_now,
    )
    digest = compose_daily_briefing(
        technical.digest,
        global_result,
        generation_now,
    )
    _write_digest(digest, settings, args.web_output)
    settings.audit_path.parent.mkdir(parents=True, exist_ok=True)
    settings.audit_path.write_text(
        json.dumps(
            {
                "technical": technical.audit.model_dump(mode="json"),
                "global": global_result.audit.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    LOGGER.info(
        "Generated %s editorial result with %d selected item(s); "
        "delivery state was not changed",
        digest.run_status,
        len(digest.global_events) + len(digest.items),
    )
    return 0


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(run(args))
