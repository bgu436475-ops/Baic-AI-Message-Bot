from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import pytest

from ai_news_bot.boards import ScoredEditorialCandidate, build_boards
from ai_news_bot.event_history import DuplicateAssessment
from ai_news_bot.evidence import EvidenceExtractionError
from ai_news_bot.gatekeeper import evaluate_gates
from ai_news_bot.models import (
    Candidate,
    ChangeFact,
    EvidenceAnchor,
    EvidenceRecord,
    GateDecision,
    ScoreBreakdown,
)
from ai_news_bot import pipeline as pipeline_module
from ai_news_bot.pipeline import PipelineDependencies, run_editorial_pipeline, write_audit
from ai_news_bot.scoring import score_record
from ai_news_bot.source_fetcher import (
    AllSourcesUnavailableError,
    FetchedSource,
)


NOW = datetime(2026, 7, 23, 1, 5, tzinfo=UTC)
FETCHED_TEXT = "Model-X API v2 is available now for one dollar."


def candidates() -> list[Candidate]:
    return [
        Candidate(
            id=candidate_id,
            title=f"Model-X API v2 launch {candidate_id}",
            summary="The API price is $1 and SDK v2 is available.",
            url=f"https://example.com/{candidate_id}",
            source="Acme",
            source_tier=1,
            source_weight=1,
            published_at=NOW,
            category_hints=["ai_coding"],
        )
        for candidate_id in ("qualifying", "rejected")
    ]


def fetched(candidate: Candidate, *, status: str = "verified") -> FetchedSource:
    return FetchedSource(
        candidate_id=candidate.id,
        requested_url=candidate.url,
        final_url=candidate.url,
        status=status,
        status_code=200 if status == "verified" else 403,
        title=candidate.title,
        text=FETCHED_TEXT if status == "verified" else "",
        fetched_at=NOW,
    )


def evidence(
    candidate: Candidate,
    *,
    source_type: str = "official_announcement",
    original_source_status: str | None = None,
) -> EvidenceRecord:
    is_rejected = candidate.id == "rejected"
    return EvidenceRecord(
        candidate_id=candidate.id,
        title_zh=f"{candidate.id}：Model-X API v2 已发布",
        summary_zh="Model-X API v2 已可使用，价格为一美元。",
        category="ai_coding",
        source_url=candidate.url,
        source_type=source_type,
        verification_status="verified",
        concrete_changes=[
            ChangeFact(
                change_type="release",
                statement="Model-X API v2 is available now for one dollar.",
                numbers=["v2", "$1"],
                entities=["Model-X"],
            )
        ],
        evidence_anchors=[
            EvidenceAnchor(
                quote="Model-X API v2 is available now for one dollar.",
                locator="Release notes / paragraph 2",
            )
        ],
        affected_audience=["API developers"],
        affected_area=["integration"],
        recommended_action=[] if is_rejected else ["Test API v2 this week"],
        event_entities=["Acme", "Model-X"],
        primary_entity="Acme",
        product_or_model="Model-X",
        change_signature="api-release",
        version_or_metric="v2-$1",
        relevance_signal="direct",
        action_horizon_days=3,
        resource_available=True,
        original_source_status=original_source_status,
    )


class FakeFetcher:
    def __init__(
        self,
        trace: list[str],
        *,
        all_fetches_fail: bool = False,
    ) -> None:
        self.trace = trace
        self.all_fetches_fail = all_fetches_fail

    def fetch_many(self, values: list[Candidate]) -> list[FetchedSource]:
        self.trace.append("fetch")
        if self.all_fetches_fail:
            raise AllSourcesUnavailableError("all sources failed")
        return [fetched(value) for value in values]


