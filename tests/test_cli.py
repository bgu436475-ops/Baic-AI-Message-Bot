from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ai_news_bot import cli
from ai_news_bot.collectors import (
    AllCollectorsUnavailableError,
    CollectionOutcome,
)
from ai_news_bot.config import Settings, SourcesConfig
from ai_news_bot.event_history import DuplicateAssessment
from ai_news_bot.history import HistoryStore
from ai_news_bot.models import (
    Candidate,
    ChangeFact,
    DigestBoards,
    EditorialDigest,
    EditorialNewsItem,
    EvidenceAnchor,
    EvidenceRecord,
    GlobalPipelineStats,
    PipelineStats,
    ScoreBreakdown,
    TechnicalDigestSlice,
)
from ai_news_bot.pipeline import (
    PipelineAudit,
    PipelineDependencies,
    PipelineResult,
)
from ai_news_bot.source_fetcher import FetchedSource


NOW = datetime(2026, 7, 23, 1, 5, tzinfo=UTC)


def _args(
    web_output: Path,
    *,
    dry_run: bool = True,
) -> argparse.Namespace:
    return argparse.Namespace(
        sources=Path("config/sources.yaml"),
        dry_run=dry_run,
        skip_ai=False,
        lookback_hours=None,
        web_output=web_output,
        send_existing=False,
        log_level="INFO",
    )


def _settings(tmp_path: Path) -> Settings:
    state = tmp_path / "state"
    return Settings(
        openai_api_key="test-key",
        state_path=state / "history.json",
        event_history_path=state / "events.json",
        send_ledger_path=state / "daily_sends.json",
        audit_path=state / "latest_audit.json",
        max_candidates=10,
    )


def _candidate() -> Candidate:
    return Candidate(
        id="one",
        title="Model-X API v2 costs $1",
        summary="The SDK v2 is now available.",
        url="https://example.com/one",
        source="Example",
        source_tier=1,
        source_weight=1,
        published_at=NOW,
    )


def _score() -> ScoreBreakdown:
    return ScoreBreakdown(
        relevance=25,
        actionability=20,
        specificity=15,
        information_gain=15,
        evidence_quality=15,
        time_sensitivity=10,
    )


def _published_digest() -> EditorialDigest:
    item = EditorialNewsItem(
        candidate_id="one",
        board="must_read",
        original_title="Model-X API v2 costs $1",
        title_zh="Model-X API v2 发布",
        summary_zh="Model-X API v2 已发布。",
        concrete_change="Model-X API v2 costs $1.",
        affected_audience=["API developers"],
        affected_area=["integration costs"],
        recommended_action=["Test API v2"],
        evidence_url="https://example.com/one?utm_source=test",
        verification_status="verified",
        event_fingerprint="acme|model-x|api-release|v2-$1|",
        primary_entity="Acme",
        event_entities=["Acme", "Model-X"],
        change_signature="api-release",
        version_or_metric="v2-$1",
        resource_available=True,
        scientific_verified=False,
        source="Example",
        published_at=NOW,
        category="ai_coding",
        score=_score(),
    )
    return EditorialDigest(
        generated_at=NOW,
        candidate_count=1,
        source_count=1,
        daily_narrative_zh="今天有一条技术情报通过核验。",
        global_pipeline_stats=GlobalPipelineStats(
            candidate_count=0,
            shortlist_count=0,
            source_verified_count=0,
            rejected_count=0,
        ),
        boards=DigestBoards(must_read=[item]),
        items=[item],
        pipeline_stats=PipelineStats(
            candidate_count=1,
            shortlist_count=1,
            source_verified_count=1,
            rejected_count=0,
        ),
    )


def _legal_empty_digest() -> EditorialDigest:
    return EditorialDigest(
        run_status="no_qualifying_items",
        generated_at=NOW,
        candidate_count=1,
        source_count=1,
        daily_narrative_zh="今天没有技术情报通过核验。",
        global_pipeline_stats=GlobalPipelineStats(
            candidate_count=0,
            shortlist_count=0,
            source_verified_count=0,
            rejected_count=0,
        ),
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=1,
            shortlist_count=1,
            source_verified_count=1,
            rejected_count=1,
            top_rejection_reasons={"missing_action": 1},
        ),
    )


