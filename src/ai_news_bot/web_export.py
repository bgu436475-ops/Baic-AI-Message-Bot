from __future__ import annotations

from pathlib import Path

from .models import DailyDigest


def export_digest_for_web(digest: DailyDigest, output_path: Path) -> None:
    """Write the latest digest to the JSON contract consumed by the website."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        digest.model_dump_json(indent=2),
        encoding="utf-8",
    )