def fakes(
    trace: list[str],
    *,
    qualifying: bool,
    all_fetches_fail: bool = False,
    record_factory: Callable[[Candidate], EvidenceRecord] = evidence,
    original_source_resolver: (
        Callable[[Candidate, FetchedSource], FetchedSource | None] | None
    ) = None,
) -> PipelineDependencies:
    traced: set[str] = set()

    def mark(stage: str) -> None:
        if stage not in traced:
            trace.append(stage)
            traced.add(stage)

    def shortlist(values: list[Candidate], now: datetime) -> list[Candidate]:
        mark("shortlist")
        return values

    def extract(
        candidate: Candidate,
        source: FetchedSource,
        original_source: FetchedSource | None,
    ) -> EvidenceRecord:
        mark("extract")
        return record_factory(candidate)

    def gates(
        record: EvidenceRecord,
        duplicate_status: str,
    ) -> GateDecision:
        mark("gates")
        if not qualifying:
            return GateDecision(
                eligible_main_try=False,
                eligible_watch=False,
                rejection_reasons=["missing_action"],
            )
        return evaluate_gates(record, duplicate_status)

    def classify(
        record: EvidenceRecord,
        now: datetime,
    ) -> DuplicateAssessment:
        mark("dedupe")
        return DuplicateAssessment(status="unique")

    def score(
        record: EvidenceRecord,
        assessment: DuplicateAssessment,
        published_at: datetime,
        now: datetime,
    ) -> ScoreBreakdown:
        mark("score")
        return ScoreBreakdown(
            relevance=25,
            actionability=20,
            specificity=15,
            information_gain=15,
            evidence_quality=15,
            time_sensitivity=10,
        )

    def boards(
        values: list[ScoredEditorialCandidate],
    ):
        mark("boards")
        return build_boards(values)

    return PipelineDependencies(
        shortlist=shortlist,
        source_fetcher=FakeFetcher(
            trace,
            all_fetches_fail=all_fetches_fail,
        ),
        extract=extract,
        gates=gates,
        classify=classify,
        score=score,
        boards=boards,
        original_source_resolver=original_source_resolver,
    )


def test_pipeline_shortlists_fetches_extracts_gates_scores_and_builds_digest(
    tmp_path: Path,
) -> None:
    trace: list[str] = []

    result = run_editorial_pipeline(
        candidates(),
        dependencies=fakes(trace, qualifying=True),
        now=NOW,
    )

    assert trace == [
        "shortlist",
        "fetch",
        "extract",
        "gates",
        "dedupe",
        "score",
        "boards",
    ]
    assert result.digest.run_status == "published"
    assert [item.candidate_id for item in result.digest.items] == ["qualifying"]
    assert [entry.candidate_id for entry in result.audit.rejected] == ["rejected"]
    assert result.digest.pipeline_stats.top_rejection_reasons == {}

    audit_path = tmp_path / "latest_audit.json"
    write_audit(result.audit, audit_path)
    serialized = audit_path.read_text(encoding="utf-8")
    assert "Release notes / paragraph 2" in serialized
    assert FETCHED_TEXT not in serialized


def test_successful_pipeline_with_zero_qualifiers_is_legal_empty() -> None:
    result = run_editorial_pipeline(
        candidates(),
        dependencies=fakes([], qualifying=False),
        now=NOW,
    )

    assert result.digest.run_status == "no_qualifying_items"
    assert result.digest.items == []


def test_pipeline_derives_grounded_action_before_hard_gates() -> None:
    candidate = candidates()[1]

    result = run_editorial_pipeline(
        [candidate],
        dependencies=fakes([], qualifying=True),
        now=NOW,
    )

    assert result.digest.run_status == "published"
    assert [item.candidate_id for item in result.digest.items] == [
        candidate.id
    ]
    action = result.digest.items[0].recommended_action[0]
    assert "非生产环境" in action
    assert "integration" in action
    assert "依据：Model-X API v2 is available now for one dollar." in action
    assert result.audit.entries[0].gate_reasons == []


def test_grounded_action_cannot_bypass_invalid_evidence() -> None:
    candidate = candidates()[1]

    def invalid_anchor(value: Candidate) -> EvidenceRecord:
        return evidence(value).model_copy(
            update={
                "evidence_anchors": [
                    EvidenceAnchor(
                        quote="This quote is absent from the source.",
                        locator="invented",
                    )
                ]
            }
        )

    result = run_editorial_pipeline(
        [candidate],
        dependencies=fakes(
            [],
            qualifying=True,
            record_factory=invalid_anchor,
        ),
        now=NOW,
    )

    assert result.digest.run_status == "no_qualifying_items"
    reasons = result.audit.entries[0].gate_reasons
    assert "missing_action" not in reasons
    assert "invalid_evidence_anchor" in reasons
    assert "unverified_primary_source" in reasons


