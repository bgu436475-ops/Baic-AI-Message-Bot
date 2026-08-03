import json
from datetime import UTC, datetime

import pytest
import requests

from ai_news_bot.feishu import (
    EVIDENCE_URL_LIMIT_BYTES,
    FEISHU_BODY_LIMIT_BYTES,
    FeishuDeliveryRejected,
    FeishuDeliveryUncertain,
    build_card,
    digest_markdown,
    make_signature,
    send_to_feishu,
)
from ai_news_bot.models import (
    DailyDigest,
    DigestBoards,
    EditorialDigest,
    EditorialNewsItem,
    GlobalEventItem,
    GlobalEventScore,
    GlobalPipelineStats,
    NewsItem,
    PipelineStats,
    ScoreBreakdown,
)


def sample_digest() -> DailyDigest:
    return DailyDigest(
        generated_at=datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
        candidate_count=42,
        source_count=12,
        items=[
            NewsItem(
                original_title="Model X",
                title_zh="Model X 发布",
                summary_zh="这是摘要。",
                url="https://example.com/model-x",
                source="Example",
                published_at=datetime(2026, 7, 13, tzinfo=UTC),
                category="new_models",
                importance=95,
            )
        ],
    )


def editorial_item(
    candidate_id: str,
    board: str,
    *,
    verification_status: str = "verified",
) -> EditorialNewsItem:
    return EditorialNewsItem(
        candidate_id=candidate_id,
        board=board,
        original_title=f"{candidate_id} original title",
        title_zh=f"{candidate_id} 中文标题",
        summary_zh=f"{candidate_id} 的事实摘要。",
        concrete_change=f"{candidate_id} 的 API 价格从每百万 token 2 美元降至 1 美元。",
        affected_audience=["API 开发者"],
        affected_area=["推理成本"],
        recommended_action=["按当前调用量重新计算本月成本"],
        evidence_url=f"https://example.com/{candidate_id}",
        verification_status=verification_status,
        event_fingerprint=f"example|{candidate_id}|price|v2|2026-07-23",
        primary_entity="Example",
        event_entities=["Example", candidate_id],
        change_signature="price",
        version_or_metric="2-to-1-usd",
        source="Example",
        published_at=datetime(2026, 7, 23, tzinfo=UTC),
        category="ai_coding",
        score=ScoreBreakdown(
            relevance=25,
            actionability=20,
            specificity=15,
            information_gain=12,
            evidence_quality=12,
            time_sensitivity=8,
        ),
    )


def global_stats() -> GlobalPipelineStats:
    return GlobalPipelineStats(
        candidate_count=0,
        shortlist_count=0,
        source_verified_count=0,
        rejected_count=0,
    )


def global_event(
    candidate_id: str = "global-model-x",
    *,
    category: str = "models_products",
) -> GlobalEventItem:
    return GlobalEventItem(
        event_id=f"acme|{candidate_id}|release|v2|",
        candidate_id=candidate_id,
        category=category,
        title_zh="Acme 正式发布 Model X",
        what_happened_zh="Acme 发布 Model X，API 输入价格降至每百万 token 1 美元。",
        why_it_matters_zh="企业可据此重新核算模型调用成本，并评估迁移收益。",
        affected_groups_zh=["企业决策者", "产品负责人"],
        key_facts=["API 已正式开放", "输入价格为每百万 token 1 美元"],
        source_name="Acme",
        source_url="https://example.com/model-x",
        published_at=datetime(2026, 7, 23, tzinfo=UTC),
        primary_entity="Acme",
        product_or_policy="Model X",
        change_signature="release",
        version_or_metric="v2-$1",
        event_entities=["Acme", "Model X"],
        score=GlobalEventScore(
            impact=30,
            global_relevance=20,
            recency=20,
            evidence_quality=15,
            information_gain=10,
            clarity=5,
        ),
    )


def schema_v4_digest() -> EditorialDigest:
    item = editorial_item("coding-agent", "must_read")
    event = global_event()
    return EditorialDigest(
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=12,
        source_count=6,
        daily_narrative_zh=(
            "今天的全球 AI 重点是 Acme 发布 Model X，"
            "企业决策者需要重新核算模型调用成本。"
        ),
        global_events=[event],
        global_pipeline_stats=GlobalPipelineStats(
            candidate_count=8,
            shortlist_count=4,
            source_verified_count=4,
            rejected_count=3,
        ),
        boards=DigestBoards(must_read=[item]),
        items=[item],
        pipeline_stats=PipelineStats(
            candidate_count=12,
            shortlist_count=8,
            source_verified_count=5,
            rejected_count=7,
        ),
    )


