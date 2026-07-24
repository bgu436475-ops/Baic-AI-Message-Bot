from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_news_bot.boards import ScoredEditorialCandidate, build_boards
from ai_news_bot.event_history import DuplicateAssessment
from ai_news_bot.models import (
    ChangeFact,
    EditorialDraft,
    EvidenceAnchor,
    EvidenceRecord,
    GateDecision,
    ScoreBreakdown,
)


NOW = datetime(2026, 7, 23, 1, 5, tzinfo=UTC)


def scored(
    candidate_id: str,
    *,
    total: int = 80,
    evidence: int = 15,
    gain: int = 15,
    action: int = 20,
    company: str = "Acme",
    resource: bool = False,
    horizon: int | None = None,
    eligible_main_try: bool = True,
    eligible_watch: bool = True,
    published_at: datetime = NOW,
    fingerprint: str | None = None,
    assessment: DuplicateAssessment | None = None,
) -> ScoredEditorialCandidate:
    score = ScoreBreakdown(
        relevance=25,
        actionability=action,
        specificity=15,
        information_gain=gain,
        evidence_quality=evidence,
        time_sensitivity=10,
        penalties=total - (25 + action + 15 + gain + evidence + 10),
    )
    event_fingerprint = fingerprint or f"fingerprint-{candidate_id}"
    record = EvidenceRecord(
        candidate_id=candidate_id,
        title_zh=f"{candidate_id} 标题",
        summary_zh=f"{candidate_id} 摘要",
        category="new_models",
        source_url=f"https://example.com/{candidate_id}",
        source_type="official_announcement",
        verification_status="verified",
        concrete_changes=[
            ChangeFact(
                change_type="release",
                statement=f"{candidate_id} has changed.",
            )
        ],
        evidence_anchors=[
            EvidenceAnchor(quote=f"{candidate_id} has changed.", locator="body")
        ],
        affected_audience=["developers"],
        affected_area=["workflow"],
        recommended_action=["Review the change"],
        event_entities=[company, candidate_id],
        primary_entity=company,
        product_or_model=candidate_id,
        change_signature="release",
        version_or_metric="v2",
        relevance_signal="direct",
        action_horizon_days=horizon,
        resource_available=resource,
    )
    draft = EditorialDraft(
        candidate_id=candidate_id,
        original_title=f"{candidate_id} title",
        title_zh=record.title_zh,
        summary_zh=record.summary_zh,
        concrete_change=record.concrete_changes[0].statement,
        affected_audience=record.affected_audience,
        affected_area=record.affected_area,
        recommended_action=record.recommended_action,
        evidence_url=record.source_url,
        verification_status=record.verification_status,
        event_fingerprint=event_fingerprint,
        primary_entity=company,
        event_entities=record.event_entities,
        change_signature=record.change_signature,
        version_or_metric=record.version_or_metric,
        resource_available=resource,
        source=company,
        published_at=published_at,
        category=record.category,
        score=score,
    )
    return ScoredEditorialCandidate(
        record=record,
        decision=GateDecision(
            eligible_main_try=eligible_main_try,
            eligible_watch=eligible_watch,
        ),
        assessment=assessment or DuplicateAssessment(status="unique"),
        draft=draft,
    )


def ids(items: list[EditorialDraft]) -> list[str]:
    return [item.candidate_id for item in items]


def test_boards_are_mutually_exclusive_and_never_pad() -> None:
    result = build_boards(
        [
            scored(
                "a",
                total=80,
                evidence=15,
                gain=15,
                action=20,
                company="A",
            ),
            scored(
                "b",
                total=65,
                evidence=12,
                gain=9,
                action=16,
                resource=True,
                horizon=7,
                company="B",
            ),
            scored(
                "c",
                total=49,
                evidence=15,
                gain=15,
                action=20,
                company="C",
            ),
        ]
    )

    assert ids(result.must_read) == ["a"]
    assert ids(result.try_now) == ["b"]
    assert result.watch == []
    assert len({item.event_fingerprint for item in result.flatten()}) == 2


def test_exact_thresholds_admit_candidates_without_padding_lower_scores() -> None:
    must = scored(
        "must",
        total=75,
        evidence=12,
        gain=10,
        company="Must",
    )
    try_now = scored(
        "try",
        total=62,
        evidence=8,
        gain=9,
        action=14,
        resource=True,
        horizon=7,
        company="Try",
    )
    watch = scored(
        "watch",
        total=50,
        evidence=8,
        gain=3,
        action=0,
        company="Watch",
    )
    below = scored(
        "below",
        total=49,
        evidence=15,
        gain=15,
        company="Below",
    )

    result = build_boards([below, watch, try_now, must])

    assert ids(result.must_read) == ["must"]
    assert ids(result.try_now) == ["try"]
    assert ids(result.watch) == ["watch"]


def test_below_each_main_or_try_condition_falls_through_to_watch() -> None:
    result = build_boards(
        [
            scored(
                "main-total",
                total=74,
                evidence=15,
                gain=15,
                company="One",
            ),
            scored(
                "main-evidence",
                total=80,
                evidence=11,
                gain=15,
                company="Two",
            ),
            scored(
                "main-gain",
                total=80,
                evidence=15,
                gain=9,
                company="Three",
            ),
            scored(
                "try-action",
                total=65,
                evidence=8,
                gain=9,
                action=13,
                resource=True,
                horizon=7,
                company="Four",
            ),
            scored(
                "try-resource",
                total=65,
                evidence=8,
                gain=9,
                action=14,
                resource=False,
                horizon=7,
                company="Five",
            ),
            scored(
                "try-horizon",
                total=65,
                evidence=8,
                gain=9,
                action=14,
                resource=True,
                horizon=8,
                company="Six",
            ),
        ]
    )

    assert result.must_read == []
    assert result.try_now == []
    assert ids(result.watch) == [
        "main-evidence",
        "main-gain",
        "main-total",
    ]