def test_all_fetches_failed_is_not_legal_empty() -> None:
    with pytest.raises(AllSourcesUnavailableError):
        run_editorial_pipeline(
            candidates(),
            dependencies=fakes(
                [],
                qualifying=True,
                all_fetches_fail=True,
            ),
            now=NOW,
        )


def test_one_extraction_failure_is_audited_while_other_candidate_publishes() -> None:
    def extract_or_fail(candidate: Candidate) -> EvidenceRecord:
        if candidate.id == "rejected":
            raise EvidenceExtractionError("candidate payload is too large")
        return evidence(candidate)

    result = run_editorial_pipeline(
        candidates(),
        dependencies=fakes(
            [],
            qualifying=True,
            record_factory=extract_or_fail,
        ),
        now=NOW,
    )

    assert result.digest.run_status == "published"
    assert [item.candidate_id for item in result.digest.items] == ["qualifying"]
    failed = next(
        entry
        for entry in result.audit.rejected
        if entry.candidate_id == "rejected"
    )
    assert failed.gate_reasons == ["evidence_extraction_failed"]
    assert failed.duplicate_status == "not_evaluated"
    assert result.digest.pipeline_stats.top_rejection_reasons == {
        "evidence_extraction_failed": 1
    }


def test_all_extraction_failures_raise_after_every_candidate_is_attempted() -> None:
    attempted: list[str] = []

    def always_fail(candidate: Candidate) -> EvidenceRecord:
        attempted.append(candidate.id)
        raise EvidenceExtractionError("candidate extraction failed")

    with pytest.raises(
        EvidenceExtractionError,
        match="all evidence extractions failed",
    ):
        run_editorial_pipeline(
            candidates(),
            dependencies=fakes(
                [],
                qualifying=True,
                record_factory=always_fail,
            ),
            now=NOW,
        )

    assert attempted == ["qualifying", "rejected"]


def test_model_cannot_invent_original_source_status_for_secondary_exception() -> None:
    def fabricated(candidate: Candidate) -> EvidenceRecord:
        return evidence(
            candidate,
            source_type="trusted_secondary",
            original_source_status="blocked",
        )

    media_candidate = candidates()[0].model_copy(
        update={
            "source_tier": 3,
            "source": "TechCrunch",
            "url": "https://techcrunch.com/story",
        }
    )
    result = run_editorial_pipeline(
        [media_candidate],
        dependencies=fakes(
            [],
            qualifying=True,
            record_factory=fabricated,
        ),
        now=NOW,
    )

    assert result.audit.entries[0].gate_reasons == [
        "unverified_primary_source"
    ]
    assert result.digest.run_status == "no_qualifying_items"


def test_explicit_fetched_original_source_can_enable_secondary_watch() -> None:
    candidate = candidates()[0]

    def secondary(value: Candidate) -> EvidenceRecord:
        return evidence(
            value,
            source_type="trusted_secondary",
            original_source_status="verified",
        )

    def original_source(
        value: Candidate,
        source: FetchedSource,
    ) -> FetchedSource:
        return fetched(value, status="blocked")

    result = run_editorial_pipeline(
        [candidate],
        dependencies=fakes(
            [],
            qualifying=True,
            record_factory=secondary,
            original_source_resolver=original_source,
        ),
        now=NOW,
    )

    assert [item.candidate_id for item in result.digest.boards.watch] == [
        candidate.id
    ]
    assert result.digest.items[0].verification_status == "blocked"


@pytest.mark.parametrize("publisher", ["TechCrunch", "VentureBeat"])
def test_tier_three_media_cannot_claim_official_primary_status(
    publisher: str,
) -> None:
    candidate = candidates()[0].model_copy(
        update={
            "source": publisher,
            "source_tier": 3,
            "url": f"https://{publisher.casefold()}.example/article",
        }
    )

    result = run_editorial_pipeline(
        [candidate],
        dependencies=fakes([], qualifying=True),
        now=NOW,
    )

    assert result.digest.run_status == "no_qualifying_items"
    assert result.audit.entries[0].gate_reasons == ["unverified_primary_source"]


