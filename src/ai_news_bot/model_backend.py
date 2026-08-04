from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import requests
from openai import OpenAI
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


def is_ollama_loopback_url(value: str | None) -> bool:
    if value is None:
        return False
    try:
        normalize_ollama_base_url(value)
    except ValueError:
        return False
    return True


def create_openai_client(
    *,
    api_key: str,
    base_url: str | None,
    client_factory: Callable[..., Any] = OpenAI,
    max_retries: int | None = None,
    disable_environment_proxy: bool = False,
) -> Any:
    """Construct an OpenAI-compatible client without proxying Ollama loopback."""
    arguments: dict[str, object] = {
        "api_key": api_key,
        "base_url": base_url,
    }
    if max_retries is not None:
        arguments["max_retries"] = max_retries
    if disable_environment_proxy:
        arguments["http_client"] = httpx.Client(trust_env=False)
    return client_factory(**arguments)


def create_model_client(
    backend: BackendSpec,
    *,
    client_factory: Callable[..., Any] = OpenAI,
    max_retries: int | None = None,
) -> Any:
    """Construct the configured model client with provider-specific transport rules."""
    return create_openai_client(
        api_key=backend.api_key,
        base_url=backend.base_url,
        client_factory=client_factory,
        max_retries=max_retries,
        disable_environment_proxy=backend.provider_id == "ollama",
    )


def create_ollama_session() -> requests.Session:
    """Create a loopback-only requests transport that ignores inherited proxies."""
    session = requests.Session()
    session.trust_env = False
    return session


def structured_chat_parse(
    client: Any,
    backend: BackendSpec,
    messages: list[dict[str, str]],
    response_format: type[BaseModel],
    *,
    max_tokens: int,
) -> BaseModel | None:
    if backend.provider_id == "cloudflare":
        # Workers AI may return the JSON object directly in `message.content`.
        # The OpenAI SDK's `.parse()` path expects that field to be a string and
        # rejects an otherwise valid Cloudflare response before exposing it.
        response = client.chat.completions.create(
            model=backend.model,
            messages=messages,
            max_tokens=max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": response_format.model_json_schema(),
            },
            **backend.chat_options,
        )
        content = response.choices[0].message.content
        if isinstance(content, str):
            return response_format.model_validate_json(content)
        if isinstance(content, dict):
            return response_format.model_validate(content)
        raise ValueError("Cloudflare response content must be JSON text or an object")
    response = client.chat.completions.parse(
        model=backend.model,
        messages=messages,
        max_tokens=max_tokens,
        response_format=response_format,
        **backend.chat_options,
    )
    return response.choices[0].message.parsed
