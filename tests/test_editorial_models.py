from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_news_bot.models import (
    ChangeFact,
    DigestBoards,
    EditorialDigest,
    EditorialNewsItem,
    EvidenceAnchor,
    GlobalEventItem,
    GlobalEventScore,
    GlobalPipelineStats,
    PipelineStats,
    ScoreBreakdown,
)


def item(board: str = "must_read") -> EditorialNewsItem:
    return EditorialNewsItem(
        candidate_id="model-x",
        board=board,
        original_title="Model X API price update",
        title_en="Model X API price update",
        summary_en="Input price falls from $2 to $1 per million tokens.",
        title_zh="Model X API 输入价格减半",
        summary_zh="输入价格从每百万 token 2 美元降至 1 美元。",
        concrete_change="输入价格从每百万 token 2 美元降至 1 美元。",
        affected_audience=["API 开发者"],
        affected_area=["推理成本"],
        recommended_action=["按当前调用量重新计算月成本"],
        evidence_url="https://example.com/pricing",
        verification_status="verified",
        event_fingerprint="example|model-x|price|v2|2026-07-23",
        primary_entity="Example",
        event_entities=["Example", "Model X"],
        change_signature="price",
        version_or_metric="v2-$1",
        resource_available=True,
        source="Example",
        published_at=datetime(2026, 7, 23, tzinfo=UTC),
        category="new_models",
        score=ScoreBreakdown(
            relevance=25,
            actionability=20,
            specificity=15,
            information_gain=15,
            evidence_quality=15,
            time_sensitivity=10,
            penalties=0,
        ),
    )


def global_event(
    *,
    event_id: str = "acme|model-x|release|2026-07-29",
    candidate_id: str = "global-model-x",
    category: str = "models_products",
) -> GlobalEventItem:
    return GlobalEventItem(
        event_id=event_id,
        candidate_id=candidate_id,
        category=category,
        title_zh="Acme 正式发布 Model X",
        what_happened_zh="Acme 于 7 月 29 日正式发布 Model X，并向公众开放使用。",
        why_it_matters_zh="该产品改变了普通用户可直接使用的模型能力范围。",
        affected_groups_zh=["普通用户", "企业采购者"],
        key_facts=["2026-07-29 正式发布"],
        source_name="Acme Newsroom",
        source_url="https://example.com/model-x",
        supporting_urls=[],
        published_at=datetime(2026, 7, 29, tzinfo=UTC),
        primary_entity="Acme",
        product_or_policy="Model X",
        change_signature="public-release",
        version_or_metric="Model X",
        effective_date="2026-07-29",
        event_entities=["Acme", "Model X"],
        score=GlobalEventScore(
            impact=24,
            global_relevance=16,
            recency=20,
            evidence_quality=15,
            information_gain=10,
            clarity=5,
        ),
    )


def global_stats() -> GlobalPipelineStats:
    return GlobalPipelineStats(
        candidate_count=20,
        shortlist_count=8,
        source_verified_count=8,
        rejected_count=7,
    )


def test_schema_v4_flattens_mutually_exclusive_boards() -> None:
    story = item()
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, tzinfo=UTC),
        candidate_count=80,
        source_count=20,
        daily_narrative_zh="今天有一条经过核验的技术情报。",
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(must_read=[story]),
        items=[story],
        pipeline_stats=PipelineStats(
            candidate_count=80,
            shortlist_count=18,
            source_verified_count=15,
            rejected_count=17,
        ),
    )
    assert digest.schema_version == 4
    assert digest.items == digest.boards.flatten()
    assert digest.run_status == "published"
    assert digest.items[0].score.total == 100


def test_schema_v4_accepts_global_only_published_digest() -> None:
    event = global_event()
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 29, 1, 5, tzinfo=UTC),
        candidate_count=20,
        source_count=8,
        daily_narrative_zh="今天的重点是 Acme 正式发布 Model X。",
        global_events=[event],
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=20,
            shortlist_count=4,
            source_verified_count=4,
            rejected_count=4,
        ),
    )

    assert digest.schema_version == 4
    assert digest.run_status == "published"
    assert digest.items == []
    assert digest.global_events == [event]


def test_schema_v4_accepts_legal_empty_digest() -> None:
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, tzinfo=UTC),
        candidate_count=12,
        source_count=7,
        run_status="no_qualifying_items",
        daily_narrative_zh="今天没有全球重大事件或技术信息通过核验。",
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=12,
            shortlist_count=4,
            source_verified_count=3,
            rejected_count=4,
            top_rejection_reasons={"missing_concrete_change": 3},
        ),
    )
    assert digest.items == []


def test_schema_v4_rejects_duplicate_or_mismatched_boards() -> None:
    story = item()
    with pytest.raises(ValidationError):
        EditorialDigest(
            generated_at=datetime(2026, 7, 23, tzinfo=UTC),
            candidate_count=1,
            source_count=1,
            daily_narrative_zh="今天有重复的技术情报。",
            global_pipeline_stats=global_stats(),
            boards=DigestBoards(
                must_read=[story],
                try_now=[story.model_copy(update={"board": "try_now"})],
            ),
            items=[story],
            pipeline_stats=PipelineStats(
                candidate_count=1,
                shortlist_count=1,
                source_verified_count=1,
                rejected_count=0,
            ),
        )