def three_board_digest() -> EditorialDigest:
    must_read = editorial_item("model-api", "must_read")
    try_now = editorial_item("coding-agent", "try_now")
    watch = editorial_item(
        "research-preview",
        "watch",
        verification_status="blocked",
    )
    return EditorialDigest(
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=12,
        source_count=6,
        daily_narrative_zh="今天有三条技术情报通过核验。",
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(
            must_read=[must_read],
            try_now=[try_now],
            watch=[watch],
        ),
        items=[must_read, try_now, watch],
        pipeline_stats=PipelineStats(
            candidate_count=12,
            shortlist_count=8,
            source_verified_count=5,
            rejected_count=5,
        ),
    )


def legal_empty_digest() -> EditorialDigest:
    return EditorialDigest(
        run_status="no_qualifying_items",
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=12,
        source_count=3,
        daily_narrative_zh="今天没有技术情报通过核验。",
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=12,
            shortlist_count=6,
            source_verified_count=3,
            rejected_count=6,
            top_rejection_reasons={
                "missing_concrete_change": 3,
                "missing_action": 2,
            },
        ),
    )


def test_build_card_uses_v2_interactive_schema() -> None:
    card = build_card(sample_digest())
    assert card["msg_type"] == "interactive"
    assert card["card"]["schema"] == "2.0"
    assert "https://example.com/model-x" in digest_markdown(sample_digest())
    content = card["card"]["body"]["elements"][0]["content"]
    assert "\n" in content
    assert not content.startswith("# AI 每日新闻")


def test_schema_v2_markdown_remains_exactly_compatible() -> None:
    assert digest_markdown(sample_digest(), include_title=False) == (
        "**1. 🧠 [Model X 发布](https://example.com/model-x)**  `新模型`\n"
        "这是摘要。\n"
        "*来源：Example · 重要性 95*\n\n"
        "共从 12 个有效来源的 42 条候选中筛选。"
    )


def test_signature_is_stable() -> None:
    assert make_signature(1_700_000_000, "secret") == make_signature(1_700_000_000, "secret")


def test_published_card_has_three_board_sections_and_action_evidence() -> None:
    content = build_card(three_board_digest())["card"]["body"]["elements"][0][
        "content"
    ]

    assert "今日必看" in content
    assert "值得试用" in content
    assert "观察项" in content
    assert "具体变化" in content
    assert "影响" in content
    assert "建议行动" in content
    assert "核查原文" in content
    assert "⚠ 原始来源暂不可核查" in content
    assert "这对行业具有重要意义" not in content


def test_feishu_places_narrative_and_global_events_before_technical() -> None:
    markdown = digest_markdown(schema_v4_digest())

    assert markdown.index("一分钟读懂今天") < markdown.index("全球 AI 重大事件")
    assert markdown.index("全球 AI 重大事件") < markdown.index("技术与工具")


def test_reader_title_is_plain_text_and_source_link_is_explicit() -> None:
    markdown = digest_markdown(schema_v4_digest())

    assert "[Acme 正式发布 Model X](" not in markdown
    assert "[查看原文](https://example.com/model-x)" in markdown


def test_feishu_shows_at_most_five_technical_items() -> None:
    markdown = digest_markdown(maximum_legal_digest())

    assert markdown.count("核查原文") == 5


def test_schema_v4_card_stays_below_feishu_limit() -> None:
    digest = maximum_legal_digest().model_copy(
        update={
            "daily_narrative_zh": "今天有五条全球重大事件和多条技术情报通过核验。",
            "global_events": [
                global_event(
                    f"event-{index}",
                    category=(
                        "models_products"
                        if index < 2
                        else "companies_business"
                        if index < 4
                        else "policy_regulation"
                    ),
                ).model_copy(
                    update={
                        "event_id": f"event-{index}",
                        "candidate_id": f"event-{index}",
                    }
                )
                for index in range(5)
            ],
        }
    )

    body = json.dumps(
        build_card(digest),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    assert len(body) < FEISHU_BODY_LIMIT_BYTES


def test_only_non_empty_editorial_boards_are_rendered() -> None:
    must_read = editorial_item("model-api", "must_read")
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=1,
        source_count=1,
        daily_narrative_zh="今天有一条技术情报通过核验。",
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(must_read=[must_read]),
        items=[must_read],
        pipeline_stats=PipelineStats(
            candidate_count=1,
            shortlist_count=1,
            source_verified_count=1,
            rejected_count=0,
        ),
    )

    content = build_card(digest)["card"]["body"]["elements"][0]["content"]

    assert "今日必看" in content
    assert "值得试用" not in content
    assert "观察项" not in content