def test_must_is_allocated_before_try_for_candidate_eligible_for_both() -> None:
    result = build_boards(
        [
            scored(
                "both",
                total=80,
                evidence=15,
                gain=15,
                action=20,
                resource=True,
                horizon=1,
            )
        ]
    )

    assert ids(result.must_read) == ["both"]
    assert result.try_now == []
    assert result.watch == []


def test_watch_only_secondary_cannot_leak_into_main_or_try() -> None:
    result = build_boards(
        [
            scored(
                "secondary",
                total=90,
                evidence=15,
                gain=15,
                action=20,
                resource=True,
                horizon=1,
                eligible_main_try=False,
                eligible_watch=True,
            )
        ]
    )

    assert result.must_read == []
    assert result.try_now == []
    assert ids(result.watch) == ["secondary"]


def test_ineligible_candidate_is_excluded_from_every_board() -> None:
    result = build_boards(
        [
            scored(
                "rejected",
                total=100,
                eligible_main_try=False,
                eligible_watch=False,
            )
        ]
    )

    assert result.flatten() == []


def test_board_caps_are_exact_and_remaining_items_can_fall_through() -> None:
    must_candidates = [
        scored(f"must-{index}", total=90 - index, company=f"M{index}")
        for index in range(6)
    ]
    must_result = build_boards(must_candidates)
    assert ids(must_result.must_read) == [
        "must-0",
        "must-1",
        "must-2",
        "must-3",
        "must-4",
    ]
    assert ids(must_result.watch) == ["must-5"]

    try_candidates = [
        scored(
            f"try-{index}",
            total=70 - index,
            evidence=8,
            gain=9,
            action=14,
            resource=True,
            horizon=7,
            company=f"T{index}",
        )
        for index in range(4)
    ]
    try_result = build_boards(try_candidates)
    assert ids(try_result.try_now) == ["try-0", "try-1", "try-2"]
    assert ids(try_result.watch) == ["try-3"]

    watch_candidates = [
        scored(
            f"watch-{index}",
            total=60 - index,
            evidence=8,
            gain=3,
            action=0,
            company=f"W{index}",
        )
        for index in range(4)
    ]
    watch_result = build_boards(watch_candidates)
    assert ids(watch_result.watch) == ["watch-0", "watch-1", "watch-2"]


def test_sort_order_uses_all_bound_tiebreakers_and_is_input_independent() -> None:
    candidates = [
        scored(
            "zeta",
            total=80,
            evidence=14,
            gain=14,
            company="Zeta",
            published_at=NOW - timedelta(hours=1),
            fingerprint="zeta",
        ),
        scored(
            "alpha",
            total=80,
            evidence=14,
            gain=14,
            company="Alpha",
            published_at=NOW - timedelta(hours=1),
            fingerprint="alpha",
        ),
        scored(
            "newer",
            total=80,
            evidence=14,
            gain=14,
            company="Newer",
            published_at=NOW,
        ),
        scored(
            "evidence",
            total=80,
            evidence=15,
            gain=14,
            company="Evidence",
        ),
        scored(
            "gain",
            total=80,
            evidence=12,
            gain=15,
            company="Gain",
        ),
        scored(
            "total",
            total=81,
            evidence=12,
            gain=10,
            company="Total",
        ),
    ]

    forward = build_boards(candidates)
    reverse = build_boards(list(reversed(candidates)))

    expected_main = ["total", "gain", "evidence", "newer", "alpha"]
    assert ids(forward.must_read) == expected_main
    assert ids(reverse.must_read) == expected_main
    assert ids(forward.watch) == ["zeta"]
    assert ids(reverse.watch) == ["zeta"]


def test_duplicate_fingerprint_is_selected_only_once() -> None:
    result = build_boards(
        [
            scored(
                "lower",
                total=75,
                company="Lower",
                fingerprint="same-event",
            ),
            scored(
                "higher",
                total=90,
                company="Higher",
                fingerprint="same-event",
            ),
        ]
    )

    assert ids(result.flatten()) == ["higher"]


def test_third_item_from_same_company_cannot_enter_main_or_try() -> None:
    result = build_boards(
        [
            scored("a", total=90, company="Acme"),
            scored("b", total=85, company="acme"),
            scored(
                "c",
                total=65,
                evidence=12,
                gain=9,
                action=14,
                company="ACME",
                resource=True,
                horizon=7,
            ),
        ]
    )

    assert ids(result.must_read + result.try_now) == ["a", "b"]
    assert ids(result.watch) == ["c"]


def test_company_cap_skip_does_not_block_other_companies() -> None:
    result = build_boards(
        [
            scored("a", total=90, company="Acme"),
            scored("b", total=89, company="Acme"),
            scored("c", total=88, company="Acme"),
            scored("d", total=87, company="Beta"),
        ]
    )

    assert ids(result.must_read) == ["a", "b", "d"]
    assert ids(result.watch) == ["c"]


def test_material_update_link_is_copied_to_selected_editorial_item() -> None:
    result = build_boards(
        [
            scored(
                "update",
                assessment=DuplicateAssessment(
                    status="material_update",
                    update_of="old-event-fingerprint",
                ),
            )
        ]
    )

    assert result.must_read[0].update_of == "old-event-fingerprint"
    assert result.must_read[0].board == "must_read"
