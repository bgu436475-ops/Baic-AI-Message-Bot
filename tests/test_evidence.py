import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from openai import LengthFinishReasonError, OpenAIError
from openai.types.chat import ChatCompletion

from ai_news_bot.evidence import (
    DEFAULT_PROMPT_TOKEN_BUDGET,
    EVIDENCE_SYSTEM_PROMPT,
    EvidenceExtractionError,
    _anchor_supports_claim,
    _estimated_tokens,
    extract_evidence,
    validate_anchors,
)
from ai_news_bot.gatekeeper import evaluate_gates
from ai_news_bot.models import Candidate, ChangeFact, EvidenceAnchor, EvidenceRecord
from ai_news_bot.source_fetcher import FetchedSource


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
LENGTH_FINISH_ERROR = LengthFinishReasonError(
    completion=ChatCompletion(
        id="completion-one",
        choices=[],
        created=0,
        model="test-model",
        object="chat.completion",
    )
)


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


def fetched(*, status: str = "verified", candidate_id: str = "one") -> FetchedSource:
    return FetchedSource(
        candidate_id=candidate_id,
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


class FakeRawChatCompletions:
    def __init__(
        self,
        owner: "FakeRawChatClient",
        responses: list[SimpleNamespace | Exception],
    ) -> None:
        self.owner = owner
        self.responses = iter(responses)

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.owner.calls += 1
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


class FakeRawChatClient:
    def __init__(self, responses: list[SimpleNamespace | Exception]) -> None:
        self.calls = 0
        completions = FakeRawChatCompletions(self, responses)
        self.chat = SimpleNamespace(completions=completions)


def chat_response(record: EvidenceRecord) -> SimpleNamespace:
    message = SimpleNamespace(parsed=record)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


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


def test_extractor_honors_single_max_attempt() -> None:
    client = FakeStructuredClient([ValueError("bad json"), valid_record()])

    with pytest.raises(EvidenceExtractionError):
        extract_evidence(
            candidate(),
            fetched(),
            client,
            "test-model",
            max_attempts=1,
        )

    assert client.calls == 1


def test_extractor_rejects_non_positive_max_attempts_without_requesting() -> None:
    client = FakeStructuredClient([valid_record()])

    with pytest.raises(ValueError, match="max_attempts must be at least 1"):
        extract_evidence(
            candidate(),
            fetched(),
            client,
            "test-model",
            max_attempts=0,
        )

    assert client.calls == 0


@pytest.mark.parametrize(
    "first_response",
    [
        LENGTH_FINISH_ERROR,
        OpenAIError("structured parser rejected the response"),
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())]),
    ],
    ids=["length-finish-reason", "openai-error", "empty-choices", "missing-parsed"],
)
def test_extractor_retries_controlled_parser_and_adapter_failures(
    first_response: SimpleNamespace | Exception,
) -> None:
    client = FakeRawChatClient([first_response, chat_response(valid_record())])

    result = extract_evidence(
        candidate(),
        fetched(),
        client,
        "github-model",
        base_url="https://models.github.ai/inference",
    )

    assert result.candidate_id == "one"
    assert client.calls == 2


@pytest.mark.parametrize(
    ("second_response", "expected_cause"),
    [
        (OpenAIError("second OpenAI parse failure"), OpenAIError),
        (SimpleNamespace(choices=[]), IndexError),
        (
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())]),
            AttributeError,
        ),
    ],
    ids=["openai-error", "empty-choices", "missing-parsed"],
)
def test_extractor_wraps_second_controlled_failure_as_extraction_error(
    second_response: SimpleNamespace | Exception,
    expected_cause: type[Exception],
) -> None:
    client = FakeRawChatClient(
        [OpenAIError("first OpenAI parse failure"), second_response]
    )

    with pytest.raises(
        EvidenceExtractionError, match="model evidence parsing failed twice"
    ) as raised:
        extract_evidence(
            candidate(),
            fetched(),
            client,
            "github-model",
            base_url="https://models.github.ai/inference",
        )

    assert client.calls == 2
    assert isinstance(raised.value.__cause__, expected_cause)


def test_extractor_retries_a_mismatched_candidate_id() -> None:
    mismatched = valid_record().model_copy(update={"candidate_id": "another"})
    client = FakeStructuredClient([mismatched, valid_record()])

    result = extract_evidence(candidate(), fetched(), client, "test-model")

    assert result.candidate_id == "one"
    assert client.calls == 2