def test_prompt_influenced_source_type_is_downgraded_by_program_provenance() -> None:
    candidate = candidates()[0].model_copy(
        update={"source_tier": 3, "url": "https://techcrunch.com/story"}
    )
    claimed = evidence(candidate, source_type="official_announcement")

    bound = pipeline_module.bind_program_provenance(
        candidate,
        fetched(candidate),
        claimed,
        original_source=None,
    )
    score = score_record(
        bound,
        DuplicateAssessment(status="unique"),
        candidate.published_at,
        NOW,
    )

    assert bound.source_type == "trusted_secondary"
    assert score.evidence_quality == 8


def test_cross_domain_redirect_cannot_retain_primary_provenance() -> None:
    candidate = candidates()[0].model_copy(
        update={"url": "https://official.example/release"}
    )
    source = fetched(candidate).model_copy(
        update={"final_url": "https://media.example/copied-release"}
    )

    bound = pipeline_module.bind_program_provenance(
        candidate,
        source,
        evidence(candidate),
        original_source=None,
    )

    assert bound.source_type == "trusted_secondary"


def test_same_trusted_tier_one_source_gets_deterministic_primary_type() -> None:
    candidate = candidates()[0].model_copy(
        update={"url": "https://official.example/release"}
    )
    source = fetched(candidate)

    bound = pipeline_module.bind_program_provenance(
        candidate,
        source,
        evidence(candidate, source_type="official_demo"),
        original_source=None,
    )

    assert bound.source_type == "official_announcement"


def test_financial_filing_domain_gets_program_owned_source_type() -> None:
    candidate = candidates()[0].model_copy(
        update={"url": "https://www.sec.gov/Archives/filing"}
    )

    bound = pipeline_module.bind_program_provenance(
        candidate,
        fetched(candidate),
        evidence(candidate),
        original_source=None,
    )

    assert bound.source_type == "financial_filing"


def test_pipeline_bounds_and_redacts_untrusted_model_output() -> None:
    candidate = candidates()[0].model_copy(
        update={
            "id": "candidate-" + "I" * 500,
            "title": (
                "Model API token="
                "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
            ),
            "summary": (
                "Bearer super-secret-access-token "
                + "summary " * 1000
            ),
            "url": (
                "https://example.com/release?"
                "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"
            ),
            "source": "password=ultra-secret-source",
        }
    )
    secrets = [
        "sk-abcdefghijklmnopqrstuvwxyz123456",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturevalue",
        "super-secret-access-token",
        "ultra-secret-source",
        "private-token-value",
    ]
    long_statement = (
        "Model-X API v2 is available now for one dollar. "
        + "A" * 30_000
        + "TAIL_MARKER "
        + secrets[0]
    )

    def hostile(value: Candidate) -> EvidenceRecord:
        record = evidence(value)
        change = record.concrete_changes[0].model_copy(
            update={
                "statement": long_statement,
                "numbers": [
                    f"{index}-{secrets[2]}"
                    for index in range(30)
                ],
                "entities": [
                    f"entity-{index}-token:{secrets[5]}"
                    for index in range(30)
                ],
            }
        )
        anchors = [
            record.evidence_anchors[0].model_copy(
                update={
                    "locator": (
                        f"paragraph-{index} "
                        f"secret={secrets[4]} "
                        + "L" * 180
                    )
                }
            )
            for index in range(30)
        ]
        return record.model_copy(
            update={
                "title_zh": f"API 发布 {secrets[1]}" + "标题" * 100,
                "summary_zh": (
                    f"Bearer {secrets[3]} "
                    + "摘要" * 1000
                ),
                "concrete_changes": [change] * 20,
                "evidence_anchors": anchors,
                "affected_audience": [
                    f"audience-{index} password:{secrets[4]}"
                    for index in range(30)
                ],
                "affected_area": [
                    f"area-{index} api_key={secrets[0]}"
                    for index in range(30)
                ],
                "recommended_action": [
                    f"action-{index} token={secrets[5]}"
                    for index in range(30)
                ],
                "event_entities": [
                    f"entity-{index}-{secrets[2]}"
                    for index in range(30)
                ],
                "primary_entity": (
                    f"Acme FEISHU_SIGNING_SECRET={secrets[4]}"
                ),
                "product_or_model": "模型" * 1000,
                "change_signature": "release " + "S" * 1000,
                "version_or_metric": f"v2 token={secrets[5]}" + "V" * 1000,
                "effective_date": (
                    f"ACCESS_TOKEN={secrets[5]}" + "D" * 1000
                ),
                "policy_terms": [
                    f"term-{index} password={secrets[4]}"
                    for index in range(30)
                ],
            }
        )

    result = run_editorial_pipeline(
        [candidate],
        dependencies=fakes(
            [],
            qualifying=True,
            record_factory=hostile,
        ),
        now=NOW,
    )

    digest_json = result.digest.model_dump_json()
    audit_json = result.audit.model_dump_json()
    for secret in secrets:
        assert secret not in digest_json
        assert secret not in audit_json
    assert "TAIL_MARKER" not in digest_json
    assert "TAIL_MARKER" not in audit_json

    item = result.digest.items[0]
    assert len(item.title_zh) <= 80
    assert len(item.summary_zh) <= 220
    assert len(item.concrete_change) <= 1200
    assert len(item.affected_audience) <= 5
    assert len(item.affected_area) <= 5
    assert len(item.recommended_action) <= 5
    assert all(
        len(action) <= 300
        for action in item.recommended_action
    )
    assert len(item.event_entities) <= 10
    assert all(
        len(entity) <= 160
        for entity in item.event_entities
    )
    assert len(item.primary_entity) <= 160
    assert len(item.change_signature) <= 160
    assert len(item.version_or_metric) <= 120
    assert item.effective_date is None or len(item.effective_date) <= 32
    assert len(item.source) <= 120
    assert len(item.event_fingerprint) <= 1000
    assert len(item.evidence_url) <= 1000

    audit = result.audit.entries[0]
    assert len(audit.candidate_id) <= 160
    assert len(audit.source_url) <= 1000
    assert audit.selected_board == "must_read"
    assert result.audit.rejected == []
    assert len(audit.anchor_locators) <= 8
    assert all(
        len(locator) <= 120
        for locator in audit.anchor_locators
    )


