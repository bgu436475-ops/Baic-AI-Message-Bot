from __future__ import annotations

from .models import EvidenceRecord
from .text import truncate


MAX_ACTION_LENGTH = 300

_PRICING_MARKERS = (
    "price",
    "pricing",
    "cost",
    "billing",
    "价格",
    "费用",
    "成本",
)
_POLICY_MARKERS = (
    "policy",
    "law",
    "regulation",
    "terms",
    "compliance",
    "政策",
    "法规",
    "条款",
    "合规",
)
_BENCHMARK_MARKERS = (
    "benchmark",
    "evaluation",
    "eval",
    "score",
    "基准",
    "评测",
    "评分",
)
_REPOSITORY_MARKERS = (
    "repository",
    "repo",
    "open_source",
    "github",
    "开源",
    "仓库",
)
_RELEASE_MARKERS = (
    "api",
    "sdk",
    "model",
    "release",
    "version",
    "launch",
    "模型",
    "发布",
    "版本",
)


def _first_nonblank(values: list[str]) -> str | None:
    return next(
        (normalized for value in values if (normalized := " ".join(value.split()))),
        None,
    )


def _action_horizon(days: int | None) -> str:
    if days == 0:
        return "今天"
    bounded_days = min(30, days) if days is not None else 7
    return f"{bounded_days}天内"


def _matches(change_type: str, markers: tuple[str, ...]) -> bool:
    normalized = change_type.casefold()
    return any(marker in normalized for marker in markers)


def _action_prefix(
    change_type: str,
    audience: str,
    area: str,
    horizon: str,
) -> str:
    if _matches(change_type, _PRICING_MARKERS):
        return (
            f"{audience}应在{horizon}按当前用量重新计算{area}，"
            "并与当前方案对比"
        )
    if _matches(change_type, _POLICY_MARKERS):
        return (
            f"{audience}应在{horizon}核对{area}的适用范围和生效时间，"
            "并更新合规清单"
        )
    if _matches(change_type, _BENCHMARK_MARKERS):
        return (
            f"{audience}应在{horizon}使用自身任务集复测{area}，"
            "不要仅凭公开基准改变选型"
        )
    if _matches(change_type, _REPOSITORY_MARKERS):
        return (
            f"{audience}应在{horizon}于隔离环境验证{area}，"
            "并核查安装方式、许可证和维护状态"
        )
    if _matches(change_type, _RELEASE_MARKERS):
        return (
            f"{audience}应在{horizon}先在非生产环境验证{area}的"
            "兼容性、性能和成本，再决定是否采用"
        )
    return (
        f"{audience}应在{horizon}针对{area}进行小范围验证，"
        "再决定是否扩大使用"
    )


def _bounded_action(prefix: str, statement: str) -> str:
    separator = "。依据："
    basis_limit = max(0, MAX_ACTION_LENGTH - len(prefix) - len(separator))
    basis = truncate(statement, basis_limit)
    return truncate(f"{prefix}{separator}{basis}", MAX_ACTION_LENGTH)


def derive_recommended_action(record: EvidenceRecord) -> EvidenceRecord:
    audience = _first_nonblank(record.affected_audience)
    area = _first_nonblank(record.affected_area)
    change = next(
        (
            value
            for value in record.concrete_changes
            if value.statement.strip()
        ),
        None,
    )
    if change is None or audience is None or area is None:
        return record.model_copy(update={"recommended_action": []})

    prefix = _action_prefix(
        change.change_type,
        audience,
        area,
        _action_horizon(record.action_horizon_days),
    )
    return record.model_copy(
        update={
            "recommended_action": [
                _bounded_action(prefix, change.statement)
            ]
        }
    )