def _result(digest: EditorialDigest) -> PipelineResult:
    return PipelineResult(
        digest=TechnicalDigestSlice(
            generated_at=digest.generated_at,
            candidate_count=digest.candidate_count,
            source_count=digest.source_count,
            lookback_hours=digest.lookback_hours,
            fallback_used=digest.fallback_used,
            boards=digest.boards,
            items=digest.items,
            pipeline_stats=digest.pipeline_stats,
        ),
        audit=PipelineAudit(
            generated_at=NOW,
            entries=[],
            rejected=[],
            rejection_reason_counts={},
        ),
    )


def _send_existing_args(web_output: Path) -> argparse.Namespace:
    args = _args(web_output)
    args.send_existing = True
    return args


class _OutcomeCollector:
    def __init__(self, outcome: CollectionOutcome) -> None:
        self.outcome = outcome

    def collect_with_health(self, *args, **kwargs) -> CollectionOutcome:
        return self.outcome


def _install_collection_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rss: CollectionOutcome,
    web: CollectionOutcome,
    github: CollectionOutcome,
) -> None:
    monkeypatch.setattr(
        cli,
        "RSSCollector",
        lambda **kwargs: _OutcomeCollector(rss),
    )
    monkeypatch.setattr(
        cli,
        "WebPageCollector",
        lambda **kwargs: _OutcomeCollector(web),
    )
    monkeypatch.setattr(
        cli,
        "GitHubCollector",
        lambda **kwargs: _OutcomeCollector(github),
    )


def test_collection_health_raises_when_every_configured_source_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_collection_outcomes(
        monkeypatch,
        rss=CollectionOutcome(candidates=[], attempted=1, succeeded=0),
        web=CollectionOutcome(candidates=[], attempted=1, succeeded=0),
        github=CollectionOutcome(candidates=[], attempted=1, succeeded=0),
    )

    with pytest.raises(
        AllCollectorsUnavailableError,
        match="all 3 configured sources/queries failed",
    ):
        cli._collect_candidates(
            SourcesConfig(rss=[]),
            _settings(tmp_path),
            36,
            include_github=True,
        )


def test_collection_health_accepts_partial_success_with_zero_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_collection_outcomes(
        monkeypatch,
        rss=CollectionOutcome(candidates=[], attempted=1, succeeded=0),
        web=CollectionOutcome(candidates=[], attempted=1, succeeded=1),
        github=CollectionOutcome(candidates=[], attempted=0, succeeded=0),
    )

    outcome = cli._collect_candidates(
        SourcesConfig(rss=[]),
        _settings(tmp_path),
        36,
        include_github=True,
    )

    assert outcome == CollectionOutcome(
        candidates=[],
        attempted=2,
        succeeded=1,
    )


def test_collection_health_keeps_candidates_from_successful_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_collection_outcomes(
        monkeypatch,
        rss=CollectionOutcome(
            candidates=[_candidate()],
            attempted=1,
            succeeded=1,
        ),
        web=CollectionOutcome(candidates=[], attempted=1, succeeded=0),
        github=CollectionOutcome(candidates=[], attempted=0, succeeded=0),
    )

    outcome = cli._collect_candidates(
        SourcesConfig(rss=[]),
        _settings(tmp_path),
        36,
        include_github=True,
    )

    assert outcome.candidates == [_candidate()]
    assert outcome.attempted == 2
    assert outcome.succeeded == 1


def test_collection_health_allows_no_configured_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_collection_outcomes(
        monkeypatch,
        rss=CollectionOutcome(candidates=[], attempted=0, succeeded=0),
        web=CollectionOutcome(candidates=[], attempted=0, succeeded=0),
        github=CollectionOutcome(candidates=[], attempted=0, succeeded=0),
    )

    outcome = cli._collect_candidates(
        SourcesConfig(rss=[]),
        _settings(tmp_path),
        36,
        include_github=True,
    )

    assert outcome.attempted == 0
    assert outcome.succeeded == 0


