from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests

from .models import (
    CATEGORY_EMOJI,
    CATEGORY_LABELS,
    DailyDigest,
    EVIDENCE_URL_LIMIT_BYTES,
    EditorialDigest,
    EditorialNewsItem,
    GlobalEventItem,
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
EDITORIAL_MARKDOWN_LIMIT_BYTES = 18_000
FEISHU_BODY_LIMIT_BYTES = 20_000

EDITORIAL_FIELD_LIMITS = {
    "title": 120,
    "concrete_change": 300,
    "affected_audience": 120,
    "affected_area": 120,
    "recommended_action": 240,
}

BOARD_LABELS = {
    "must_read": "今日必看",
    "try_now": "值得试用",
    "watch": "观察项",
}

GLOBAL_CATEGORY_LABELS = {
    "models_products": "模型与产品",
    "companies_business": "公司与商业",
    "policy_regulation": "政策与监管",
    "research_breakthroughs": "科研突破",
    "adoption_society": "大众应用与社会影响",
}

GLOBAL_FIELD_LIMITS = {
    "title": 180,
    "what_happened": 900,
    "why_it_matters": 720,
    "affected_groups": 300,
    "key_facts": 600,
    "source_name": 180,
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


def _bounded_markdown_text(value: str, max_bytes: int) -> str:
    normalized = " ".join(value.split())
    units: list[str] = []
    for character in normalized:
        if character == "\\":
            units.append("\\\\")
        elif character in {"[", "]", "*", "_", "`"}:
            units.append(f"\\{character}")
        else:
            units.append(character)
    escaped = "".join(units)
    if len(escaped.encode("utf-8")) <= max_bytes:
        return escaped

    suffix = "…"
    remaining = max_bytes - len(suffix.encode("utf-8"))
    kept: list[str] = []
    for unit in units:
        unit_size = len(unit.encode("utf-8"))
        if unit_size > remaining:
            break
        kept.append(unit)
        remaining -= unit_size
    return "".join(kept).rstrip() + suffix


def _safe_evidence_url(value: str) -> str:
    if value != value.strip() or any(
        ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise ValueError("证据链接格式无效")
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("证据链接必须是有效的 HTTPS 原始来源")
    try:
        port = parsed.port
        hostname = parsed.hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError) as error:
        raise ValueError("证据链接格式无效") from error
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = hostname if port is None else f"{hostname}:{port}"
    safe_url = urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            quote(parsed.path, safe="/:@!$&'*+,;=%~._-"),
            quote(parsed.query, safe="/?:@!$&'*+,;=%~._-"),
            quote(parsed.fragment, safe="/?:@!$&'*+,;=%~._-"),
        )
    )
    if len(safe_url.encode("utf-8")) > EVIDENCE_URL_LIMIT_BYTES:
        raise ValueError(
            "证据链接过长，无法在不破坏原始地址的情况下安全发送"
        )
    return safe_url


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
    title = _bounded_markdown_text(
        item.title_zh,
        EDITORIAL_FIELD_LIMITS["title"],
    )
    concrete_change = _bounded_markdown_text(
        item.concrete_change,
        EDITORIAL_FIELD_LIMITS["concrete_change"],
    )
    affected_audience = _bounded_markdown_text(
        "、".join(item.affected_audience),
        EDITORIAL_FIELD_LIMITS["affected_audience"],
    )
    affected_area = _bounded_markdown_text(
        "、".join(item.affected_area),
        EDITORIAL_FIELD_LIMITS["affected_area"],
    )
    recommended_action = _bounded_markdown_text(
        "；".join(item.recommended_action),
        EDITORIAL_FIELD_LIMITS["recommended_action"],
    )
    evidence_url = _safe_evidence_url(item.evidence_url)
    warning = (
        "  ⚠ 原始来源暂不可核查"
        if (
            item.board == "watch"
            and item.verification_status in {"unavailable", "blocked"}
        )
        else ""
    )
    return [
        f"**{index}. {title}**  `总分 {item.score.total}`",
        f"具体变化：{concrete_change}",
        f"影响：{affected_audience} · {affected_area}",
        f"建议行动：{recommended_action}",
        f"[核查原文]({evidence_url}){warning}",
        "",
    ]