def test_extractor_retries_blank_chinese_instead_of_returning_it() -> None:
    invalid = valid_record().model_copy(
        update={"title_zh": "", "summary_zh": ""}
    )
    client = FakeStructuredClient([invalid, valid_record()])

    result = extract_evidence(candidate(), fetched(), client, "test-model")

    assert result.title_zh == "Model X API 输入价格调整"
    assert result.summary_zh == "输入价格为每百万 token 1 美元。"
    assert client.calls == 2


def test_extractor_rejects_candidate_source_mismatch_before_model_call() -> None:
    client = FakeStructuredClient([valid_record()])

    with pytest.raises(EvidenceExtractionError, match="candidate and source IDs"):
        extract_evidence(
            candidate(),
            fetched(candidate_id="another"),
            client,
            "test-model",
        )

    assert client.calls == 0


def test_extractor_clears_model_claimed_original_status_without_original_source() -> None:
    claimed = valid_record().model_copy(
        update={
            "source_type": "trusted_secondary",
            "original_source_status": "unavailable",
        }
    )
    client = FakeStructuredClient([claimed])

    result = extract_evidence(candidate(), fetched(), client, "test-model")

    assert result.original_source_status is None
    assert not evaluate_gates(result, "unique").eligible_watch


def test_extractor_uses_fetched_original_status_for_verified_secondary_watch() -> None:
    claimed = valid_record().model_copy(
        update={
            "source_type": "trusted_secondary",
            "original_source_status": "verified",
        }
    )
    client = FakeStructuredClient([claimed])

    result = extract_evidence(
        candidate(),
        fetched(),
        client,
        "test-model",
        original_source=fetched(status="unavailable"),
    )

    decision = evaluate_gates(result, "unique")

    assert result.original_source_status == "unavailable"
    assert not decision.eligible_main_try
    assert decision.eligible_watch
    assert decision.rejection_reasons == ["unverified_primary_source"]


@pytest.mark.parametrize("original_status", ["verified", "insufficient"])
def test_extractor_does_not_watch_verified_secondary_when_original_is_accessible(
    original_status: Literal["verified", "insufficient"],
) -> None:
    claimed = valid_record().model_copy(
        update={
            "source_type": "trusted_secondary",
            "original_source_status": "unavailable",
        }
    )
    client = FakeStructuredClient([claimed])

    result = extract_evidence(
        candidate(),
        fetched(),
        client,
        "test-model",
        original_source=fetched(status=original_status),
    )

    assert result.original_source_status == original_status
    assert not evaluate_gates(result, "unique").eligible_watch


def test_extractor_rejects_original_source_mismatch_before_model_call() -> None:
    client = FakeStructuredClient([valid_record()])

    with pytest.raises(
        EvidenceExtractionError, match="candidate and original source IDs"
    ):
        extract_evidence(
            candidate(),
            fetched(),
            client,
            "test-model",
            original_source=fetched(candidate_id="another"),
        )

    assert client.calls == 0


def test_extractor_uses_openai_compatible_structured_chat_parse() -> None:
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
    assert "policy_terms" in prompt
    assert "original_source_status" in prompt
    assert "secondary" in prompt
    assert "program" in prompt
    assert "must not infer" in prompt


def test_extractor_bounds_multilingual_source_before_first_request() -> None:
    client = FakeStructuredClient([valid_record()])
    source = fetched().model_copy(
        update={
            "text": (
                "模型 X API v2 输入价格从 2 美元降至 1 美元。"
                "Developers can migrate today. "
            )
            * 2_000
        }
    )

    extract_evidence(candidate(), source, client, "openai-model")

    _, request = client.requests[0]
    payload = json.loads(request["input"][1]["content"])
    assert len(payload["source_text"]) <= 12_000
    assert len(payload["source_text"]) < len(source.text)


