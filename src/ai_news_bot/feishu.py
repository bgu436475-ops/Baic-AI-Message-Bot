from __future__ import annotations

import base64
import hashlib
import hmac
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from .models import CATEGORY_EMOJI, CATEGORY_LABELS, DailyDigest
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _escape_markdown(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("[", "]", "*", "_", "`"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[: max_bytes - 5].decode("utf-8", errors="ignore").rstrip() + "\n\n…"


def make_signature(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def digest_markdown(digest: DailyDigest, include_title: bool = True) -> str:
    date_text = digest.generated_at.astimezone(SHANGHAI).strftime("%Y-%m-%d")
    lines = [f"# AI 每日新闻 · {date_text}", ""] if include_title else []
    for index, item in enumerate(digest.items, start=1):
        label = CATEGORY_LABELS[item.category]
        emoji = CATEGORY_EMOJI[item.category]
        title = _escape_markdown(item.title_zh)
        lines.extend(
            [
                f"**{index}. {emoji} [{title}]({item.url})**  `{label}`",
                item.summary_zh,
                f"*来源：{item.source} · 重要性 {item.importance}*",
                "",
            ]
        )
    lines.append(
        f"共从 {digest.source_count} 个有效来源的 {digest.candidate_count} 条候选中筛选。"
    )
    return "\n".join(lines)


def build_card(digest: DailyDigest) -> dict[str, object]:
    date_text = digest.generated_at.astimezone(SHANGHAI).strftime("%Y-%m-%d")
    content = digest_markdown(digest, include_title=False)
    # Feishu custom-bot requests are limited to 20 KB; leave room for card JSON.
    content = _truncate_utf8(content, 18_000)
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"AI 每日新闻 · {date_text}"},
                "subtitle": {
                    "tag": "plain_text",
                    "content": f"今日精选 {len(digest.items)} 条 · AI 增长内部群",
                },
                "template": "blue",
                "padding": "12px 12px 12px 12px",
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                        "text_align": "left",
                        "text_size": "normal_v2",
                        "margin": "0px 0px 0px 0px",
                    }
                ],
            },
        },
    }


def send_to_feishu(
    digest: DailyDigest,
    webhook_url: str,
    signing_secret: str = "",
    timeout: int = 20,
) -> dict[str, object]:
    if not webhook_url:
        raise ValueError("缺少 FEISHU_WEBHOOK_URL")
    parsed = urlsplit(webhook_url)
    if parsed.scheme != "https" or parsed.netloc not in {
        "open.feishu.cn",
        "open.larksuite.com",
    }:
        raise ValueError("FEISHU_WEBHOOK_URL 必须是飞书/Lark 官方 HTTPS webhook")

    payload = build_card(digest)
    if signing_secret:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = make_signature(timestamp, signing_secret)

    response = requests.post(webhook_url, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if data.get("code", data.get("StatusCode", 0)) != 0:
        raise RuntimeError(f"飞书发送失败：{data}")
    return data
