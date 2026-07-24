from __future__ import annotations

import base64
import hashlib
import hmac
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from .models import (
    CATEGORY_EMOJI,
    CATEGORY_LABELS,
    DailyDigest,
    EditorialDigest,
    EditorialNewsItem,
)
SHANGHAI = ZoneInfo("Asia/Shanghai")

BOARD_LABELS = {
    "must_read": "今日必看",
    "try_now": "值得试用",
    "watch": "观察项",
}

REJECTION_LABELS = {
    "funding_only": "只有融资金额，缺少业务或技术数据",
    "opinion_without_evidence": "只有观点，缺少事实证据",
    "policy_without_terms_or_date": "政策缺少具体条款或生效时间",
    "vague_claim_without_evidence": "模糊结论缺少对应证据",
    "title_body_conflict": "标题与正文信息冲突",
    "scientific_claim_unverified": "科学结论缺少原始论文或独立验证",
    "duplicate_without_material_update": "过去 7 天重复",
    "missing_concrete_change": "缺少具体变化",
    "missing_action": "缺少可执行行动",
    "missing_affected_audience": "缺少受影响对象",
    "missing_affected_area": "缺少受影响内容",
    "invalid_evidence_anchor": "证据无法核查",
    "unverified_primary_source": "原始来源未核查",
}


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


def _legacy_digest_markdown(
    digest: DailyDigest,
    include_title: bool,
) -> str:
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


def _render_editorial_item(
    item: EditorialNewsItem,
    index: int,
) -> list[str]:
    title = _escape_markdown(item.title_zh)
    concrete_change = _escape_markdown(item.concrete_change)
    affected_audience = "、".join(
        _escape_markdown(value) for value in item.affected_audience
    )
    affected_area = "、".join(
        _escape_markdown(value) for value in item.affected_area
    )
    recommended_action = "；".join(
        _escape_markdown(value) for value in item.recommended_action
    )
    warning = (
        "  ⚠ 原始来源暂不可核查"
        if (
            item.board == "watch"
            and item.verification_status in {"unavailable", "blocked"}
        )
        else ""
    )
    return [
        (
            f"**{index}. [{title}]({item.evidence_url})**  "
            f"`总分 {item.score.total}`"
        ),
        f"具体变化：{concrete_change}",
        f"影响：{affected_audience} · {affected_area}",
        f"建议行动：{recommended_action}",
        f"[核查原文]({item.evidence_url}){warning}",
        "",
    ]


def _editorial_digest_markdown(
    digest: EditorialDigest,
    include_title: bool,
) -> str:
    date_text = digest.generated_at.astimezone(SHANGHAI).strftime("%Y-%m-%d")
    lines = [f"# AI 每日新闻 · {date_text}", ""] if include_title else []
    if digest.run_status == "no_qualifying_items":
        stats = digest.pipeline_stats
        lines.extend(
            [
                "**今日无内容通过硬门槛**",
                "",
                (
                    f"已检查候选 {stats.candidate_count} 条，"
                    f"粗筛 {stats.shortlist_count} 条，"
                    f"已核查来源 {stats.source_verified_count} 条。"
                ),
                "",
                "主要淘汰原因：",
            ]
        )
        reasons = sorted(
            stats.top_rejection_reasons.items(),
            key=lambda reason: (-reason[1], reason[0]),
        )
        if reasons:
            lines.extend(
                f"- {REJECTION_LABELS.get(code, code)}：{count}"
                for code, count in reasons
            )
        else:
            lines.append("- 无：本轮未产生可筛选候选")
        return "\n".join(lines)

    for board_name, items in (
        ("must_read", digest.boards.must_read),
        ("try_now", digest.boards.try_now),
        ("watch", digest.boards.watch),
    ):
        if not items:
            continue
        lines.extend([f"## {BOARD_LABELS[board_name]}", ""])
        for index, item in enumerate(items, start=1):
            lines.extend(_render_editorial_item(item, index))
    return "\n".join(lines).rstrip()


def digest_markdown(
    digest: DailyDigest | EditorialDigest,
    include_title: bool = True,
) -> str:
    if isinstance(digest, EditorialDigest):
        return _editorial_digest_markdown(digest, include_title)
    return _legacy_digest_markdown(digest, include_title)


def build_card(digest: DailyDigest | EditorialDigest) -> dict[str, object]:
    date_text = digest.generated_at.astimezone(SHANGHAI).strftime("%Y-%m-%d")
    content = digest_markdown(digest, include_title=False)
    # Feishu custom-bot requests are limited to 20 KB; leave room for card JSON.
    content = _truncate_utf8(content, 18_000)
    subtitle = (
        "严格筛选完成 · AI 增长内部群"
        if (
            isinstance(digest, EditorialDigest)
            and digest.run_status == "no_qualifying_items"
        )
        else f"今日精选 {len(digest.items)} 条 · AI 增长内部群"
    )
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"AI 每日新闻 · {date_text}"},
                "subtitle": {
                    "tag": "plain_text",
                    "content": subtitle,
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
    digest: DailyDigest | EditorialDigest,
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