def test_pipeline_sanitizes_update_link_env_keys_and_path_credentials() -> None:
    path_secret = "path-secret-value"
    update_secret = "update-secret-value"
    signing_secret = "signing-secret-value"
    candidate = candidates()[0].model_copy(
        update={
            "url": (
                "https://example.com/hooks/access_token/"
                f"{path_secret}/release"
            )
        }
    )
    dependencies = fakes([], qualifying=True)

    def classify(
        record: EvidenceRecord,
        now: datetime,
    ) -> DuplicateAssessment:
        return DuplicateAssessment(
            status="material_update",
            update_of=(
                f"ACCESS_TOKEN={update_secret} "
                f"FEISHU_SIGNING_SECRET={signing_secret} "
                + "U" * 2000
            ),
        )

    result = run_editorial_pipeline(
        [candidate],
        dependencies=replace(
            dependencies,
            classify=classify,
        ),
        now=NOW,
    )

    digest_json = result.digest.model_dump_json()
    audit_json = result.audit.model_dump_json()
    for secret in (path_secret, update_secret, signing_secret):
        assert secret not in digest_json
        assert secret not in audit_json
    item = result.digest.items[0]
    assert item.update_of is not None
    assert len(item.update_of) <= 500
    assert "ACCESS_TOKEN=[REDACTED]" in item.update_of
    assert "FEISHU_SIGNING_SECRET=[REDACTED]" in item.update_of
    assert item.evidence_url == (
        "https://example.com/hooks/access_token/REDACTED/release"
    )
    assert result.audit.entries[0].source_url == item.evidence_url


def test_final_gate_runs_after_event_dedupe_with_real_status() -> None:
    calls: list[str] = []
    dependencies = fakes([], qualifying=True)

    def gates(
        record: EvidenceRecord,
        duplicate_status: str,
    ) -> GateDecision:
        calls.append(f"gate:{duplicate_status}")
        return evaluate_gates(record, duplicate_status)

    def classify(
        record: EvidenceRecord,
        now: datetime,
    ) -> DuplicateAssessment:
        calls.append("dedupe")
        return DuplicateAssessment(
            status="material_update",
            update_of="previous-event",
        )

    result = run_editorial_pipeline(
        [candidates()[0]],
        dependencies=replace(
            dependencies,
            gates=gates,
            classify=classify,
        ),
        now=NOW,
    )

    assert calls == [
        "gate:unique",
        "dedupe",
        "gate:material_update",
    ]
    assert result.digest.items[0].update_of == "previous-event"