def test_legal_empty_card_is_sent_as_normal_success_content() -> None:
    card = build_card(legal_empty_digest())
    content = card["card"]["body"]["elements"][0]["content"]

    assert "今日无内容通过硬门槛" in content
    assert "候选 12 条" in content
    assert "粗筛 6 条" in content
    assert "已核查来源 3 条" in content
    assert "缺少具体变化：3" in content
    assert "缺少可执行行动：2" in content
    assert (
        card["card"]["header"]["subtitle"]["content"]
        == "严格筛选完成 · AI 增长内部群"
    )


def maximum_legal_digest() -> EditorialDigest:
    board_specs = (
        ("must_read", 5),
        ("try_now", 3),
        ("watch", 3),
    )
    boards: dict[str, list[EditorialNewsItem]] = {
        "must_read": [],
        "try_now": [],
        "watch": [],
    }
    all_items: list[EditorialNewsItem] = []
    item_number = 0
    for board, count in board_specs:
        for _ in range(count):
            item_number += 1
            candidate_id = f"完整条目-{item_number:02d}"
            item = editorial_item(candidate_id, board).model_copy(
                update={
                    "title_zh": candidate_id + "·" + "标题字段" * 30,
                    "concrete_change": (
                        f"{candidate_id} API 从 2 美元降至 1 美元；"
                        + "具体参数变化" * 160
                    ),
                    "affected_audience": [
                        f"{candidate_id} API 开发者" + "受影响对象" * 20
                    ],
                    "affected_area": [
                        f"{candidate_id} 推理成本" + "受影响内容" * 20
                    ],
                    "recommended_action": [
                        f"{candidate_id} 本周重新计算成本" + "执行步骤" * 50
                    ],
                    "evidence_url": evidence_url_with_size(
                        item_number,
                        EVIDENCE_URL_LIMIT_BYTES,
                    ),
                }
            )
            boards[board].append(item)
            all_items.append(item)
    return EditorialDigest(
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=80,
        source_count=20,
        daily_narrative_zh="今天有十一条技术情报通过核验。",
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(**boards),
        items=all_items,
        pipeline_stats=PipelineStats(
            candidate_count=80,
            shortlist_count=20,
            source_verified_count=20,
            rejected_count=9,
        ),
    )


def evidence_url_with_size(item_number: int, size: int) -> str:
    prefix = f"https://example.com/evidence/{item_number}?source="
    remaining = size - len(prefix.encode("utf-8"))
    assert remaining >= 0
    return prefix + "a" * remaining


def test_maximum_editorial_card_keeps_five_items_and_required_blocks_complete() -> None:
    content = build_card(maximum_legal_digest())["card"]["body"]["elements"][0][
        "content"
    ]

    assert len(content.encode("utf-8")) <= 18_000
    assert content.count("### 今日必看") == 1
    assert "### 值得试用" not in content
    assert "### 观察项" not in content
    assert content.count("`总分 ") == 5
    assert content.count("具体变化：") == 5
    assert content.count("影响：") == 5
    assert content.count(" · ") == 5
    assert content.count("建议行动：") == 5
    assert content.count("[核查原文](") == 5
    for item_number in range(1, 6):
        evidence_url = evidence_url_with_size(
            item_number,
            EVIDENCE_URL_LIMIT_BYTES,
        )
        assert len(evidence_url.encode("utf-8")) == EVIDENCE_URL_LIMIT_BYTES
        assert f"完整条目-{item_number:02d}" in content
        board_index = (
            item_number
            if item_number <= 5
            else item_number - 5
            if item_number <= 8
            else item_number - 8
        )
        assert f"**{board_index}. 完整条目-{item_number:02d}" in content
        assert content.count(f"]({evidence_url})") == 1
    for item_number in range(6, 12):
        assert f"完整条目-{item_number:02d}" not in content
    assert not content.endswith("…")


@pytest.mark.parametrize(
    ("board", "verification_status", "has_warning"),
    [
        ("watch", "blocked", True),
        ("watch", "unavailable", True),
        ("watch", "verified", False),
        ("must_read", "blocked", False),
    ],
)
def test_original_source_warning_is_watch_only(
    board: str,
    verification_status: str,
    has_warning: bool,
) -> None:
    item = editorial_item(
        f"{board}-{verification_status}",
        board,
        verification_status=verification_status,
    )
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=1,
        source_count=1,
        daily_narrative_zh="今天有一条技术情报通过核验。",
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(**{board: [item]}),
        items=[item],
        pipeline_stats=PipelineStats(
            candidate_count=1,
            shortlist_count=1,
            source_verified_count=1,
            rejected_count=0,
        ),
    )

    content = digest_markdown(digest, include_title=False)

    assert ("⚠ 原始来源暂不可核查" in content) is has_warning


