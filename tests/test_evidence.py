import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from ai_news_bot.evidence import (
    EVIDENCE_SYSTEM_PROMPT,
    EvidenceExtractionError,
    extract_evidence,
    validate_anchors,
)
from ai_news_bot.models import Candidate, ChangeFact, EvidenceAnchor, EvidenceRecord
from ai_news_bot.source_fetcher import FetchedSource


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def candidate() -> Candidate:
    return Candidate(
        id="one",
        title="Model X API price update",
        summary="Input price falls from $2 to $1 per million tokens.",
        url="https://example.test/pricing",
        source="Example",
        source_tier=1,
        source_weight=1.0,
        published_at=NOW,
        metrics={"stars": 9_999},
    )


def fetched(*, status: str = "verified") -> FetchedSource:
    return FetchedSource(
        candidate_id="one",
        requested_url="https://example.test/pricing",
        final_url="https://example.test/pricing-v2",
        status=status,
        status_code=200 if status == "verified" else None,
        title="Model X pricing",
        text="Model X API\nInput price is $1 per million tokens.\nAvailable today.",
        fetched_at=NOW,
    )


def valid_record() -> EvidenceRecord:
    return EvidenceRecord(
        candidate_id="one",
        title_zh="Model X API 输入价格调整",
        summary_zh="输入价格为每百万 token 1 美元。",
        category="new_models",
        source_url="https://model.example/hallucinated",
        source_type="official_announcement",
        verification_status="verified",
        concrete_changes=[
            ChangeFact(
                change_type="pricing",
                statement="输入价格为每百万 token 1 美元。",
                numbers=["$1"],
                entities=["Model X"],
            )
        ],
        evidence_anchors=[
            EvidenceAnchor(
                quote="  INPUT   PRICE IS $1 PER MILLION TOKENS. ",
                locator="Pricing",
            )
        ],
        affected_audience=["API developers"],
        affected_area=["inference cost"],
        recommended_action=["Recalculate usage cost"],
        event_entities=["Example", "Model X"],
        primary_entity="Example",
        product_or_model="Model X",
        change_signature="api-input-price",
        version_or_metric="$1 / million tokens",
        relevance_signal="direct",
        action_horizon_days=0,
        resource_available=True,
    )


class FakeResponses:
    def __init__(self, owner: "FakeStructuredClient") -> None:
        self.owner = owner

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.owner.calls += 1
        self.owner.requests.append(("responses", kwargs))
        parsed = self.owner.next_result()
        return SimpleNamespace(output_parsed=parsed)


class FakeChatCompletions:
    def __init__(self, owner: "FakeStructuredClient") -> None:
        self.owner = owner

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.owner.calls += 1
        self.owner.requests.append(("chat", kwargs))
        parsed = self.owner.next_result()
        message = SimpleNamespace(parsed=parsed)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeStructuredClient:
    def __init__(self, results: list[EvidenceRecord | Exception | None]) -> None:
        self.results = iter(results)
        self.calls = 0
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.responses = FakeResponses(self)
        self.chat = SimpleNamespace(completions=FakeChatCompletions(self))

    def next_result(self) -> EvidenceRecord | None:
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def test_extractor_retries_once_then_returns_record() -> None:
    client = FakeStructuredClient([ValueError("bad json"), valid_record()])

    result = extract_evidence(candidate(), fetched(), client, "test-model")

    assert result.candidate_id == "one"
    assert result.source_url == "https://example.test/pricing-v2"
    assert client.calls == 2


def test_extractor_stops_after_second_parse_failure() -> None:
    client = FakeStructuredClient([ValueError("bad"), ValueError("bad again")])

    with pytest.raises(
        EvidenceExtractionError, match="model evidence parsing failed twice"
    ) as raised:
        extract_evidence(candidate(), fetched(), client, "test-model")

    assert client.calls == 2
    assert isinstance(raised.value.__cause__, ValueError)
    assert str(raised.value.__cause__) == "bad again"


def test_extractor_retries_a_mismatched_candidate_id() -> None:
    mismatched = valid_record().model_copy(update={"candidate_id": "another"})
    client = FakeStructuredClient([mismatched, valid_record()])

    result = extract_evidence(candidate(), fetched(), client, "test-model")

    assert result.candidate_id == "one"
    assert client.calls == 2


def test_extractor_uses_github_models_structured_chat_parse() -> None:
    client = FakeStructuredClient([valid_record()])

    result = extract_evidence(
        candidate(),
        fetched(),
        client,
        "github-model",
        base_url="https://models.github.ai/inference",
    )

    assert result.candidate_id == "one"
    assert client.calls == 1
    interface, request = client.requests[0]
    assert interface == "chat"
    assert request["model"] == "github-model"
    assert request["response_format"] is EvidenceRecord
    assert request["messages"][0]["content"] == EVIDENCE_SYSTEM_PROMPT


def test_extractor_uses_responses_structured_parse_and_constrained_payload() -> None:
    client = FakeStructuredClient([valid_record()])

    extract_evidence(candidate(), fetched(), client, "openai-model")

    interface, request = client.requests[0]
    assert interface == "responses"
    assert request["model"] == "openai-model"
    assert request["text_format"] is EvidenceRecord
    messages = request["input"]
    assert messages[0]["content"] == EVIDENCE_SYSTEM_PROMPT
    payload = json.loads(messages[1]["content"])
    assert payload == {
        "candidate_id": "one",
        "candidate_title": "Model X API price update",
        "candidate_summary": "Input price falls from $2 to $1 per million tokens.",
        "source_url": "https://example.test/pricing-v2",
        "source_title": "Model X pricing",
        "source_text": (
            "Model X API Input price is $1 per million tokens. Available today."
        ),
    }
    prompt = EVIDENCE_SYSTEM_PROMPT.casefold()
    assert "untrusted" in prompt
    assert "only" in prompt
    assert "score" in prompt
    assert "board" in prompt


def test_anchor_validator_accepts_normalized_literal_quote() -> None:
    checked = validate_anchors(valid_record(), fetched())

    assert checked.verification_status == "verified"
    assert checked.evidence_anchors == valid_record().evidence_anchors


def test_anchor_validator_rejects_quote_not_present_in_source() -> None:
    record = valid_record().model_copy(
        update={
            "evidence_anchors": [
                EvidenceAnchor(quote="invented price", locator="Pricing")
            ]
        }
    )

    checked = validate_anchors(record, fetched())

    assert checked.verification_status == "insufficient"
    assert checked.evidence_anchors == []
    assert checked.source_url == "https://example.test/pricing-v2"


def test_anchor_validator_rejects_quote_empty_after_normalization() -> None:
    record = valid_record().model_copy(
        update={
            "evidence_anchors": [
                EvidenceAnchor(quote="    ", locator="Whitespace-only quote")
            ]
        }
    )

    checked = validate_anchors(record, fetched())

    assert checked.verification_status == "insufficient"
    assert checked.evidence_anchors == []


@pytest.mark.parametrize("status", ["unavailable", "blocked", "insufficient"])
def test_anchor_validator_preserves_failed_source_status(status: str) -> None:
    checked = validate_anchors(valid_record(), fetched(status=status))

    assert checked.verification_status == status
