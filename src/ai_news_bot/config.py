from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .model_backend import BackendSpec, normalize_ollama_base_url
from .models import Category, EditorialLane


DEFAULT_CLOUDFLARE_AI_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"


class RSSSource(BaseModel):
    name: str
    url: str
    tier: int = Field(ge=1, le=3)
    weight: float = Field(ge=0, le=2)
    category_hints: list[Category] = Field(default_factory=list)
    lanes: list[EditorialLane] = Field(
        default_factory=lambda: ["technical"]
    )
    keyword_filter: bool = True


class GitHubQuery(BaseModel):
    name: str
    query: str
    category_hints: list[Category] = Field(default_factory=list)
    lanes: list[EditorialLane] = Field(
        default_factory=lambda: ["technical"]
    )


class WebPageSource(BaseModel):
    name: str
    url: str
    tier: int = Field(ge=1, le=3)
    weight: float = Field(ge=0, le=2)
    category_hints: list[Category] = Field(default_factory=list)
    lanes: list[EditorialLane] = Field(
        default_factory=lambda: ["technical"]
    )
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
    ai_backend_name: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-luna"
    cloudflare_account_id: str = ""
    cloudflare_ai_api_token: str = ""
    cloudflare_ai_model: str = DEFAULT_CLOUDFLARE_AI_MODEL
    ollama_base_url: str = ""
    ollama_model: str = ""
    feishu_webhook_url: str = ""
    feishu_signing_secret: str = ""
    github_token: str = ""
    lookback_hours: int = Field(default=36, ge=6, le=168)
    fallback_lookback_hours: int = Field(default=168, ge=24, le=336)
    max_candidates: int = Field(default=80, ge=10, le=80)
    request_timeout: int = Field(default=20, ge=5, le=60)
    state_path: Path = Path(".state/history.json")
    event_history_path: Path = Path(".state/events.json")
    send_ledger_path: Path = Path(".state/daily_sends.json")
    audit_path: Path = Path(".state/latest_audit.json")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            ai_backend_name=os.getenv("AI_BACKEND", "").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip(),
            cloudflare_account_id=os.getenv(
                "CLOUDFLARE_ACCOUNT_ID", ""
            ).strip(),
            cloudflare_ai_api_token=os.getenv(
                "CLOUDFLARE_AI_API_TOKEN", ""
            ).strip(),
            cloudflare_ai_model=os.getenv(
                "CLOUDFLARE_AI_MODEL", DEFAULT_CLOUDFLARE_AI_MODEL
            ).strip(),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "").strip(),
            ollama_model=os.getenv("OLLAMA_MODEL", "").strip(),
            feishu_webhook_url=os.getenv("FEISHU_WEBHOOK_URL", "").strip(),
            feishu_signing_secret=os.getenv("FEISHU_SIGNING_SECRET", "").strip(),
            github_token=os.getenv("GITHUB_TOKEN", "").strip(),
            lookback_hours=int(os.getenv("LOOKBACK_HOURS", "36")),
            fallback_lookback_hours=int(os.getenv("FALLBACK_LOOKBACK_HOURS", "168")),
            max_candidates=int(os.getenv("MAX_CANDIDATES", "80")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "20")),
            state_path=Path(os.getenv("STATE_PATH", ".state/history.json")),
            event_history_path=Path(
                os.getenv("EVENT_HISTORY_PATH", ".state/events.json")
            ),
            send_ledger_path=Path(
                os.getenv("SEND_LEDGER_PATH", ".state/daily_sends.json")
            ),
            audit_path=Path(
                os.getenv("AUDIT_PATH", ".state/latest_audit.json")
            ),
        )

    def ai_backend(self) -> BackendSpec:
        if self.ai_backend_name:
            return self._explicit_ai_backend()
        return self._legacy_ai_backend()

    def _explicit_ai_backend(self) -> BackendSpec:
        if self.ai_backend_name == "cloudflare":
            return self._cloudflare_backend()
        if self.ai_backend_name == "openai":
            return self._openai_backend()
        if self.ai_backend_name == "ollama":
            return BackendSpec(
                provider_id="ollama",
                provider_label="Ollama",
                api_key="ollama",
                model=self.ollama_model or "qwen3:8b",
                base_url=normalize_ollama_base_url(
                    self.ollama_base_url or "http://127.0.0.1:11434/v1"
                ),
                chat_options={"temperature": 0, "extra_body": {"think": False}},
            )
        raise ValueError("AI_BACKEND must be cloudflare, openai, or ollama")

    def _legacy_ai_backend(self) -> BackendSpec:
        cloudflare_configured = bool(self.cloudflare_account_id)
        cloudflare_token_configured = bool(self.cloudflare_ai_api_token)
        if cloudflare_configured != cloudflare_token_configured:
            raise ValueError(
                "Cloudflare Workers AI 配置不完整；必须同时设置 "
                "CLOUDFLARE_ACCOUNT_ID 和 CLOUDFLARE_AI_API_TOKEN"
            )
        if cloudflare_configured:
            return self._cloudflare_backend()
        if self.openai_api_key:
            return self._openai_backend()
        raise ValueError(
            "缺少 Cloudflare Workers AI 或 OpenAI 凭证；无法执行结构化证据提取"
        )

    def _cloudflare_backend(self) -> BackendSpec:
        if not self.cloudflare_account_id or not self.cloudflare_ai_api_token:
            raise ValueError(
                "Cloudflare Workers AI 配置不完整；必须同时设置 "
                "CLOUDFLARE_ACCOUNT_ID 和 CLOUDFLARE_AI_API_TOKEN"
            )
        if any(character in self.cloudflare_account_id for character in "/?#"):
            raise ValueError("Cloudflare account ID 不能包含 /、? 或 #")
        return BackendSpec(
            provider_id="cloudflare",
            provider_label="Cloudflare Workers AI",
            api_key=self.cloudflare_ai_api_token,
            model=self.cloudflare_ai_model,
            base_url=(
                "https://api.cloudflare.com/client/v4/accounts/"
                f"{self.cloudflare_account_id}/ai/v1"
            ),
        )

    def _openai_backend(self) -> BackendSpec:
        if not self.openai_api_key:
            raise ValueError("缺少 OpenAI 凭证；无法执行结构化证据提取")
        return BackendSpec(
            provider_id="openai",
            provider_label="OpenAI",
            api_key=self.openai_api_key,
            model=self.openai_model,
            base_url=None,
        )


def load_sources(path: Path) -> SourcesConfig:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return SourcesConfig.model_validate(data)
