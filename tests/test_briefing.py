from datetime import UTC, datetime

from ai_news_bot.briefing import compose_daily_briefing
from ai_news_bot.event_history import DuplicateAssessment
from ai_news_bot.global_pipeline import (
    GlobalPipelineAudit,
    GlobalPipelineResult,
)
from ai_news_bot.models import (
    DigestBoards,
    EditorialNewsItem,
    GlobalEventItem,
    GlobalEventScore,
    GlobalPipelineStats,
    PipelineStats,
    ScoreBreakdown,
    TechnicalDigestSlice,
)


NOW = datetime(2026, 7, 29, 1, 5, tzinfo=UTC)


def technical_item(
    *,
    candidate_id: str = "shared",
    resource_available: bool = True,
    recommended_action: list[str] | None = None,
) -> EditorialNewsItem:
    return EditorialNewsItem(
        candidate_id=candidate_id,
        board="must_read",
        original_title="Model X developer release",
        title_zh="Model X 开发工具发布",
        summary_zh="开发者现在可以使用新的模型工具。",
        concrete_change="Model X developer tool is available.",
        affected_audience=["开发者"],
        affected_area=["开发工具"],
        recommended_action=(
            ["本周完成小范围验证"]
            if recommended_action is None
            else recommended_action
        ),
        evidence_url="https://example.com/technical",
        verification_status="verified",
        event_fingerprint="acme|model-x|developer-tool|v1|",
        primary_entity="Acme",
        product_or_model="Model X",
        event_entities=["Acme", "Model X"],
        change_signature="developer-tool",
        version_or_metric="v1",
        resource_available=resource_available,
        source="Acme",
        published_at=NOW,
        category="ai_coding",
        score=ScoreBreakdown(
            relevance=25,
            actionability=20,
            specificity=15,
            information_gain=15,
            evidence_quality=15,
            time_sensitivity=10,
        ),
    )


def technical_slice(
    items: list[EditorialNewsItem],
) -> TechnicalDigestSlice:
    boards = DigestBoards(
        must_read=[item for item in items if item.board == "must_read"]
    )
    return TechnicalDigestSlice(
        generated_at=NOW,
        candidate_count=len(items),
        source_count=len(items),
        lookback_hours=36,
        boards=boards,
        items=items,
        pipeline_stats=PipelineStats(
            candidate_count=len(items),
            shortlist_count=len(items),
            source_verified_count=len(items),
            rejected_count=0,
        ),
    )


def global_item(*, candidate_id: str = "shared") -> GlobalEventItem:
    return GlobalEventItem(
        event_id="acme|model-x|public-release|v1|2026-07-29",
        candidate_id=candidate_id,
        category="models_products",
        title_zh="Acme 正式发布 Model X",
        what_happened_zh="Acme 正式发布 Model X，并向公众开放使用。",
        why_it_matters_zh="普通用户现在可以直接使用该模型的新能力。",
        affected_groups_zh=["普通用户", "企业采购者"],
        key_facts=["模型已经正式发布"],
        source_name="Acme Newsroom",
        source_url="https://example.com/global",
        published_at=NOW,
        primary_entity="Acme",
        product_or_policy="Model X",
        change_signature="public-release",
        version_or_metric="v1",
        effective_date="2026-07-29",
        event_entities=["Acme", "Model X"],
        score=GlobalEventScore(
            impact=30,
            global_relevance=20,
            recency=20,
            evidence_quality=15,
            information_gain=10,
            clarity=5,
        ),
    )


def global_result(
    events: list[GlobalEventItem],
) -> GlobalPipelineResult:
    return GlobalPipelineResult(
        events=events,
        stats=GlobalPipelineStats(
            candidate_count=len(events),
            shortlist_count=len(events),
            source_verified_count=len(events),
            rejected_count=0,
        ),
        audit=GlobalPipelineAudit(generated_at=NOW),
    )


def test_composer_keeps_independent_actionable_technical_angle() -> None:
    digest = compose_daily_briefing(
        technical_slice([technical_item()]),
        global_result([global_item()]),
        NOW,
    )

    assert digest.global_events[0].candidate_id == "shared"
    assert digest.items[0].resource_available
    assert "今天" in digest.daily_narrative_zh


def test_composer_drops_non_actionable_cross_lane_duplicate() -> None:
    digest = compose_daily_briefing(
        technical_slice(
            [
                technical_item(
                    resource_available=False,
                    recommended_action=[],
                )
            ]
        ),
        global_result([global_item()]),
        NOW,
    )

    assert digest.items == []
    assert digest.boards.flatten() == []


def test_composer_accepts_global_only_technical_only_and_legal_empty() -> None:
    global_only = compose_daily_briefing(
        technical_slice([]),
        global_result([global_item()]),
        NOW,
    )
    technical_only = compose_daily_briefing(
        technical_slice([technical_item(candidate_id="technical")]),
        global_result([]),
        NOW,
    )
    empty = compose_daily_briefing(
        technical_slice([]),
        global_result([]),
        NOW,
    )

    assert global_only.run_status == "published"
    assert technical_only.run_status == "published"
    assert empty.run_status == "no_qualifying_items"