def test_prepare_candidates_enforces_hard_eighty_at_call_site(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = [
        _candidate().model_copy(
            update={
                "id": f"candidate-{index}",
                "title": (
                    f"Product-{index} API v{index} costs ${index + 1}"
                ),
                "url": f"https://example.com/{index}",
            }
        )
        for index in range(100)
    ]
    monkeypatch.setattr(cli, "hard_dedupe", lambda candidates: candidates)

    retained = cli._prepare_candidates(
        values,
        HistoryStore(tmp_path / "history.json"),
        max_candidates=200,
        now=NOW,
    )

    assert len(retained) == 80


def test_parse_args_rejects_legacy_target_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["ai-news-bot", "--target-count", "5"],
    )

    with pytest.raises(SystemExit) as error:
        cli.parse_args()

    assert error.value.code == 2


def test_fallback_expands_only_when_current_shortlist_is_empty() -> None:
    qualifying = _candidate()
    nonspecific = qualifying.model_copy(
        update={
            "id": "nonspecific",
            "title": "AI industry thoughts",
            "summary": "A broad discussion of future potential.",
            "url": "https://example.com/nonspecific",
        }
    )

    assert not cli._should_expand_lookback([qualifying], NOW)
    assert cli._should_expand_lookback([nonspecific], NOW)
    assert cli._should_expand_lookback([], NOW)


def test_run_keeps_older_strong_candidate_ahead_of_eighty_current_weak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    collected_at = datetime.now(UTC)
    alphabetic_hash = str.maketrans(
        "0123456789abcdef",
        "ghijklmnopqrstuv",
    )
    current_weak = [
        _candidate().model_copy(
            update={
                "id": f"current-weak-{index:02d}",
                "title": sha256(
                    str(index).encode()
                ).hexdigest().translate(
                    alphabetic_hash
                ),
                "summary": "General commentary without a concrete change.",
                "url": f"https://example.com/current/{index:02d}",
                "published_at": collected_at - timedelta(minutes=index),
            }
        )
        for index in range(80)
    ]
    older_strong = _candidate().model_copy(
        update={
            "id": "older-strong",
            "url": "https://example.com/older-strong",
            "published_at": collected_at - timedelta(days=3),
        }
    )
    outcomes = iter(
        [
            CollectionOutcome(
                candidates=current_weak,
                attempted=1,
                succeeded=1,
            ),
            CollectionOutcome(
                candidates=[older_strong],
                attempted=1,
                succeeded=1,
            ),
        ]
    )
    settings = _settings(tmp_path).model_copy(
        update={"max_candidates": 80}
    )
    web_output = tmp_path / "fallback.json"

    def fetched_sources(values: list[Candidate]) -> list[FetchedSource]:
        return [
            FetchedSource(
                candidate_id=value.id,
                requested_url=value.url,
                final_url=value.url,
                status="verified",
                status_code=200,
                title=value.title,
                text=(
                    "Model-X API v2 is available now for one dollar."
                ),
                fetched_at=collected_at,
            )
            for value in values
        ]

    def extract(
        candidate: Candidate,
        source: FetchedSource,
        original_source: FetchedSource | None,
    ) -> EvidenceRecord:
        return _model_record().model_copy(
            update={
                "candidate_id": candidate.id,
                "source_url": candidate.url,
            }
        )

    dependencies = PipelineDependencies(
        shortlist=cli.shortlist_candidates,
        source_fetcher=SimpleNamespace(fetch_many=fetched_sources),
        extract=extract,
        gates=cli.evaluate_gates,
        classify=lambda record, now: DuplicateAssessment(
            status="unique"
        ),
        score=lambda record, assessment, published_at, now: _score(),
        boards=cli.build_boards,
        lookback_hours=settings.fallback_lookback_hours,
        fallback_used=True,
    )
    monkeypatch.setattr(cli.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(
        cli,
        "load_sources",
        lambda path: SourcesConfig(rss=[]),
    )
    monkeypatch.setattr(
        cli,
        "_collect_candidates",
        lambda *args, **kwargs: next(outcomes),
    )
    monkeypatch.setattr(
        cli,
        "_build_pipeline_dependencies",
        lambda *args, **kwargs: dependencies,
    )

    assert cli.run(_args(web_output)) == 0

    digest = EditorialDigest.model_validate_json(
        web_output.read_text(encoding="utf-8")
    )
    assert digest.candidate_count == 80
    assert digest.fallback_used is True
    assert [
        item.candidate_id
        for item in digest.boards.must_read
    ] == ["older-strong"]


class _PipelineHTTPResponse:
    url = "https://example.com/one?token=private"
    status_code = 200
    headers = {"content-type": "text/html; charset=utf-8"}

    def iter_content(self, *, chunk_size: int):
        body = (
            "<html><head><title>Model-X release</title></head><body>"
            "<p>Model-X API v2 is available now for one dollar.</p>"
            "<p>The SDK is available today for API developers worldwide.</p>"
            "</body></html>"
        ).encode()
        yield body

    def raise_for_status(self) -> None:
        return None

    def close(self) -> None:
        return None


class _PipelineHTTPSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, target, **kwargs):
        self.calls.append(target.url)
        return _PipelineHTTPResponse()

    @staticmethod
    def resolve(hostname: str, port: int) -> list[str]:
        return ["93.184.216.34"]