def test_extractor_retries_payload_limit_with_smaller_source_excerpt() -> None:
    client = FakeStructuredClient(
        [
            OpenAIError(
                "Error code: 413 - tokens_limit_reached; "
                "Max size: 8000 tokens"
            ),
            valid_record(),
        ]
    )
    source = fetched().model_copy(
        update={"text": "Model X API v2 costs $1. " * 2_000}
    )

    result = extract_evidence(
        candidate(),
        source,
        client,
        "github-model",
        base_url="https://models.github.ai/inference",
    )

    first = json.loads(client.requests[0][1]["messages"][1]["content"])
    second = json.loads(client.requests[1][1]["messages"][1]["content"])
    assert result.candidate_id == "one"
    assert len(second["source_text"]) < len(first["source_text"])


def test_extractor_bounds_the_serialized_prompt_including_json_escaping() -> None:
    client = FakeStructuredClient([valid_record()])
    oversized_candidate = candidate().model_copy(
        update={"title": '"quoted\\\\title" ' * 2_000}
    )
    source = fetched().model_copy(
        update={
            "title": '"quoted\\\\source" ' * 2_000,
            "text": '"value\\\\path" ' * 8_000,
        }
    )

    extract_evidence(
        oversized_candidate,
        source,
        client,
        "github-model",
        base_url="https://models.github.ai/inference",
    )

    messages = client.requests[0][1]["messages"]
    assert sum(
        _estimated_tokens(message["content"])
        for message in messages
    ) <= DEFAULT_PROMPT_TOKEN_BUDGET


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


def test_each_concrete_change_must_be_supported_by_a_bound_anchor() -> None:
    source = fetched().model_copy(
        update={
            "text": (
                "Model X API input costs $1 per million tokens. "
                "Model X API v2 launches on 2026-07-24."
            )
        }
    )
    record = valid_record().model_copy(
        update={
            "concrete_changes": [
                ChangeFact(
                    change_type="price",
                    statement="Model X API input costs $1 per million tokens.",
                ),
                ChangeFact(
                    change_type="release",
                    statement="Model X API v3 launches on 2026-07-24.",
                ),
            ],
            "evidence_anchors": [
                EvidenceAnchor(
                    quote="Model X API input costs $1 per million tokens.",
                    locator="Pricing",
                ),
                EvidenceAnchor(
                    quote="Model X API v2 launches on 2026-07-24.",
                    locator="Release",
                ),
            ],
        }
    )

    checked = validate_anchors(record, source)

    assert checked.verification_status == "insufficient"
    assert checked.evidence_covers_full_claim is False


def test_unrelated_literal_quote_cannot_support_a_different_price_claim() -> None:
    source = fetched().model_copy(
        update={"text": "Model X API input price is $1 per million tokens."}
    )
    record = valid_record().model_copy(
        update={
            "concrete_changes": [
                ChangeFact(
                    change_type="pricing",
                    statement="Model X API output is free.",
                )
            ],
            "evidence_anchors": [
                EvidenceAnchor(
                    quote="Model X API input price is $1 per million tokens.",
                    locator="Pricing",
                )
            ],
            "evidence_covers_full_claim": True,
        }
    )

    checked = validate_anchors(record, source)

    assert checked.verification_status == "insufficient"
    assert checked.evidence_covers_full_claim is False


@pytest.mark.parametrize(
    ("statement", "quote"),
    [
        ("Model X API v2 costs $1 per million tokens.", "Model X API v2 costs $1 per million tokens."),
        ("模型 X API v2 输入价格降至每百万 token 1 美元。", "模型 X API v2 输入价格降至每百万 token 1 美元，今日生效。"),
    ],
)
def test_matching_price_version_api_and_cjk_claims_pass(
    statement: str,
    quote: str,
) -> None:
    source = fetched().model_copy(update={"text": quote})
    record = valid_record().model_copy(
        update={
            "concrete_changes": [
                ChangeFact(change_type="release", statement=statement)
            ],
            "evidence_anchors": [
                EvidenceAnchor(quote=quote, locator="Release")
            ],
        }
    )

    checked = validate_anchors(record, source)

    assert checked.verification_status == "verified"
    assert checked.evidence_covers_full_claim is True


def test_generic_literal_quote_cannot_support_specific_change() -> None:
    source = fetched().model_copy(update={"text": "Available today."})
    record = valid_record().model_copy(
        update={
            "concrete_changes": [
                ChangeFact(
                    change_type="release",
                    statement="Model X API v2 is available today.",
                )
            ],
            "evidence_anchors": [
                EvidenceAnchor(quote="Available today.", locator="Hero")
            ],
        }
    )

    checked = validate_anchors(record, source)

    assert checked.verification_status == "insufficient"