def test_empty_rejection_reasons_use_stable_tie_order() -> None:
    digest = legal_empty_digest().model_copy(
        update={
            "pipeline_stats": PipelineStats(
                candidate_count=12,
                shortlist_count=6,
                source_verified_count=3,
                rejected_count=6,
                top_rejection_reasons={
                    "missing_action": 2,
                    "invalid_evidence_anchor": 2,
                },
            )
        }
    )

    content = digest_markdown(digest, include_title=False)

    assert content.index("证据无法核查：2") < content.index("缺少可执行行动：2")


def test_nonzero_empty_result_without_reason_counts_is_not_contradictory() -> None:
    digest = legal_empty_digest().model_copy(
        update={
            "pipeline_stats": PipelineStats(
                candidate_count=12,
                shortlist_count=6,
                source_verified_count=3,
                rejected_count=6,
                top_rejection_reasons={},
            )
        }
    )

    content = digest_markdown(digest, include_title=False)

    assert "未记录可归类淘汰原因" in content
    assert "未产生可筛选候选" not in content


def test_overlong_evidence_url_fails_closed_instead_of_rendering_broken_link() -> None:
    item = editorial_item("long-url", "must_read").model_copy(
        update={
            "evidence_url": evidence_url_with_size(
                1,
                EVIDENCE_URL_LIMIT_BYTES + 1,
            )
        }
    )
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        candidate_count=1,
        source_count=1,
        daily_narrative_zh="今天有一条技术情报通过核验。",
        global_pipeline_stats=global_stats(),
        boards=DigestBoards(must_read=[item]),
        items=[item],
        pipeline_stats=PipelineStats(
            candidate_count=1,
            shortlist_count=1,
            source_verified_count=1,
            rejected_count=0,
        ),
    )

    with pytest.raises(ValueError, match="证据链接过长"):
        build_card(digest)


def test_send_serializes_compact_utf8_body_below_feishu_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, int]:
            return {"code": 0}

    def fake_post(url: str, **kwargs: object) -> Response:
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("ai_news_bot.feishu.requests.post", fake_post)

    send_to_feishu(
        maximum_legal_digest(),
        "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        signing_secret="secret",
    )

    body = captured["data"]
    assert isinstance(body, bytes)
    assert len(body) < 20_000
    assert captured["headers"] == {
        "Content-Type": "application/json; charset=utf-8"
    }
    assert "json" not in captured
    assert json.loads(body)["msg_type"] == "interactive"


@pytest.mark.parametrize(
    "webhook_url",
    [
        "",
        "http://open.feishu.cn/open-apis/bot/v2/hook/test",
        "https://evil.example/open-apis/bot/v2/hook/test",
        "https://open.feishu.cn.evil.example/open-apis/bot/v2/hook/test",
    ],
)
def test_webhook_validation_rejects_non_official_urls_before_http(
    webhook_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_post(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("ai_news_bot.feishu.requests.post", fake_post)

    with pytest.raises(ValueError):
        send_to_feishu(sample_digest(), webhook_url)

    assert not called


def test_timeout_is_uncertain_without_exposing_request_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/secret-webhook"
    secret = "secret-signing-key"
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.Timeout("underlying network secret")
        ),
    )

    with pytest.raises(FeishuDeliveryUncertain, match="indeterminate") as error:
        send_to_feishu(legal_empty_digest(), webhook, secret)

    message = str(error.value)
    assert "underlying network secret" not in message
    assert webhook not in message
    assert secret not in message


def test_connection_loss_is_uncertain_without_exposing_request_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.ConnectionError("connection detail")
        ),
    )

    with pytest.raises(FeishuDeliveryUncertain, match="indeterminate") as error:
        send_to_feishu(
            legal_empty_digest(),
            "https://open.feishu.cn/open-apis/bot/v2/hook/secret-webhook",
            "secret-signing-key",
        )

    assert "connection detail" not in str(error.value)


def test_nonzero_feishu_code_is_definite_rejection_without_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"code": 19001, "msg": "response secret"}

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: Response())

    with pytest.raises(FeishuDeliveryRejected) as error:
        send_to_feishu(
            legal_empty_digest(),
            "https://open.feishu.cn/open-apis/bot/v2/hook/secret-webhook",
            "secret-signing-key",
        )

    message = str(error.value)
    assert "response secret" not in message
    assert "19001" not in message
    assert "secret-webhook" not in message
    assert "secret-signing-key" not in message


def test_invalid_success_response_json_is_uncertain_without_parser_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            raise ValueError("malformed response secret")

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: Response())

    with pytest.raises(FeishuDeliveryUncertain, match="indeterminate") as error:
        send_to_feishu(
            legal_empty_digest(),
            "https://open.feishu.cn/open-apis/bot/v2/hook/secret-webhook",
            "secret-signing-key",
        )

    assert "malformed response secret" not in str(error.value)