class _PipelineModelClient:
    def __init__(self, record: EvidenceRecord) -> None:
        self.record = record
        self.interfaces: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.responses = SimpleNamespace(parse=self._responses_parse)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(parse=self._chat_parse)
        )

    def _responses_parse(self, **kwargs: Any) -> SimpleNamespace:
        self.interfaces.append("responses")
        self.requests.append(kwargs)
        return SimpleNamespace(output_parsed=self.record)

    def _chat_parse(self, **kwargs: Any) -> SimpleNamespace:
        self.interfaces.append("chat")
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(parsed=self.record)
                )
            ]
        )


class _PipelineEventStore:
    def __init__(self) -> None:
        self.classified: list[str] = []

    def classify(
        self,
        record: EvidenceRecord,
        now: datetime,
    ) -> DuplicateAssessment:
        self.classified.append(record.candidate_id)
        return DuplicateAssessment(status="unique")

    def classify_global(
        self,
        record: Any,
        now: datetime,
    ) -> DuplicateAssessment:
        self.classified.append(record.candidate_id)
        return DuplicateAssessment(status="unique")


def _model_record() -> EvidenceRecord:
    return EvidenceRecord(
        candidate_id="one",
        title_zh="Model-X API v2 发布",
        summary_zh="Model-X API v2 已开放，价格为一美元。",
        category="ai_coding",
        source_url="https://model.invalid/hallucinated",
        source_type="official_announcement",
        verification_status="verified",
        concrete_changes=[
            ChangeFact(
                change_type="release",
                statement=(
                    "Model-X API v2 is available now for one dollar."
                ),
                numbers=["v2", "$1"],
                entities=["Model-X"],
            )
        ],
        evidence_anchors=[
            EvidenceAnchor(
                quote=(
                    "Model-X API v2 is available now for one dollar."
                ),
                locator="release paragraph",
            )
        ],
        affected_audience=["API developers"],
        affected_area=["integration"],
        recommended_action=["Test API v2 this week"],
        event_entities=["Acme", "Model-X"],
        primary_entity="Acme",
        product_or_model="Model-X",
        change_signature="api-release",
        version_or_metric="v2-$1",
        relevance_signal="direct",
        action_horizon_days=3,
        resource_available=True,
    )


