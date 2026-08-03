from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel


@dataclass(frozen=True)
class BackendSpec:
    provider_id: Literal["cloudflare", "openai", "ollama"]
    provider_label: str
    api_key: str
    model: str
    base_url: str | None
    chat_options: dict[str, Any] = field(default_factory=dict)


def normalize_ollama_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("Ollama base URL must use loopback HTTP")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "Ollama loopback URL cannot contain credentials or query data"
        )
    if parsed.path.rstrip("/") != "/v1":
        raise ValueError("Ollama loopback URL must end with /v1")
    return value.rstrip("/")


def structured_chat_parse(
    client: Any,
    backend: BackendSpec,
    messages: list[dict[str, str]],
    response_format: type[BaseModel],
    *,
    max_tokens: int,
) -> BaseModel | None:
    response = client.chat.completions.parse(
        model=backend.model,
        messages=messages,
        max_tokens=max_tokens,
        response_format=response_format,
        **backend.chat_options,
    )
    return response.choices[0].message.parsed
