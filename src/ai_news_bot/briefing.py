from __future__ import annotations

from datetime import datetime

from .global_pipeline import GlobalPipelineResult
from .models import (
    DigestBoards,
    EditorialDigest,
    EditorialNewsItem,
    GlobalEventItem,
    TechnicalDigestSlice,
)


_ACTIONABLE_TECHNICAL_CATEGORIES = {
    "ai_coding",
    "agents",
    "image_video",
    "comfyui",
    "open_source",
    "mcp",
    "skills",
}


def _independent_technical_angle(item: EditorialNewsItem) -> bool:
    return (
        item.resource_available
        and bool(item.recommended_action)
        and item.category in _ACTIONABLE_TECHNICAL_CATEGORIES
    )


def build_daily_narrative_zh(
    events: list[GlobalEventItem],
    technical_items: list[EditorialNewsItem],
) -> str:
    if events:
        titles = "；".join(event.title_zh for event in events[:3])
        groups = "、".join(
            list(
                dict.fromkeys(
                    group
                    for event in events[:3]
                    for group in event.affected_groups_zh
                )
            )[:4]
        )
        return (
            f"今天的全球 AI 重点包括：{titles}。"
            f"主要影响{groups}，事实与原始来源见下方。"
        )
    if technical_items:
        return (
            "今天没有全球重大事件通过核验；"
            f"技术与工具栏有 {len(technical_items)} 条可行动信息。"
        )
    return "今天没有全球重大事件或技术信息通过核验，以下为空榜说明。"


def compose_daily_briefing(
    technical: TechnicalDigestSlice,
    global_result: GlobalPipelineResult,
    now: datetime,
) -> EditorialDigest:
    global_candidate_ids = {
        event.candidate_id for event in global_result.events
    }

    def keep(item: EditorialNewsItem) -> bool:
        return (
            item.candidate_id not in global_candidate_ids
            or _independent_technical_angle(item)
        )

    boards = DigestBoards(
        must_read=[item for item in technical.boards.must_read if keep(item)],
        try_now=[item for item in technical.boards.try_now if keep(item)],
        watch=[item for item in technical.boards.watch if keep(item)],
    )
    technical_items = boards.flatten()
    all_published_at = [
        *(event.published_at for event in global_result.events),
        *(item.published_at for item in technical_items),
    ]
    has_content = bool(global_result.events or technical_items)
    return EditorialDigest(
        run_status="published" if has_content else "no_qualifying_items",
        generated_at=now,
        candidate_count=max(
            technical.candidate_count,
            global_result.stats.candidate_count,
        ),
        source_count=technical.source_count,
        latest_published_at=max(all_published_at, default=None),
        fresh_count_24h=sum(
            0 <= (now - value).total_seconds() <= 24 * 3600
            for value in all_published_at
        ),
        lookback_hours=max(
            technical.lookback_hours,
            168 if global_result.fallback_used else 48,
        ),
        fallback_used=(
            technical.fallback_used or global_result.fallback_used
        ),
        daily_narrative_zh=build_daily_narrative_zh(
            global_result.events,
            technical_items,
        ),
        global_events=global_result.events,
        global_pipeline_stats=global_result.stats,
        boards=boards,
        items=technical_items,
        pipeline_stats=technical.pipeline_stats,
    )