def test_lowercase_api_identifier_must_appear_in_bound_anchor() -> None:
    quote = "Output price is $1 per million tokens."
    source = fetched().model_copy(update={"text": quote})
    record = valid_record().model_copy(
        update={
            "concrete_changes": [
                ChangeFact(
                    change_type="pricing",
                    statement="api output price is $1 per million tokens.",
                )
            ],
            "evidence_anchors": [
                EvidenceAnchor(quote=quote, locator="Pricing")
            ],
        }
    )

    checked = validate_anchors(record, source)

    assert checked.verification_status == "insufficient"


def test_currency_unit_must_appear_in_bound_anchor() -> None:
    quote = "Model X API input price is 1 per million tokens."
    source = fetched().model_copy(update={"text": quote})
    record = valid_record().model_copy(
        update={
            "concrete_changes": [
                ChangeFact(
                    change_type="pricing",
                    statement="Model X API input price is $1 per million tokens.",
                )
            ],
            "evidence_anchors": [
                EvidenceAnchor(quote=quote, locator="Pricing")
            ],
        }
    )

    checked = validate_anchors(record, source)

    assert checked.verification_status == "insufficient"


def checked_claim(statement: str, quote: str) -> EvidenceRecord:
    source = fetched().model_copy(update={"text": quote})
    record = valid_record().model_copy(
        update={
            "concrete_changes": [
                ChangeFact(change_type="material", statement=statement)
            ],
            "evidence_anchors": [
                EvidenceAnchor(quote=quote, locator="Material facts")
            ],
        }
    )
    return validate_anchors(record, source)


@pytest.mark.parametrize(
    ("statement", "quote", "supported"),
    [
        (
            "价格从每百万令牌2美元降至1美元",
            "价格从每百万令牌1美元涨至2美元",
            False,
        ),
        (
            "价格从每百万令牌2美元降至1美元",
            "价格从每百万令牌2美元涨至1美元",
            False,
        ),
        (
            "价格从每百万令牌2美元降至1美元",
            "价格从每百万令牌2美元降至1美元",
            True,
        ),
        (
            "Input price falls from $2 to $1 per million tokens.",
            "Input price rises from $1 to $2 per million tokens.",
            False,
        ),
        (
            "Input price falls from $2 to $1 per million tokens.",
            "Input price rises from $2 to $1 per million tokens.",
            False,
        ),
        (
            "Input price falls from $2 to $1 per million tokens.",
            "Input price falls from $2 to $1 per million tokens.",
            True,
        ),
    ],
    ids=[
        "zh-reversed-values",
        "zh-opposite-direction",
        "zh-match",
        "en-reversed-values",
        "en-opposite-direction",
        "en-match",
    ],
)
def test_directional_claim_binds_value_order_and_direction(
    statement: str,
    quote: str,
    supported: bool,
) -> None:
    assert _anchor_supports_claim(statement, quote) is supported


@pytest.mark.parametrize(
    ("statement", "quote", "supported"),
    [
        ("折扣从20%降至10%", "折扣从20%降至10%", True),
        ("折扣从20%降至10%", "折扣从20%涨至10%", False),
        (
            "Latency decreases from 200ms to 100ms.",
            "Latency decreases from 200ms to 100ms.",
            True,
        ),
        (
            "Latency decreases from 200ms to 100ms.",
            "Latency increases from 200ms to 100ms.",
            False,
        ),
        (
            "Latency decreases from 200ms to 100ms.",
            "Latency decreases from 100ms to 200ms.",
            False,
        ),
        (
            "Input price increases from $1 to $2.",
            "Input price increases from $1 to $2.",
            True,
        ),
        (
            "Input price increases from $1 to $2.",
            "Input price decreases from $1 to $2.",
            False,
        ),
        (
            "Input price falls from $2 to $1.",
            "Input price was $2; input price is $1.",
            False,
        ),
        (
            "Input price falls from $2 to $1.",
            "Input price moves from $2 to $1.",
            True,
        ),
        ("模型v2.0发布", "模型version 2.0发布", True),
        (
            "Model X API v2.0 launches on 2026-07-24.",
            "Model X API version 2.0 launches on 2026-07-24.",
            True,
        ),
        ("Model X API price is $1.", "Model X API price is $1.", True),
        ("api价格降至1美元", "api价格降至1美元", True),
    ],
    ids=[
        "percentage-decrease",
        "percentage-opposite",
        "latency-decrease",
        "latency-opposite",
        "latency-reversed-values",
        "price-increase",
        "price-opposite",
        "ambiguous-anchor",
        "ordered-anchor-infers-direction",
        "version-only",
        "version-and-date",
        "one-value-price-api",
        "one-value-direction",
    ],
)
def test_direction_binding_covers_metrics_without_overapplying(
    statement: str,
    quote: str,
    supported: bool,
) -> None:
    assert _anchor_supports_claim(statement, quote) is supported


