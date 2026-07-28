from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


EVIDENCE_URL_LIMIT_BYTES = 256
_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


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


SourceType = Literal[
    "official_announcement",
    "paper",
    "model_card",
    "repository",
    "law_or_regulation",
    "financial_filing",
    "official_demo",
    "trusted_secondary",
]
VerificationStatus = Literal["verified", "unavailable", "blocked", "insufficient"]
BoardName = Literal["must_read", "try_now", "watch"]
RejectionCode = Literal[
    "funding_only",
    "opinion_without_evidence",
    "policy_without_terms_or_date",
    "vague_claim_without_evidence",
    "title_body_conflict",
    "scientific_claim_unverified",
    "duplicate_without_material_update",
    "missing_concrete_change",
    "missing_action",
    "missing_affected_audience",
    "missing_affected_area",
    "invalid_evidence_anchor",
    "unverified_primary_source",
    "evidence_extraction_failed",
]


class ChangeFact(BaseModel):
    change_type: str
    statement: str
    numbers: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class EvidenceAnchor(BaseModel):
    quote: str = Field(min_length=4, max_length=500)
    locator: str = Field(min_length=1, max_length=200)


class EvidenceRecord(BaseModel):
    candidate_id: str
    title_zh: str
    summary_zh: str
    category: Category
    extra_categories: list[Category] = Field(default_factory=list, max_length=3)
    source_url: str
    source_type: SourceType
    verification_status: VerificationStatus
    concrete_changes: list[ChangeFact] = Field(default_factory=list)
    evidence_anchors: list[EvidenceAnchor] = Field(default_factory=list)
    affected_audience: list[str] = Field(default_factory=list)
    affected_area: list[str] = Field(default_factory=list)
    recommended_action: list[str] = Field(default_factory=list)
    event_entities: list[str] = Field(default_factory=list)
    primary_entity: str
    product_or_model: str = ""
    change_signature: str
    version_or_metric: str = ""
    effective_date: str | None = None
    policy_terms: list[str] = Field(default_factory=list)
    relevance_signal: Literal["direct", "adjacent", "low"] = "low"
    action_horizon_days: int | None = Field(default=None, ge=0)
    resource_available: bool = False
    funding_only: bool = False
    opinion_only: bool = False
    policy_claim: bool = False
    vague_claim_without_evidence: bool = False
    title_body_conflict: bool = False
    scientific_claim: bool = False
    original_paper_or_independent_validation: bool = False
    marketing_exaggeration: bool = False
    evidence_covers_full_claim: bool = True
    original_source_status: VerificationStatus | None = None


class GateDecision(BaseModel):
    eligible_main_try: bool
    eligible_watch: bool
    rejection_reasons: list[RejectionCode] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    relevance: int = Field(ge=0, le=25)
    actionability: int = Field(ge=0, le=20)
    specificity: int = Field(ge=0, le=15)
    information_gain: int = Field(ge=0, le=15)
    evidence_quality: int = Field(ge=0, le=15)
    time_sensitivity: int = Field(ge=0, le=10)
    penalties: int = Field(default=0, le=0)

    @computed_field
    @property
    def total(self) -> int:
        return max(
            0,
            self.relevance
            + self.actionability
            + self.specificity
            + self.information_gain
            + self.evidence_quality
            + self.time_sensitivity
            + self.penalties,
        )


class EditorialDraft(BaseModel):
    candidate_id: str = Field(max_length=160)
    original_title: str = Field(max_length=120)
    title_en: str = Field(default="", max_length=120)
    summary_en: str = Field(default="", max_length=320)
    title_zh: str = Field(max_length=80)
    summary_zh: str = Field(max_length=220)
    concrete_change: str = Field(max_length=1200)
    affected_audience: list[
        Annotated[str, Field(max_length=160)]
    ] = Field(max_length=5)
    affected_area: list[
        Annotated[str, Field(max_length=160)]
    ] = Field(max_length=5)
    recommended_action: list[
        Annotated[str, Field(max_length=300)]
    ] = Field(max_length=5)
    evidence_url: str = Field(max_length=1000)
    verification_status: VerificationStatus
    event_fingerprint: str = Field(max_length=1000)
    update_of: str | None = Field(default=None, max_length=500)
    primary_entity: str = Field(max_length=160)
    product_or_model: str = Field(default="", max_length=160)
    event_entities: list[
        Annotated[str, Field(max_length=160)]
    ] = Field(max_length=10)
    change_signature: str = Field(max_length=160)
    version_or_metric: str = Field(default="", max_length=120)
    effective_date: str | None = Field(default=None, max_length=32)
    resource_available: bool = False
    scientific_verified: bool = False
    source: str = Field(max_length=120)
    published_at: datetime
    category: Category
    extra_categories: list[Category] = Field(
        default_factory=list,
        max_length=3,
    )
    score: ScoreBreakdown

    @field_validator("evidence_url")
    @classmethod
    def validate_evidence_url(cls, value: str) -> str:
        if (
            value != value.strip()
            or len(value.encode("utf-8")) > EVIDENCE_URL_LIMIT_BYTES
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            )
        ):
            raise ValueError("evidence_url is malformed or too long")
        try:
            parsed = urlsplit(value)
            _ = parsed.port
        except ValueError as error:
            raise ValueError("evidence_url is malformed") from error
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("evidence_url must be credential-free HTTPS")
        return value

    @field_validator("effective_date")
    @classmethod
    def validate_effective_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _DATE_ONLY.fullmatch(value):
            raise ValueError("effective_date must be YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("effective_date is not a calendar date") from error
        return value


class EditorialNewsItem(EditorialDraft):
    board: BoardName


class DigestBoards(BaseModel):
    must_read: list[EditorialNewsItem] = Field(default_factory=list, max_length=5)
    try_now: list[EditorialNewsItem] = Field(default_factory=list, max_length=3)
    watch: list[EditorialNewsItem] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_item_board_membership(self) -> "DigestBoards":
        for board, items in (
            ("must_read", self.must_read),
            ("try_now", self.try_now),
            ("watch", self.watch),
        ):
            if any(item.board != board for item in items):
                raise ValueError("board items must match their board")
        return self

    def flatten(self) -> list[EditorialNewsItem]:
        return [*self.must_read, *self.try_now, *self.watch]


class PipelineStats(BaseModel):
    candidate_count: int = Field(ge=0)
    shortlist_count: int = Field(ge=0)
    source_verified_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    top_rejection_reasons: dict[str, int] = Field(default_factory=dict)


class EditorialDigest(BaseModel):
    schema_version: Literal[3] = 3
    run_status: Literal["published", "no_qualifying_items"] = "published"
    generated_at: datetime
    candidate_count: int
    source_count: int
    latest_published_at: datetime | None = None
    fresh_count_24h: int = 0
    lookback_hours: int = 36
    fallback_used: bool = False
    boards: DigestBoards
    items: list[EditorialNewsItem] = Field(max_length=11)
    pipeline_stats: PipelineStats

    @model_validator(mode="after")
    def validate_contract(self) -> "EditorialDigest":
        flattened = self.boards.flatten()
        fingerprints = [item.event_fingerprint for item in flattened]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("board items must be mutually exclusive")
        if self.items != flattened:
            raise ValueError("items must equal the flattened boards")
        if self.run_status == "published" and not flattened:
            raise ValueError("published digests require an item")
        if self.run_status == "no_qualifying_items" and flattened:
            raise ValueError("empty digests cannot include items")
        return self
