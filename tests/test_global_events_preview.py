from __future__ import annotations

import json
from pathlib import Path

from ai_news_bot.feishu import FEISHU_BODY_LIMIT_BYTES
from ai_news_bot.models import EditorialDigest
from scripts.build_global_events_preview import build_preview


def test_preview_contains_all_global_categories_and_no_linked_title(
    tmp_path: Path,
) -> None:
    build_preview(tmp_path)

    digest = EditorialDigest.model_validate_json(
        (tmp_path / "latest-v4.json").read_text(encoding="utf-8")
    )
    card = json.loads(
        (tmp_path / "feishu-card.json").read_text(encoding="utf-8")
    )
    assert {item.category for item in digest.global_events} == {
        "models_products",
        "companies_business",
        "policy_regulation",
        "research_breakthroughs",
        "adoption_society",
    }
    content = card["card"]["body"]["elements"][0]["content"]
    assert "[查看原文](" in content
    assert "[Acme 正式发布" not in content
    body = json.dumps(
        card,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(body) < FEISHU_BODY_LIMIT_BYTES