@pytest.mark.parametrize(
    ("quote", "eligible"),
    [
        ("价格从每百万令牌1美元涨至2美元", False),
        ("价格从每百万令牌2美元涨至1美元", False),
        ("价格从每百万令牌2美元降至1美元", True),
    ],
    ids=["reversed-values", "opposite-direction", "matching-direction"],
)
def test_extraction_and_gate_cannot_bypass_direction_binding(
    quote: str,
    eligible: bool,
) -> None:
    statement = "价格从每百万令牌2美元降至1美元"
    record = valid_record().model_copy(
        update={
            "concrete_changes": [
                ChangeFact(change_type="pricing", statement=statement)
            ],
            "evidence_anchors": [
                EvidenceAnchor(quote=quote, locator="Pricing")
            ],
            "evidence_covers_full_claim": True,
        }
    )
    source = fetched().model_copy(update={"text": quote})

    extracted = extract_evidence(
        candidate(),
        source,
        FakeStructuredClient([record]),
        "test-model",
    )
    decision = evaluate_gates(extracted, "unique")

    assert extracted.evidence_covers_full_claim is eligible
    assert decision.eligible_main_try is eligible
    assert (
        "invalid_evidence_anchor" in decision.rejection_reasons
    ) is not eligible


def test_chinese_adjacent_price_numbers_must_match_exactly() -> None:
    checked = checked_claim(
        "价格从每百万令牌2美元降至1美元",
        "价格从每百万令牌3美元降至2美元",
    )

    assert checked.verification_status == "insufficient"
    assert checked.evidence_covers_full_claim is False


def test_matching_chinese_adjacent_price_numbers_pass() -> None:
    checked = checked_claim(
        "价格从每百万令牌2美元降至1美元",
        "价格从每百万令牌2美元降至1美元",
    )

    assert checked.verification_status == "verified"
    assert checked.evidence_covers_full_claim is True


@pytest.mark.parametrize(
    ("statement", "quote"),
    [
        ("折扣从20%降至10%", "折扣从20%降至10%"),
        ("新价格为2欧元", "新价格为2欧元"),
        ("条款于2026年7月24日生效", "条款于2026年7月24日生效"),
        ("模型v2.0发布", "模型v2.0发布"),
        ("api价格降至1美元", "api价格降至1美元"),
    ],
)
def test_chinese_adjacent_material_tokens_pass_when_matching(
    statement: str,
    quote: str,
) -> None:
    assert checked_claim(statement, quote).verification_status == "verified"


@pytest.mark.parametrize(
    ("statement", "quote"),
    [
        ("折扣从20%降至10%", "折扣从30%降至20%"),
        ("新价格为2欧元", "新价格为3欧元"),
        ("条款于2026年7月24日生效", "条款于2026年7月25日生效"),
        ("模型v2.0发布", "模型v3.0发布"),
    ],
)
def test_chinese_adjacent_material_tokens_fail_when_different(
    statement: str,
    quote: str,
) -> None:
    assert checked_claim(statement, quote).verification_status == "insufficient"


def test_version_prefix_paraphrase_uses_same_canonical_material_version() -> None:
    checked = checked_claim("模型v2.0发布", "模型version 2.0发布")

    assert checked.verification_status == "verified"
    assert checked.evidence_covers_full_claim is True


@pytest.mark.parametrize("status", ["unavailable", "blocked", "insufficient"])
def test_anchor_validator_preserves_failed_source_status(status: str) -> None:
    checked = validate_anchors(valid_record(), fetched(status=status))

    assert checked.verification_status == status