def test_schema_v4_rejects_item_in_wrong_named_board() -> None:
    with pytest.raises(ValidationError):
        DigestBoards(must_read=[item(board="try_now")])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title_zh", "Model X release"),
        ("what_happened_zh", "Public release"),
        ("why_it_matters_zh", "Broad access"),
        ("affected_groups_zh", ["developers"]),
        ("key_facts", ["released"]),
    ],
)
def test_global_event_rejects_missing_chinese_explanation(
    field: str,
    value: str | list[str],
) -> None:
    with pytest.raises(ValidationError):
        GlobalEventItem.model_validate(
            {**global_event().model_dump(), field: value}
        )


def test_schema_v4_rejects_more_than_five_global_events() -> None:
    events = [
        global_event(
            event_id=f"event-{index}",
            candidate_id=f"candidate-{index}",
            category=(
                "models_products"
                if index < 2
                else "companies_business"
                if index < 4
                else "policy_regulation"
            ),
        )
        for index in range(6)
    ]
    with pytest.raises(ValidationError):
        EditorialDigest(
            generated_at=datetime(2026, 7, 29, tzinfo=UTC),
            candidate_count=6,
            source_count=6,
            daily_narrative_zh="今天有多条全球人工智能重大事件。",
            global_events=events,
            global_pipeline_stats=global_stats(),
            boards=DigestBoards(),
            items=[],
            pipeline_stats=PipelineStats(
                candidate_count=6,
                shortlist_count=0,
                source_verified_count=0,
                rejected_count=0,
            ),
        )


def test_schema_v4_rejects_more_than_two_events_in_one_category() -> None:
    events = [
        global_event(
            event_id=f"event-{index}",
            candidate_id=f"candidate-{index}",
        )
        for index in range(3)
    ]
    with pytest.raises(ValidationError):
        EditorialDigest(
            generated_at=datetime(2026, 7, 29, tzinfo=UTC),
            candidate_count=3,
            source_count=3,
            daily_narrative_zh="今天同一类别事件数量超过上限。",
            global_events=events,
            global_pipeline_stats=global_stats(),
            boards=DigestBoards(),
            items=[],
            pipeline_stats=PipelineStats(
                candidate_count=3,
                shortlist_count=0,
                source_verified_count=0,
                rejected_count=0,
            ),
        )


def test_schema_v4_rejects_identical_global_and_technical_fingerprint() -> None:
    story = item()
    event = global_event(event_id=story.event_fingerprint)
    with pytest.raises(ValidationError):
        EditorialDigest(
            generated_at=datetime(2026, 7, 29, tzinfo=UTC),
            candidate_count=2,
            source_count=2,
            daily_narrative_zh="今天同一事件不能跨栏重复。",
            global_events=[event],
            global_pipeline_stats=global_stats(),
            boards=DigestBoards(must_read=[story]),
            items=[story],
            pipeline_stats=PipelineStats(
                candidate_count=2,
                shortlist_count=1,
                source_verified_count=1,
                rejected_count=0,
            ),
        )


def test_schema_v4_allows_same_candidate_with_distinct_event_fingerprints() -> None:
    story = item().model_copy(update={"candidate_id": "shared-candidate"})
    event = global_event(candidate_id="shared-candidate")
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 29, tzinfo=UTC),
        candidate_count=1,
        source_count=1,
        daily_narrative_zh="同一来源保留了不同的全球与技术视角。",
        global_events=[event],
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(must_read=[story]),
        items=[story],
        pipeline_stats=PipelineStats(
            candidate_count=1,
            shortlist_count=1,
            source_verified_count=1,
            rejected_count=0,
        ),
    )

    assert digest.global_events[0].candidate_id == digest.items[0].candidate_id


def test_schema_v4_rejects_empty_status_with_global_content() -> None:
    with pytest.raises(ValidationError):
        EditorialDigest(
            generated_at=datetime(2026, 7, 29, tzinfo=UTC),
            candidate_count=1,
            source_count=1,
            run_status="no_qualifying_items",
            daily_narrative_zh="状态为空榜时不能包含全球事件。",
            global_events=[global_event()],
            global_pipeline_stats=global_stats(),
            boards=DigestBoards(),
            items=[],
            pipeline_stats=PipelineStats(
                candidate_count=1,
                shortlist_count=0,
                source_verified_count=0,
                rejected_count=0,
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("title_zh", ""), ("summary_zh", "English only")],
)
def test_technical_item_rejects_missing_chinese_content(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError):
        EditorialNewsItem.model_validate(
            {**item().model_dump(), field: value}
        )


@pytest.mark.parametrize(
    "evidence_url",
    [
        "http://127.0.0.1/evidence",
        "http://example.com/evidence",
        "https://user:password@example.com/evidence",
        "https://example.com/" + "x" * 240,
    ],
)
def test_editorial_item_rejects_unsafe_or_overlong_evidence_url(
    evidence_url: str,
) -> None:
    with pytest.raises(ValidationError):
        item().model_copy(update={"evidence_url": evidence_url}).__class__.model_validate(
            {**item().model_dump(), "evidence_url": evidence_url}
        )


@pytest.mark.parametrize(
    "effective_date",
    ["2026-02-30", "2026-2-03", "not-a-date"],
)
def test_editorial_item_rejects_invalid_effective_date(
    effective_date: str,
) -> None:
    with pytest.raises(ValidationError):
        EditorialNewsItem.model_validate(
            {**item().model_dump(), "effective_date": effective_date}
        )


def test_editorial_item_accepts_valid_https_url_and_calendar_date() -> None:
    validated = EditorialNewsItem.model_validate(
        {
            **item().model_dump(),
            "evidence_url": "https://example.com/evidence",
            "effective_date": "2024-02-29",
        }
    )

    assert validated.evidence_url == "https://example.com/evidence"
    assert validated.effective_date == "2024-02-29"
