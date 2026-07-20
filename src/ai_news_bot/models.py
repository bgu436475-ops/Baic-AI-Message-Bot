from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


Category = Literal[
    "new_models",
    "ai_coding",
    "agents",
    "image_video",
    "comfyui",
    "open_source",
    "mcp",
    "skills",
    "industry_business",
]

CATEGORY_LABELS: dict[str, str] = {
    "new_models": "新模型",
    "ai_coding": "AI 编程",
    "agents": "Agent",
    "image_video": "图片/视频",
    "comfyui": "ComfyUI",
    "open_source": "开源项目",
    "mcp": "MCP",
    "skills": "Skill",
    "industry_business": "行业/商业",
}

CATEGORY_EMOJI: dict[str, str] = {
    "new_models": "🧠",
    "ai_coding": "💻",
    "agents": "🤖",
    "image_video": "🎨",
    "comfyui": "🧩",
    "open_source": "🌟",
    "mcp": "🔌",
    "skills": "🛠️",
    "industry_business": "📈",
}


class Candidate(BaseModel):
    id: str
    title: str
    summary: str = ""
    url: str
    source: str
    source_tier: int = Field(ge=1, le=3)
    source_weight: float = Field(ge=0, le=2)
    published_at: datetime
    category_hints: list[Category] = Field(default_factory=list)
    metrics: dict[str, int | float | str] = Field(default_factory=dict)


class SelectedByAI(BaseModel):
    candidate_id: str
    title_zh: str = Field(description="准确、简洁的中文标题")
    summary_zh: str = Field(description="1 至 2 句中文摘要，只使用候选材料中的事实")
    category: Category
    extra_categories: list[Category] = Field(default_factory=list, max_length=3)
    importance: int = Field(ge=1, le=100)


class AISelection(BaseModel):
    items: list[SelectedByAI]


class NewsItem(BaseModel):
    original_title: str
    title_en: str = ""
    summary_en: str = ""
    title_zh: str
    summary_zh: str
    url: str
    source: str
    published_at: datetime
    category: Category
    extra_categories: list[Category] = Field(default_factory=list)
    importance: int = Field(ge=1, le=100)


class DailyDigest(BaseModel):
    schema_version: Literal[2] = 2
    run_status: Literal["published", "no_qualifying_items"] = "published"
    generated_at: datetime
    candidate_count: int
    source_count: int
    latest_published_at: datetime | None = None
    fresh_count_24h: int = 0
    lookback_hours: int = 36
    fallback_used: bool = False
    items: list[NewsItem]

    @model_validator(mode="after")
    def validate_run_status_matches_items(self) -> "DailyDigest":
        if self.run_status == "published" and not self.items:
            raise ValueError("published daily digests must include at least one item")
        if self.run_status == "no_qualifying_items" and self.items:
            raise ValueError("empty daily results cannot include items")
        return self