@pytest.mark.parametrize(
    (
        "backend",
        "expected_base_url",
        "expected_interface",
        "expected_model",
        "expected_chat_options",
    ),
    [
        (
            "openai",
            None,
            "responses",
            "gpt-5.6-luna",
            {},
        ),
        (
            "cloudflare",
            "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1",
            "chat",
            "@cf/meta/llama-3.1-8b-instruct-fast",
            {},
        ),
        (
            "ollama",
            "http://127.0.0.1:11434/v1",
            "chat",
            "qwen3:8b",
            {"temperature": 0, "extra_body": {"think": False}},
        ),
    ],
)
def test_production_pipeline_wiring_uses_backend_adapter_and_real_stages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    backend: str,
    expected_base_url: str | None,
    expected_interface: str,
    expected_model: str,
    expected_chat_options: dict[str, Any],
) -> None:
    settings = _settings(tmp_path).model_copy(
        update={
            "openai_api_key": (
                "openai-key" if backend == "openai" else ""
            ),
            "cloudflare_account_id": (
                "account-123" if backend == "cloudflare" else ""
            ),
            "cloudflare_ai_api_token": (
                "cf-token" if backend == "cloudflare" else ""
            ),
            "ai_backend_name": "ollama" if backend == "ollama" else "",
            "ollama_base_url": (
                "http://127.0.0.1:11434/v1" if backend == "ollama" else ""
            ),
            "ollama_model": "qwen3:8b" if backend == "ollama" else "",
        }
    )
    web_output = tmp_path / f"{backend}.json"
    session = _PipelineHTTPSession()
    model_client = _PipelineModelClient(_model_record())
    event_store = _PipelineEventStore()
    constructor_calls: list[dict[str, Any]] = []

    def openai_constructor(**kwargs: Any) -> _PipelineModelClient:
        constructor_calls.append(kwargs)
        return model_client

    monkeypatch.setattr(cli.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(
        cli,
        "load_sources",
        lambda path: SourcesConfig(rss=[]),
    )
    monkeypatch.setattr(
        cli,
        "_collect_candidates",
        lambda *args, **kwargs: CollectionOutcome(
            candidates=[_candidate()],
            attempted=1,
            succeeded=1,
        ),
    )
    monkeypatch.setattr(cli, "OpenAI", openai_constructor)
    monkeypatch.setattr(
        "ai_news_bot.source_fetcher.PinnedHTTPSTransport",
        lambda: session,
    )
    monkeypatch.setattr(
        cli,
        "EventHistoryStore",
        lambda path: event_store,
    )

    assert cli.run(_args(web_output)) == 0

    payload = json.loads(web_output.read_text(encoding="utf-8"))
    assert payload["run_status"] == "published"
    assert payload["items"][0]["candidate_id"] == "one"
    assert constructor_calls == [
        {
            "api_key": (
                "openai-key"
                if backend == "openai"
                else ("cf-token" if backend == "cloudflare" else "ollama")
            ),
            "base_url": expected_base_url,
        }
    ]
    assert model_client.interfaces == [expected_interface]
    assert model_client.requests[0]["model"] == expected_model
    for key, value in expected_chat_options.items():
        assert model_client.requests[0][key] == value
    assert event_store.classified == ["one"]
    assert session.calls == [_candidate().url]


@pytest.mark.parametrize("dry_run", [True, False])
def test_generation_writes_schema_v4_digest_and_private_audit_without_sending_or_state_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dry_run: bool,
) -> None:
    web_output = tmp_path / "latest.json"
    settings = _settings(tmp_path)
    pipeline_calls: list[list[Candidate]] = []
    dependencies = object()
    monkeypatch.setattr(cli.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(
        cli,
        "load_sources",
        lambda path: SourcesConfig(rss=[]),
    )
    monkeypatch.setattr(
        cli,
        "_collect_candidates",
        lambda *args, **kwargs: CollectionOutcome(
            candidates=[_candidate()],
            attempted=1,
            succeeded=1,
        ),
    )
    monkeypatch.setattr(
        cli,
        "_build_pipeline_dependencies",
        lambda *args, **kwargs: dependencies,
    )

    def run_pipeline(values, dependencies, now):
        pipeline_calls.append(values)
        return _result(_published_digest())

    monkeypatch.setattr(cli, "run_editorial_pipeline", run_pipeline)
    monkeypatch.setattr(
        cli,
        "send_to_feishu",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("generation must not send")
        ),
    )
    monkeypatch.setattr(
        cli.SendLedger,
        "record_success",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("generation must not mutate ledger")
        ),
    )
    monkeypatch.setattr(
        cli.HistoryStore,
        "record_digest",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("generation must not mutate URL history")
        ),
    )
    monkeypatch.setattr(
        cli.EventHistoryStore,
        "record_digest",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("generation must not mutate event history")
        ),
    )

    assert cli.run(_args(web_output, dry_run=dry_run)) == 0

    assert pipeline_calls == [[_candidate()]]
    assert json.loads(web_output.read_text(encoding="utf-8"))[
        "schema_version"
    ] == 4
    assert settings.audit_path.exists()


