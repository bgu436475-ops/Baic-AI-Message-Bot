from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .models import Category


class RSSSource(BaseModel):
    name: str
    url: str
    tier: int = Field(ge=1, le=3)
    weight: float = Field(ge=0, le=2)
    category_hints: list[Category] = Field(default_factory=list)
    keyword_filter: bool = True


class GitHubQuery(BaseModel):
    name: str
    query: str
    category_hints: list[Category] = Field(default_factory=list)


class WebPageSource(BaseModel):
    name: str
    url: str
    tier: int = Field(ge=1, le=3)
    weight: float = Field(ge=0, le=2)
    category_hints: list[Category] = Field(default_factory=list)
    item_selector: str
    title_selector: str
    date_selector: str
    summary_selector: str = ""


class GitHubSources(BaseModel):
    enabled: bool = True
    lookback_days: int = Field(default=7, ge=1, le=30)
    per_query: int = Field(default=10, ge=1, le=30)
    queries: list[GitHubQuery] = Field(default_factory=list)


class SourcesConfig(BaseModel):
    rss: list[RSSSource]
    webpages: list[WebPageSource] = Field(default_factory=list)
    github: GitHubSources = Field(default_factory=GitHubSources)


class Settings(BaseModel):
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-luna"
    github_models_model: str = "openai/gpt-4o-mini"
    github_models_base_url: str = "https://models.github.ai/inference"
    feishu_webhook_url: str = ""
    feishu_signing_secret: str = ""
    github_token: str = ""
    target_news_count: int = Field(default=10, ge=1, le=20)
    lookback_hours: int = Field(default=36, ge=6, le=168)
    fallback_lookback_hours: int = Field(default=168, ge=24, le=336)
    max_candidates: int = Field(default=80, ge=10, le=200)
    request_timeout: int = Field(default=20, ge=5, le=60)
    state_path: Path = Path(".state/history.json")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip(),
            github_models_model=os.getenv(
                "GITHUB_MODELS_MODEL", "openai/gpt-4o-mini"
            ).strip(),
            github_models_base_url=os.getenv(
                "GITHUB_MODELS_BASE_URL", "https://models.github.ai/inference"
            ).strip(),
            feishu_webhook_url=os.getenv("FEISHU_WEBHOOK_URL", "").strip(),
            feishu_signing_secret=os.getenv("FEISHU_SIGNING_SECRET", "").strip(),
            github_token=os.getenv("GITHUB_TOKEN", "").strip(),
            target_news_count=int(os.getenv("TARGET_NEWS_COUNT", "10")),
            lookback_hours=int(os.getenv("LOOKBACK_HOURS", "36")),
            fallback_lookback_hours=int(os.getenv("FALLBACK_LOOKBACK_HOURS", "168")),
            max_candidates=int(os.getenv("MAX_CANDIDATES", "80")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "20")),
            state_path=Path(os.getenv("STATE_PATH", ".state/history.json")),
        )

    def ai_backend(self) -> tuple[str, str, str | None, str]:
        if self.openai_api_key:
            return self.openai_api_key, self.openai_model, None, "OpenAI"
        if self.github_token:
            return (
                self.github_token,
                self.github_models_model,
                self.github_models_base_url,
                "GitHub Models",
            )
        raise ValueError(
            "缺少 OPENAI_API_KEY 或 GITHUB_TOKEN；无法执行中文摘要和语义筛选"
        )


def load_sources(path: Path) -> SourcesConfig:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return SourcesConfig.model_validate(data)
