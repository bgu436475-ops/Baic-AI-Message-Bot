from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_news_bot import cli
from ai_news_bot.config import Settings, SourcesConfig
from ai_news_bot.history import HistoryStore
from ai_news_bot.models import (
    Candidate,
    DigestBoards,
    EditorialDigest,
    EditorialNewsItem,
    PipelineStats,
    ScoreBreakdown,
)
from ai_news_bot.pipeline import PipelineAudit, PipelineResult


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
        target_count=None,
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
        target_news_count=1,
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
        digest=digest,
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


@pytest.mark.parametrize("dry_run", [True, False])
def test_generation_writes_schema_v3_digest_and_private_audit_without_sending_or_state_mutation(
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
        lambda *args, **kwargs: [_candidate()],
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
        "record",
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
    ] == 3
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
        "record",
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
        "record",
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
        "record",
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

    assert HistoryStore(path).contains("https://example.com/one")
    stored = json.loads(path.read_text(encoding="utf-8"))["sent"]
    assert list(stored) == ["https://example.com/one"]