def test_send_existing_records_success_then_nonempty_histories_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = _published_digest()
    web_output = tmp_path / "latest.json"
    web_output.write_text(digest.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: _settings(tmp_path),
    )
    events: list[str] = []
    monkeypatch.setattr(
        cli,
        "send_to_feishu",
        lambda value, *args: events.append("send"),
    )
    monkeypatch.setattr(
        cli.SendLedger,
        "record_success",
        lambda self, value, target, now=None: events.append("ledger"),
    )
    monkeypatch.setattr(
        cli.HistoryStore,
        "record_digest",
        lambda self, items: events.append("url-history"),
    )
    monkeypatch.setattr(
        cli.EventHistoryStore,
        "record_digest",
        lambda self, value: events.append("event-history"),
    )

    assert cli.run(_send_existing_args(web_output)) == 0

    assert events == [
        "send",
        "ledger",
        "url-history",
        "event-history",
    ]


def test_send_existing_sends_empty_card_and_records_daily_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = _legal_empty_digest()
    output = tmp_path / "latest.json"
    output.write_text(digest.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: _settings(tmp_path),
    )
    sent: list[EditorialDigest] = []
    ledger: list[str] = []
    histories: list[str] = []
    monkeypatch.setattr(
        cli,
        "send_to_feishu",
        lambda value, *args: sent.append(value),
    )
    monkeypatch.setattr(
        cli.SendLedger,
        "record_success",
        lambda self, value, target, now=None: ledger.append(
            value.run_status
        ),
    )
    monkeypatch.setattr(
        cli.HistoryStore,
        "record_digest",
        lambda *args: histories.append("url"),
    )
    monkeypatch.setattr(
        cli.EventHistoryStore,
        "record_digest",
        lambda *args: histories.append("event"),
    )

    assert cli.run(_send_existing_args(output)) == 0

    assert sent == [digest]
    assert ledger == ["no_qualifying_items"]
    assert histories == []


def test_send_existing_daily_result_returns_the_persisted_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = _published_digest()
    output = tmp_path / "latest.json"
    output.write_text(digest.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "send_to_feishu", lambda *args: None)
    monkeypatch.setattr(cli.SendLedger, "record_success", lambda *args: None)
    monkeypatch.setattr(cli.HistoryStore, "record_digest", lambda *args: None)
    monkeypatch.setattr(
        cli.EventHistoryStore,
        "record_digest",
        lambda *args: None,
    )

    assert cli.send_existing_daily_result(output, _settings(tmp_path)) == digest


def test_feishu_failure_does_not_record_any_success_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "latest.json"
    output.write_text(
        _published_digest().model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: _settings(tmp_path),
    )
    recorded: list[str] = []
    monkeypatch.setattr(
        cli,
        "send_to_feishu",
        lambda *args: (_ for _ in ()).throw(
            RuntimeError("Feishu down")
        ),
    )
    monkeypatch.setattr(
        cli.SendLedger,
        "record_success",
        lambda *args: recorded.append("ledger"),
    )
    monkeypatch.setattr(
        cli.HistoryStore,
        "record_digest",
        lambda *args: recorded.append("url"),
    )
    monkeypatch.setattr(
        cli.EventHistoryStore,
        "record_digest",
        lambda *args: recorded.append("event"),
    )

    with pytest.raises(RuntimeError, match="Feishu down"):
        cli.run(_send_existing_args(output))

    assert recorded == []


