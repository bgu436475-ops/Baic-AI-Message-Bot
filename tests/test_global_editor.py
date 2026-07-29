from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from ai_news_bot.global_editor import (
    GLOBAL_EVENT_SYSTEM_PROMPT,
    GlobalEventExtractionError,
    extract_global_event,
    validate_global_anchors,
)
from ai_news_bot.models import (
    Candidate,
    EvidenceAnchor,
    GlobalEventEvidence,
)
from ai_news_bot.source_fetcher import FetchedSource


NOW = datetime(2026, 7, 29, 1, 5, tzinfo=UTC)


def candidate(*, source_tier: int = 1) -> Candidate:
    return Candidate(
        id="global-model-x",
        title="Acme officially releases Model X",
        summary="The model is available to the public.",
        url="https://example.com/model-x",
        source="Acme Newsroom",
        source_tier=source_tier,
        source_weight=1,
        published_at=NOW,
        lane_hints=["global"],
    )


def fetched() -> FetchedSource:
    return FetchedSource(
        candidate_id="global-model-x",
        requested_url="https://example.com/model-x",
        final_url="https://example.com/model-x",
        status="verified",
        status_code=200,
        title="Acme officially releases Model X",
        text=(
            "Acme officially released Model X on July 29, 2026. "
            "Model X is available to the public."
        ),
        fetched_at=NOW,
    )


def valid_global_record() -> GlobalEventEvidence:
    return GlobalEventEvidence(
        candidate_id="global-model-x",
        occurred=True,
        material_change=True,
        category="models_products",
        title_zh="Acme 正式发布 Model X",
        what_happened_zh="Acme 于 7 月 29 日正式发布 Model X，并向公众开放使用。",
        why_it_matters_zh="普通用户现在可以直接使用该模型的新能力。",
        affected_groups_zh=["普通用户", "企业采购者"],
        key_facts=["模型已经正式发布"],
        evidence_anchors=[
            EvidenceAnchor(
                quote="Acme officially released Model X on July 29, 2026.",
                locator="Announcement",
            )
        ],
        source_url="https://hallucinated.example/model-x",
        source_type="trusted_secondary",
        verification_status="verified",
        primary_entity="Acme",
        product_or_policy="Model X",
        change_signature="public-release",
        version_or_metric="Model X",
        effective_date="2026-07-29",
        event_entities=["Acme", "Model X"],
        impact_scope="global",
        geographic_scope=["全球市场"],
    )


class FakeResponses:
    def __init__(self, owner: "FakeStructuredClient") -> None:
        self.owner = owner

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.owner.calls += 1
        self.owner.requests.append(("responses", kwargs))
        return SimpleNamespace(output_parsed=self.owner.next_result())


class FakeChatCompletions:
    def __init__(self, owner: "FakeStructuredClient") -> None:
        self.owner = owner

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.owner.calls += 1
        self.owner.requests.append(("chat", kwargs))
        result = self.owner.next_result()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))]
        )


class FakeStructuredClient:
    def __init__(self, results: list[object]) -> None:
        self.results = iter(results)
        self.calls = 0
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.responses = FakeResponses(self)
        self.chat = SimpleNamespace(completions=FakeChatCompletions(self))

    def next_result(self) -> object:
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def test_global_editor_retries_once_for_missing_chinese() -> None:
    invalid = valid_global_record().model_copy(
        update={
            "title_zh": "Model X release",
            "what_happened_zh": "Public release",
        }
    )
    client = FakeStructuredClient([invalid, valid_global_record()])

    result = extract_global_event(
        candidate(),
        fetched(),
        client,
        "test-model",
    )

    assert result.title_zh == "Acme 正式发布 Model X"
    assert client.calls == 2


def test_global_editor_rejects_repository_style_reader_title() -> None:
    invalid = valid_global_record().model_copy(
        update={"title_zh": "owner/repository"}
    )
    client = FakeStructuredClient([invalid, valid_global_record()])

    result = extract_global_event(
        candidate(),
        fetched(),
        client,
        "test-model",
    )

    assert result.title_zh == "Acme 正式发布 Model X"
    assert client.calls == 2


def test_global_anchor_must_be_literal_source_text() -> None:
    record = valid_global_record().model_copy(
        update={
            "evidence_anchors": [
                EvidenceAnchor(
                    quote="fabricated claim",
                    locator="paragraph 1",
                )
            ]
        }
    )

    checked = validate_global_anchors(record, fetched())

    assert checked.verification_status == "insufficient"
    assert checked.evidence_anchors == []


def test_global_editor_overwrites_model_source_provenance() -> None:
    client = FakeStructuredClient([valid_global_record()])

    result = extract_global_event(
        candidate(source_tier=1),
        fetched(),
        client,
        "test-model",
    )

    assert result.source_url == "https://example.com/model-x"
    assert result.source_type == "official_announcement"
    assert result.verification_status == "verified"


def test_global_editor_forces_non_tier_one_source_to_secondary() -> None:
    client = FakeStructuredClient([valid_global_record()])

    result = extract_global_event(
        candidate(source_tier=3),
        fetched(),
        client,
        "test-model",
    )

    assert result.source_type == "trusted_secondary"


def test_global_editor_stops_after_two_controlled_failures() -> None:
    client = FakeStructuredClient([ValueError("bad"), ValueError("bad again")])

    with pytest.raises(
        GlobalEventExtractionError,
        match="global event parsing failed twice",
    ):
        extract_global_event(candidate(), fetched(), client, "test-model")

    assert client.calls == 2


def test_global_editor_uses_constrained_prompt_and_expected_schema() -> None:
    client = FakeStructuredClient([valid_global_record()])

    extract_global_event(candidate(), fetched(), client, "test-model")

    interface, request = client.requests[0]
    assert interface == "responses"
    assert request["text_format"] is GlobalEventEvidence
    assert request["input"][0]["content"] == GLOBAL_EVENT_SYSTEM_PROMPT
    prompt = GLOBAL_EVENT_SYSTEM_PROMPT.casefold()
    assert "already happened" in prompt
    assert "chinese" in prompt
    assert "literal evidence anchor" in prompt
    assert "do not score" in prompt
