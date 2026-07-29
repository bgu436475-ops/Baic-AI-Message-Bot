from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_news_bot.feishu import FEISHU_BODY_LIMIT_BYTES, build_card
from ai_news_bot.models import EditorialDigest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "tests/fixtures/global_events_validation.json"
GLOBAL_CATEGORIES = {
    "models_products",
    "companies_business",
    "policy_regulation",
    "research_breakthroughs",
    "adoption_society",
}


def build_preview(
    output_dir: Path,
    fixture_path: Path = DEFAULT_FIXTURE,
) -> tuple[Path, Path]:
    digest = EditorialDigest.model_validate_json(
        fixture_path.read_text(encoding="utf-8")
    )
    if {item.category for item in digest.global_events} != GLOBAL_CATEGORIES:
        raise ValueError("preview fixture must cover every global event category")
    required_chinese = [
        digest.daily_narrative_zh,
        *(
            value
            for item in digest.global_events
            for value in (
                item.title_zh,
                item.what_happened_zh,
                item.why_it_matters_zh,
                *item.affected_groups_zh,
                *item.key_facts,
            )
        ),
    ]
    if any(not value.strip() for value in required_chinese):
        raise ValueError("preview contains a blank required Chinese field")

    card = build_card(digest)
    compact_body = json.dumps(
        card,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(compact_body) >= FEISHU_BODY_LIMIT_BYTES:
        raise ValueError("preview Feishu request is at least 20 KB")

    output_dir.mkdir(parents=True, exist_ok=True)
    digest_path = output_dir / "latest-v4.json"
    card_path = output_dir / "feishu-card.json"
    digest_path.write_text(
        digest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    card_path.write_text(
        json.dumps(card, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return digest_path, card_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an offline schema-v4 global events preview"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    args = parser.parse_args()
    build_preview(args.output_dir)


if __name__ == "__main__":
    main()