@pytest.mark.parametrize(
    ("url_history_fails", "event_history_fails"),
    [
        (True, False),
        (False, True),
        (True, True),
    ],
)
def test_post_send_history_failures_do_not_erase_delivery_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    url_history_fails: bool,
    event_history_fails: bool,
) -> None:
    output = tmp_path / "latest.json"
    output.write_text(
        _published_digest().model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: _settings(tmp_path),
    )
    events: list[str] = []
    monkeypatch.setattr(
        cli,
        "send_to_feishu",
        lambda *args: events.append("send"),
    )
    monkeypatch.setattr(
        cli.SendLedger,
        "record_success",
        lambda *args: events.append("ledger"),
    )

    def record_urls(*args) -> None:
        events.append("url")
        if url_history_fails:
            raise OSError("URL history unavailable")

    def record_events(*args) -> None:
        events.append("event")
        if event_history_fails:
            raise OSError("event history unavailable")

    monkeypatch.setattr(cli.HistoryStore, "record_digest", record_urls)
    monkeypatch.setattr(
        cli.EventHistoryStore,
        "record_digest",
        record_events,
    )

    assert cli.run(_send_existing_args(output)) == 0

    assert events == ["send", "ledger", "url", "event"]
    if url_history_fails:
        assert "Could not record sent URL history" in caplog.text
    if event_history_fails:
        assert "Could not record sent event history" in caplog.text


def test_ledger_failure_after_feishu_stops_before_noncritical_histories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "latest.json"
    output.write_text(
        _published_digest().model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: _settings(tmp_path),
    )
    events: list[str] = []
    monkeypatch.setattr(
        cli,
        "send_to_feishu",
        lambda *args: events.append("send"),
    )

    def ledger_failure(*args) -> None:
        events.append("ledger")
        raise OSError("ledger replace failed")

    monkeypatch.setattr(
        cli.SendLedger,
        "record_success",
        ledger_failure,
    )
    monkeypatch.setattr(
        cli.HistoryStore,
        "record_digest",
        lambda *args: events.append("url"),
    )
    monkeypatch.setattr(
        cli.EventHistoryStore,
        "record_digest",
        lambda *args: events.append("event"),
    )

    with pytest.raises(OSError, match="ledger replace failed"):
        cli.run(_send_existing_args(output))

    assert events == ["send", "ledger"]


@pytest.mark.parametrize("payload", ["not json", "{}", "schema-v2"])
def test_send_existing_rejects_missing_or_invalid_schema_v3_result_before_feishu(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: str,
) -> None:
    web_output = tmp_path / "latest.json"
    if payload == "schema-v2":
        payload = json.dumps(
            {
                "schema_version": 2,
                "run_status": "no_qualifying_items",
                "generated_at": NOW.isoformat(),
                "candidate_count": 0,
                "source_count": 0,
                "items": [],
            }
        )
    if payload != "{}":
        web_output.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: _settings(tmp_path),
    )
    monkeypatch.setattr(
        cli,
        "send_to_feishu",
        lambda *args: (_ for _ in ()).throw(AssertionError()),
    )

    with pytest.raises(ValueError, match="persisted daily result"):
        cli.run(_send_existing_args(web_output))


def test_history_records_editorial_evidence_url_canonically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.json"
    digest = _published_digest()

    HistoryStore(path).record(digest.items, now=NOW)

    assert HistoryStore(path).contains(
        "https://example.com/one",
        now=NOW,
    )
    stored = json.loads(path.read_text(encoding="utf-8"))["sent"]
    assert list(stored) == ["https://example.com/one"]