def _render_global_event(
    digest: EditorialDigest,
    item: GlobalEventItem,
    index: int,
) -> list[str]:
    title = _bounded_markdown_text(
        item.title_zh,
        GLOBAL_FIELD_LIMITS["title"],
    )
    what_happened = _bounded_markdown_text(
        item.what_happened_zh,
        GLOBAL_FIELD_LIMITS["what_happened"],
    )
    why_it_matters = _bounded_markdown_text(
        item.why_it_matters_zh,
        GLOBAL_FIELD_LIMITS["why_it_matters"],
    )
    affected_groups = _bounded_markdown_text(
        "、".join(item.affected_groups_zh),
        GLOBAL_FIELD_LIMITS["affected_groups"],
    )
    key_facts = _bounded_markdown_text(
        "；".join(item.key_facts),
        GLOBAL_FIELD_LIMITS["key_facts"],
    )
    source_name = _bounded_markdown_text(
        item.source_name,
        GLOBAL_FIELD_LIMITS["source_name"],
    )
    source_url = _safe_evidence_url(item.source_url)
    label = GLOBAL_CATEGORY_LABELS[item.category]
    event_date = item.published_at.astimezone(SHANGHAI).strftime("%Y-%m-%d")
    fallback = (
        digest.generated_at - item.published_at
    ).total_seconds() > 48 * 3600
    return [
        f"**{index}. 🌍 [{label}] {title}**",
        f"发生了什么：{what_happened}",
        f"为什么重要：{why_it_matters}",
        f"影响：{affected_groups}",
        f"关键事实：{key_facts}",
        f"日期：{event_date}{' · 回看' if fallback else ''}",
        f"来源：{source_name} · [查看原文]({source_url})",
        "",
    ]


def _technical_items_for_feishu(
    digest: EditorialDigest,
) -> list[EditorialNewsItem]:
    return digest.boards.flatten()[:5]


def _published_editorial_lines(
    digest: EditorialDigest,
    technical_items: list[EditorialNewsItem],
) -> list[str]:
    lines = [
        "## 一分钟读懂今天",
        "",
        _bounded_markdown_text(digest.daily_narrative_zh, 1_500),
        "",
    ]
    if digest.global_events:
        lines.extend(["## 全球 AI 重大事件", ""])
        for index, item in enumerate(digest.global_events, start=1):
            lines.extend(_render_global_event(digest, item, index))
    if technical_items:
        lines.extend(["## 技术与工具", ""])
        current_board = ""
        board_index = 0
        for item in technical_items:
            if item.board != current_board:
                current_board = item.board
                board_index = 0
                lines.extend([f"### {BOARD_LABELS[current_board]}", ""])
            board_index += 1
            lines.extend(_render_editorial_item(item, board_index))
    return lines


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
        elif any(
            (
                stats.candidate_count,
                stats.shortlist_count,
                stats.source_verified_count,
                stats.rejected_count,
            )
        ):
            lines.append(
                "- 未记录可归类淘汰原因；本轮内容未达到最终分榜阈值"
            )
        else:
            lines.append("- 无：本轮未产生候选")
        return "\n".join(lines)

    prefix = lines
    technical_items = _technical_items_for_feishu(digest)
    while True:
        content = "\n".join(
            [
                *prefix,
                *_published_editorial_lines(digest, technical_items),
            ]
        ).rstrip()
        if len(content.encode("utf-8")) <= EDITORIAL_MARKDOWN_LIMIT_BYTES:
            return content
        if technical_items:
            technical_items = technical_items[:-1]
            continue
        raise ValueError("飞书卡片内容超过安全预算，未发送不完整简报")


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
    if isinstance(digest, DailyDigest):
        content = _truncate_utf8(content, EDITORIAL_MARKDOWN_LIMIT_BYTES)
    subtitle = (
        "严格筛选完成 · AI 增长内部群"
        if (
            isinstance(digest, EditorialDigest)
            and digest.run_status == "no_qualifying_items"
        )
        else (
            f"全球大事 {len(digest.global_events)} · "
            f"技术情报 {len(_technical_items_for_feishu(digest))} · "
            "AI 增长内部群"
            if isinstance(digest, EditorialDigest)
            else f"今日精选 {len(digest.items)} 条 · AI 增长内部群"
        )
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

    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(body) >= FEISHU_BODY_LIMIT_BYTES:
        raise ValueError("飞书请求体超过 20 KB，拒绝发送不完整简报")
    response = requests.post(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code", data.get("StatusCode", 0)) != 0:
        raise RuntimeError(f"飞书发送失败：{data}")
    return data
