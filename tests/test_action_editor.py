from __future__ import annotations

from importlib import import_module, util

import pytest

from ai_news_bot.action_editor import derive_recommended_action
from ai_news_bot.models import ChangeFact, EvidenceAnchor, EvidenceRecord


def record(
    *,
    change_type: str = "pricing",
    statement: str = "Model X API input price falls from $2 to $1.",
    action_horizon_days: int | None = 3,
) -> EvidenceRecord:
    return EvidenceRecord(
        candidate_id="one",
        title_zh="Model X API 输入价格下降",
        summary_zh="输入价格从 2 美元降至 1 美元。",
        category="new_models",
        source_url="https://example.com/pricing",
        source_type="official_announcement",
        verification_status="verified",
        concrete_changes=[
            ChangeFact(
                change_type=change_type,
                statement=statement,
                numbers=["$2", "$1"],
                entities=["Model X API"],
            )
        ],
        evidence_anchors=[
            EvidenceAnchor(
                quote=statement,
                locator="Pricing",
            )
        ],
        affected_audience=["API 开发者"],
        affected_area=["推理成本"],
        recommended_action=["立即购买并全面迁移"],
        event_entities=["Example", "Model X"],
        primary_entity="Example",
        product_or_model="Model X",
        change_signature="api-price-change",
        version_or_metric="$2-to-$1",
        relevance_signal="direct",
        action_horizon_days=action_horizon_days,
        resource_available=True,
    )


def test_action_editor_module_exposes_expected_api() -> None:
    spec = util.find_spec("ai_news_bot.action_editor")

    assert spec is not None
    module = import_module("ai_news_bot.action_editor")
    assert callable(module.derive_recommended_action)


@pytest.mark.parametrize(
    ("change_type", "statement", "expected_phrases"),
    [
        (
            "pricing",
            "Model X API input price falls from $2 to $1.",
            ("重新计算", "推理成本", "当前方案"),
        ),
        (
            "api_release",
            "Model X API v2 is available.",
            ("非生产环境", "兼容性", "再决定是否采用"),
        ),
        (
            "policy_terms",
            "The new reporting rule takes effect on 2026-08-01.",
            ("适用范围", "生效时间", "合规清单"),
        ),
        (
            "benchmark",
            "Model X scores 72.4 on Benchmark Y.",
            ("自身任务集", "公开基准"),
        ),
        (
            "repository_release",
            "Project X v2.0 is released under the Apache-2.0 license.",
            ("隔离环境", "许可证", "维护状态"),
        ),
        (
            "capacity",
            "The context window increases from 128K to 256K.",
            ("小范围验证", "推理成本"),
        ),
    ],
)
def test_action_editor_uses_change_specific_grounded_templates(
    change_type: str,
    statement: str,
    expected_phrases: tuple[str, ...],
) -> None:
    edited = derive_recommended_action(
        record(change_type=change_type, statement=statement)
    )

    assert len(edited.recommended_action) == 1
    action = edited.recommended_action[0]
    assert all(phrase in action for phrase in expected_phrases)
    assert "API 开发者" in action
    assert "3天内" in action
    assert f"依据：{statement}" in action
    assert "立即购买并全面迁移" not in action
    assert len(action) <= 300


@pytest.mark.parametrize(
    ("days", "expected"),
    [(0, "今天"), (1, "1天内"), (7, "7天内"), (30, "30天内"), (None, "7天内")],
)
def test_action_editor_uses_bounded_action_horizon(
    days: int | None,
    expected: str,
) -> None:
    edited = derive_recommended_action(
        record(action_horizon_days=days)
    )

    assert expected in edited.recommended_action[0]


@pytest.mark.parametrize(
    "update",
    [
        {"concrete_changes": []},
        {"affected_audience": []},
        {"affected_area": []},
    ],
    ids=["no-change", "no-audience", "no-area"],
)
def test_action_editor_does_not_fill_missing_hard_gate_inputs(
    update: dict[str, list[object]],
) -> None:
    edited = derive_recommended_action(
        record().model_copy(update=update)
    )

    assert edited.recommended_action == []
