# Global AI Major Events Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reader-first “全球 AI 重大事件” lane to the daily digest while preserving the existing evidence-heavy technical boards, then publish both lanes through schema v4, Feishu, and the website.

**Architecture:** Collection remains shared, but source configuration marks whether a candidate can enter the global lane, technical lane, or both. The technical pipeline continues to enforce its current action/evidence gates; a new global pipeline performs independent extraction, corroboration, gating, scoring, and seven-day event deduplication. A composition layer removes cross-lane repetition, creates a deterministic Chinese daily narrative, and emits one schema-v4 digest consumed by Feishu and the website.

**Tech Stack:** Python 3.11+, Pydantic 2, OpenAI structured output, requests/feedparser/BeautifulSoup, pytest 8, TypeScript 5.9, React 19, Next 16/vinext, Node 22.

## Global Constraints

- Global events are capped at 5 per day and are never padded with low-scoring content.
- Global categories are exactly `models_products`, `companies_business`, `policy_regulation`, `research_breakthroughs`, and `adoption_society`.
- No global category may contribute more than 2 events.
- Global events must have happened, normally be no older than 48 hours, and may use a clearly dated fallback no older than 7 days.
- A global event needs one verified primary source or two independent verified secondary sources.
- Global events do not require an action recommendation, code, API, or technical parameter.
- The existing technical hard gates and 5/3/3 board limits remain unchanged.
- New formal output is `schema_version: 4`; schema v3 remains read-only compatible on the website.
- Every published item must have nonblank Chinese title and Chinese explanation fields.
- A repository-style `owner/repository` string is not a valid reader-facing Chinese title.
- Feishu renders the daily narrative and global events before technical items, and only explicit “查看原文” text carries the source link.
- The Feishu request body must remain below 20 KB; global event title, occurrence text, and source link have priority over technical detail.
- A failure in either editorial lane fails the run before delivery; a successful zero-selection result in both lanes sends a normal empty card.
- Branch validation must never read the production Feishu webhook or send a group message.

---

## File Responsibility Map

- `src/ai_news_bot/models.py`: schema-v4 public contracts and shared lane types.
- `src/ai_news_bot/global_shortlist.py`: deterministic global-lane coarse filtering.
- `src/ai_news_bot/global_editor.py`: structured extraction and one controlled retry for Chinese global-event records.
- `src/ai_news_bot/global_rules.py`: global hard gates, corroboration, score, category cap, and selection.
- `src/ai_news_bot/global_pipeline.py`: global fetch/extract/audit orchestration.
- `src/ai_news_bot/briefing.py`: cross-lane deduplication, narrative generation, and final digest composition.
- `src/ai_news_bot/pipeline.py`: technical pipeline returns a technical slice instead of a public final digest.
- `src/ai_news_bot/cli.py`: runs both lanes, writes one final digest, and persists both lanes after a successful send.
- `src/ai_news_bot/event_history.py`: seven-day fingerprints shared by global and technical events.
- `src/ai_news_bot/feishu.py`: reader-first schema-v4 card.
- `web/app/news-data.ts`: strict v4 validation and v3/v2 read compatibility.
- `web/app/news-dashboard.tsx`: global section before technical boards.
- `web/app/summary.ts`: summaries prioritize global events.
- `.github/workflows/daily-ai-news.yml`: safe branch-only preview path and production-send guard.

---

### Task 1: Introduce schema-v4 domain contracts

**Files:**
- Modify: `src/ai_news_bot/models.py:109-359`
- Modify: `tests/test_editorial_models.py`
- Create: `web/tests/fixtures/python-global-v4.json`
- Modify: `tests/test_cross_language_web_contract.py`

**Interfaces:**
- Produces: `EditorialLane`, `GlobalEventCategory`, `GlobalEventEvidence`, `GlobalEventGateDecision`, `GlobalEventScore`, `GlobalEventItem`, `TechnicalDigestSlice`, `GlobalPipelineStats`, and schema-v4 `EditorialDigest`.
- `EditorialDigest.items` remains the flattened technical boards for compatibility.
- `EditorialDigest.global_events` remains separate from `items`.

- [ ] **Step 1: Write failing model tests for a published global-only digest**

Add constructors and assertions to `tests/test_editorial_models.py`:

```python
def global_event() -> GlobalEventItem:
    return GlobalEventItem(
        event_id="acme|model-x|release|2026-07-29",
        candidate_id="global-model-x",
        category="models_products",
        title_zh="Acme 正式发布 Model X",
        what_happened_zh="Acme 于 7 月 29 日正式发布 Model X，并向公众开放使用。",
        why_it_matters_zh="该产品改变了普通用户可直接使用的模型能力范围。",
        affected_groups_zh=["普通用户", "企业采购者"],
        key_facts=["2026-07-29 正式发布"],
        source_name="Acme Newsroom",
        source_url="https://example.com/model-x",
        supporting_urls=[],
        published_at=datetime(2026, 7, 29, tzinfo=UTC),
        primary_entity="Acme",
        product_or_policy="Model X",
        change_signature="public-release",
        version_or_metric="Model X",
        effective_date="2026-07-29",
        event_entities=["Acme", "Model X"],
        score=GlobalEventScore(
            impact=24,
            global_relevance=16,
            recency=20,
            evidence_quality=15,
            information_gain=10,
            clarity=5,
        ),
    )


def test_schema_v4_accepts_global_only_published_digest() -> None:
    event = global_event()
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 29, 1, 5, tzinfo=UTC),
        candidate_count=20,
        source_count=8,
        daily_narrative_zh="今天的重点是 Acme 正式发布 Model X。",
        global_events=[event],
        global_pipeline_stats=GlobalPipelineStats(
            candidate_count=20,
            shortlist_count=8,
            source_verified_count=8,
            rejected_count=7,
        ),
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=20,
            shortlist_count=4,
            source_verified_count=4,
            rejected_count=4,
        ),
    )
    assert digest.schema_version == 4
    assert digest.run_status == "published"
    assert digest.items == []
    assert digest.global_events == [event]
```

Also add failures for blank Chinese fields, more than five global events, more than two events in one category, an identical global `event_id` and technical `event_fingerprint`, and `no_qualifying_items` containing either lane. The same source candidate may remain in both lanes only when composition gives the two angles different event fingerprints.

- [ ] **Step 2: Run the model tests and confirm RED**

Run:

```bash
python -m pytest tests/test_editorial_models.py -q
```

Expected: collection fails because the global-event classes and schema-v4 fields do not exist.

- [ ] **Step 3: Add the exact schema-v4 models**

Add these types to `src/ai_news_bot/models.py`:

```python
EditorialLane = Literal["global", "technical"]
GlobalEventCategory = Literal[
    "models_products",
    "companies_business",
    "policy_regulation",
    "research_breakthroughs",
    "adoption_society",
]
GlobalImpactScope = Literal["global", "multi_market", "single_market", "niche"]


class GlobalEventScore(BaseModel):
    impact: int = Field(ge=0, le=30)
    global_relevance: int = Field(ge=0, le=20)
    recency: int = Field(ge=0, le=20)
    evidence_quality: int = Field(ge=0, le=15)
    information_gain: int = Field(ge=0, le=10)
    clarity: int = Field(ge=0, le=5)

    @computed_field
    @property
    def total(self) -> int:
        return (
            self.impact
            + self.global_relevance
            + self.recency
            + self.evidence_quality
            + self.information_gain
            + self.clarity
        )


class GlobalEventEvidence(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=160)
    occurred: bool
    material_change: bool
    category: GlobalEventCategory
    title_zh: str = Field(min_length=1, max_length=80)
    what_happened_zh: str = Field(min_length=1, max_length=360)
    why_it_matters_zh: str = Field(min_length=1, max_length=320)
    affected_groups_zh: list[str] = Field(min_length=1, max_length=5)
    key_facts: list[str] = Field(min_length=1, max_length=5)
    evidence_anchors: list[EvidenceAnchor] = Field(min_length=1, max_length=8)
    source_url: str = Field(max_length=1000)
    source_type: SourceType
    verification_status: VerificationStatus
    primary_entity: str = Field(min_length=1, max_length=160)
    product_or_policy: str = Field(default="", max_length=160)
    change_signature: str = Field(min_length=1, max_length=160)
    version_or_metric: str = Field(default="", max_length=120)
    effective_date: str | None = Field(default=None, max_length=32)
    event_entities: list[str] = Field(default_factory=list, max_length=10)
    impact_scope: GlobalImpactScope
    geographic_scope: list[str] = Field(default_factory=list, max_length=8)
    funding_only: bool = False
    opinion_only: bool = False
    policy_claim: bool = False
    policy_text_available: bool = False
    title_body_conflict: bool = False
    scientific_claim: bool = False
    scientific_verified: bool = False


class GlobalEventGateDecision(BaseModel):
    eligible: bool
    rejection_reasons: list[str] = Field(default_factory=list, max_length=20)


class GlobalEventItem(BaseModel):
    event_id: str = Field(min_length=1, max_length=1000)
    candidate_id: str = Field(min_length=1, max_length=160)
    category: GlobalEventCategory
    title_zh: str = Field(min_length=1, max_length=80)
    what_happened_zh: str = Field(min_length=1, max_length=360)
    why_it_matters_zh: str = Field(min_length=1, max_length=320)
    affected_groups_zh: list[str] = Field(min_length=1, max_length=5)
    key_facts: list[str] = Field(min_length=1, max_length=5)
    source_name: str = Field(min_length=1, max_length=120)
    source_url: str = Field(max_length=1000)
    supporting_urls: list[str] = Field(default_factory=list, max_length=2)
    published_at: datetime
    primary_entity: str = Field(min_length=1, max_length=160)
    product_or_policy: str = Field(default="", max_length=160)
    change_signature: str = Field(min_length=1, max_length=160)
    version_or_metric: str = Field(default="", max_length=120)
    effective_date: str | None = Field(default=None, max_length=32)
    event_entities: list[str] = Field(default_factory=list, max_length=10)
    score: GlobalEventScore


class GlobalPipelineStats(BaseModel):
    candidate_count: int = Field(ge=0)
    shortlist_count: int = Field(ge=0)
    source_verified_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    top_rejection_reasons: dict[str, int] = Field(default_factory=dict)
```

Move the current technical digest fields into:

```python
class TechnicalDigestSlice(BaseModel):
    generated_at: datetime
    candidate_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    lookback_hours: int = Field(ge=0)
    fallback_used: bool = False
    boards: DigestBoards
    items: list[EditorialNewsItem] = Field(max_length=11)
    pipeline_stats: PipelineStats
```

Change `EditorialDigest` to `schema_version: Literal[4] = 4` and add:

```python
daily_narrative_zh: str = Field(min_length=1, max_length=600)
global_events: list[GlobalEventItem] = Field(default_factory=list, max_length=5)
global_pipeline_stats: GlobalPipelineStats
```

Its validator must require:

```python
has_content = bool(self.global_events or flattened)
if self.run_status == "published" and not has_content:
    raise ValueError("published digests require global or technical content")
if self.run_status == "no_qualifying_items" and has_content:
    raise ValueError("empty digests cannot include global or technical content")
if set(event.event_id for event in self.global_events).intersection(
    item.event_fingerprint for item in flattened
):
    raise ValueError("global and technical lanes must not repeat events")
```

Add a shared validator that strips whitespace and requires at least two CJK characters in all published Chinese explanation fields. Add `min_length=1` to `EvidenceRecord.title_zh`, `EvidenceRecord.summary_zh`, `EditorialDraft.title_zh`, and `EditorialDraft.summary_zh` so the existing technical extraction cannot publish blank Chinese fields.

- [ ] **Step 4: Add a Python-generated v4 fixture and cross-language contract test**

Serialize the model fixture to `web/tests/fixtures/python-global-v4.json`, then update `tests/test_cross_language_web_contract.py`:

```python
def test_python_generated_web_fixture_is_valid_schema_v4() -> None:
    digest = EditorialDigest.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert digest.schema_version == 4
    assert digest.global_events[0].category == "models_products"
    assert digest.items == digest.boards.flatten()
```

- [ ] **Step 5: Run the focused model tests and confirm GREEN**

Run:

```bash
python -m pytest tests/test_editorial_models.py tests/test_cross_language_web_contract.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the schema contract**

```bash
git add src/ai_news_bot/models.py tests/test_editorial_models.py \
  tests/test_cross_language_web_contract.py web/tests/fixtures/python-global-v4.json
git commit -m "Add schema v4 global event contracts"
```

---

### Task 2: Mark source lanes and build a global shortlist

**Files:**
- Modify: `src/ai_news_bot/models.py:52-63`
- Modify: `src/ai_news_bot/config.py:12-49`
- Modify: `src/ai_news_bot/collectors.py:93-386`
- Create: `src/ai_news_bot/global_shortlist.py`
- Modify: `config/sources.yaml`
- Modify: `tests/test_config.py`
- Modify: `tests/test_collectors.py`
- Create: `tests/test_global_shortlist.py`

**Interfaces:**
- `Candidate.lane_hints: list[EditorialLane]`.
- All RSS, webpage, and GitHub query configurations expose `lanes`.
- `shortlist_global_candidates(candidates: list[Candidate], now: datetime, limit: int = 20) -> list[Candidate]`.

- [ ] **Step 1: Write failing propagation and shortlist tests**

Add:

```python
def test_rss_collector_propagates_global_lane(monkeypatch) -> None:
    source = RSSSource(
        name="Official News",
        url="https://example.com/feed",
        tier=1,
        weight=1,
        category_hints=["industry_business"],
        lanes=["global", "technical"],
        keyword_filter=False,
    )
    items = RSSCollector().collect([source], 48, now=NOW)
    assert items[0].lane_hints == ["global", "technical"]


def test_global_shortlist_does_not_require_api_or_numeric_tokens() -> None:
    event = candidate(
        title="Commission adopts binding AI transparency rules",
        summary="The rules take effect on 2 August.",
        source_tier=1,
        lanes=["global"],
    )
    assert shortlist_global_candidates([event], NOW) == [event]


def test_global_shortlist_excludes_github_and_items_older_than_seven_days() -> None:
    repository = candidate(source="GitHub · AI 新项目", lanes=["technical"])
    stale = candidate(
        published_at=NOW - timedelta(days=8),
        lanes=["global"],
    )
    assert shortlist_global_candidates([repository, stale], NOW) == []
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
python -m pytest tests/test_config.py tests/test_collectors.py \
  tests/test_global_shortlist.py -q
```

Expected: failures report missing `lanes`, `lane_hints`, and `global_shortlist`.

- [ ] **Step 3: Add lane fields and propagate them**

Use these defaults:

```python
lanes: list[EditorialLane] = Field(
    default_factory=lambda: ["technical"]
)
```

Add the field to `RSSSource`, `WebPageSource`, and `GitHubQuery`. Add:

```python
lane_hints: list[EditorialLane] = Field(
    default_factory=lambda: ["technical"]
)
```

to `Candidate`, and pass `source.lanes` or `query.lanes` in each collector’s `Candidate(...)` construction.

- [ ] **Step 4: Implement deterministic global coarse filtering**

Create `src/ai_news_bot/global_shortlist.py`:

```python
GLOBAL_WINDOW_HOURS = 48
GLOBAL_FALLBACK_HOURS = 168


def shortlist_global_candidates(
    candidates: list[Candidate],
    now: datetime,
    limit: int = 20,
) -> list[Candidate]:
    eligible = [
        item
        for item in candidates
        if "global" in item.lane_hints
        and 0 <= (now - item.published_at).total_seconds()
        <= GLOBAL_FALLBACK_HOURS * 3600
    ]
    return sorted(
        eligible,
        key=lambda item: (
            0 if (now - item.published_at).total_seconds()
            <= GLOBAL_WINDOW_HOURS * 3600 else 1,
            item.source_tier,
            -item.source_weight,
            -item.published_at.timestamp(),
            item.id,
        ),
    )[: max(0, min(limit, 20))]
```

- [ ] **Step 5: Annotate current sources and add three verified official feeds**

In `config/sources.yaml`:

- Mark official model/company feeds and industry media as `[global, technical]`.
- Mark GitHub, ComfyUI, MCP, developer changelogs, and skills queries as `[technical]`.
- Add:

```yaml
  - name: Microsoft Official Blog
    url: https://blogs.microsoft.com/feed/
    tier: 1
    weight: 0.98
    category_hints: [industry_business, new_models]
    lanes: [global, technical]
    keyword_filter: true

  - name: Apple Machine Learning Research
    url: https://machinelearning.apple.com/rss.xml
    tier: 1
    weight: 0.98
    category_hints: [new_models, industry_business]
    lanes: [global, technical]
    keyword_filter: true

  - name: AWS Machine Learning Blog
    url: https://aws.amazon.com/blogs/machine-learning/feed/
    tier: 1
    weight: 0.92
    category_hints: [new_models, agents, industry_business]
    lanes: [global, technical]
    keyword_filter: true
```

Add a configuration test asserting that every source has at least one lane and every GitHub query is technical-only.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run:

```bash
python -m pytest tests/test_config.py tests/test_collectors.py \
  tests/test_global_shortlist.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit lane-aware collection**

```bash
git add src/ai_news_bot/models.py src/ai_news_bot/config.py \
  src/ai_news_bot/collectors.py src/ai_news_bot/global_shortlist.py \
  config/sources.yaml tests/test_config.py tests/test_collectors.py \
  tests/test_global_shortlist.py
git commit -m "Add global event source lane"
```

---

### Task 3: Extract verified Chinese global-event records

**Files:**
- Create: `src/ai_news_bot/global_editor.py`
- Create: `tests/test_global_editor.py`
- Modify: `src/ai_news_bot/evidence.py:18-47`
- Modify: `tests/test_evidence.py`

**Interfaces:**
- `extract_global_event(candidate, source, client, model, base_url=None) -> GlobalEventEvidence`.
- `GlobalEventExtractionError` distinguishes controlled model/validation failure from source failure.
- `validate_global_anchors(record, source) -> GlobalEventEvidence`.

- [ ] **Step 1: Write failing extraction tests**

Use a fake structured client that first returns a blank/English-only record and then a valid record:

```python
def test_global_editor_retries_once_for_missing_chinese() -> None:
    client = FakeStructuredClient([
        invalid_english_only_record(),
        valid_global_record(),
    ])
    result = extract_global_event(
        candidate(),
        fetched(),
        client,
        "test-model",
    )
    assert result.title_zh == "Acme 正式发布 Model X"
    assert client.call_count == 2


def test_global_editor_rejects_repository_style_reader_title() -> None:
    client = FakeStructuredClient([
        valid_global_record().model_copy(update={"title_zh": "owner/repository"}),
        valid_global_record().model_copy(update={"title_zh": "Acme 发布开发工具"}),
    ])
    assert extract_global_event(
        candidate(), fetched(), client, "test-model"
    ).title_zh == "Acme 发布开发工具"


def test_global_anchor_must_be_literal_source_text() -> None:
    record = valid_global_record().model_copy(
        update={"evidence_anchors": [EvidenceAnchor(
            quote="fabricated claim",
            locator="paragraph 1",
        )]}
    )
    assert validate_global_anchors(record, fetched()).verification_status == "insufficient"
```

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```bash
python -m pytest tests/test_global_editor.py -q
```

Expected: import failure for `ai_news_bot.global_editor`.

- [ ] **Step 3: Implement constrained extraction and validation**

Create `GLOBAL_EVENT_SYSTEM_PROMPT` that explicitly states:

```text
Use only the supplied candidate and fetched source.
The event must already have happened.
Return Chinese title, what happened, why it matters, affected groups, and key facts.
Do not return owner/repository as a title.
Do not score or select the event.
Every factual change needs a literal evidence anchor from source_text.
```

Use the same 4,500-token first attempt and 2,200-token retry budget as `evidence.py`. Parse `GlobalEventEvidence` with the existing GitHub Models/OpenAI structured-output split. Retry once for:

- structured parse errors,
- fewer than two CJK characters in any required Chinese field,
- `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$` reader title,
- candidate ID mismatch,
- invalid literal evidence anchors.

After the second failure, raise:

```python
class GlobalEventExtractionError(RuntimeError):
    pass
```

Programmatically overwrite `source_url`, `verification_status`, and `source_type` from `FetchedSource` and candidate tier. The model must never decide that a fetched secondary page is a primary source.

- [ ] **Step 4: Tighten technical Chinese extraction**

Update `EVIDENCE_SYSTEM_PROMPT` to require complete Chinese `title_zh` and `summary_zh`. Add a regression test proving the existing technical extractor retries rather than returning blank Chinese fields.

- [ ] **Step 5: Run editor and evidence tests**

Run:

```bash
python -m pytest tests/test_global_editor.py tests/test_evidence.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit structured global extraction**

```bash
git add src/ai_news_bot/global_editor.py src/ai_news_bot/evidence.py \
  tests/test_global_editor.py tests/test_evidence.py
git commit -m "Extract Chinese global event evidence"
```

---

### Task 4: Apply global gates, corroboration, scoring, and deduplication

**Files:**
- Create: `src/ai_news_bot/global_rules.py`
- Create: `tests/test_global_rules.py`
- Modify: `src/ai_news_bot/event_history.py:15-285`
- Modify: `tests/test_event_history.py`

**Interfaces:**
- `global_event_fingerprint(record: GlobalEventEvidence | GlobalEventItem) -> str`.
- `corroborate_global_records(records: list[GlobalEventEvidence]) -> dict[str, list[GlobalEventEvidence]]`.
- `evaluate_global_event(record, cluster, duplicate, published_at, now) -> GlobalEventGateDecision`.
- `score_global_event(record, cluster, duplicate, published_at, now) -> GlobalEventScore`.
- `select_global_events(prepared: list[ScoredGlobalEvent], limit: int = 5) -> list[GlobalEventItem]`.
- `EventHistoryStore.classify_global(record, now) -> DuplicateAssessment`.

- [ ] **Step 1: Write failing table-driven gate tests**

Cover every hard rule:

```python
@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"occurred": False}, "not_occurred"),
        ({"material_change": False}, "missing_material_change"),
        ({"funding_only": True}, "funding_only"),
        ({"opinion_only": True}, "opinion_without_evidence"),
        (
            {"policy_claim": True, "policy_text_available": False},
            "policy_without_text",
        ),
        ({"title_body_conflict": True}, "title_body_conflict"),
        (
            {"scientific_claim": True, "scientific_verified": False},
            "scientific_claim_unverified",
        ),
    ],
)
def test_global_gate_rejects_invalid_event(changes, reason) -> None:
    record = valid_record().model_copy(update=changes)
    decision = evaluate_global_event(
        record,
        [record],
        DuplicateAssessment(status="unique"),
        NOW,
        NOW,
    )
    assert not decision.eligible
    assert reason in decision.rejection_reasons
```

Add tests proving a verified primary source passes alone, a trusted secondary requires two distinct hostnames, a 49-hour event is allowed but marked fallback, an event older than 168 hours is rejected, and a duplicate without material update is rejected.

- [ ] **Step 2: Write failing scoring and selection tests**

```python
def test_global_score_totals_exactly_one_hundred_at_caps() -> None:
    score = score_global_event(
        valid_record(impact_scope="global", geographic_scope=["global"]),
        [valid_record()],
        DuplicateAssessment(status="unique"),
        NOW,
        NOW,
    )
    assert score.total == 100


def test_selection_enforces_threshold_category_cap_and_daily_limit() -> None:
    selected = select_global_events(prepared_records())
    assert len(selected) <= 5
    assert all(item.score.total >= 65 for item in selected)
    assert Counter(item.category for item in selected).most_common(1)[0][1] <= 2
```

- [ ] **Step 3: Run the global rule tests and confirm RED**

Run:

```bash
python -m pytest tests/test_global_rules.py tests/test_event_history.py -q
```

Expected: missing global rule functions.

- [ ] **Step 4: Implement exact deterministic rules**

Use these score mappings:

```python
class ScoredGlobalEvent(BaseModel):
    record: GlobalEventEvidence
    cluster: list[GlobalEventEvidence] = Field(min_length=1)
    assessment: DuplicateAssessment
    source_name: str = Field(min_length=1, max_length=120)
    published_at: datetime
    score: GlobalEventScore


IMPACT = {"global": 30, "multi_market": 24, "single_market": 16, "niche": 8}
INFORMATION_GAIN = {
    "unique": 10,
    "material_update": 7,
    "minor_update": 0,
    "duplicate": 0,
}


def _recency(age_hours: float) -> int:
    return 20 if age_hours <= 24 else 16 if age_hours <= 48 else 8


def _evidence_quality(
    record: GlobalEventEvidence,
    cluster: list[GlobalEventEvidence],
) -> int:
    if record.source_type != "trusted_secondary" and record.verification_status == "verified":
        return 15
    independent_hosts = {
        urlsplit(item.source_url).hostname
        for item in cluster
        if item.source_type == "trusted_secondary"
        and item.verification_status == "verified"
    }
    return 12 if len(independent_hosts) >= 2 else 0
```

Map `global_relevance` to 20 for global scope, 16 for at least two distinct markets/regions, 8 for one market, and 4 for an empty scope. `clarity` is 5 only when all required Chinese fields, affected groups, and key facts pass deterministic checks.

Sort accepted events by:

```python
(-score.total, -score.recency, -score.evidence_quality, -published_at.timestamp(), event_id)
```

Allocate at most two per category and five overall.

- [ ] **Step 5: Extend seven-day history to global events**

Make the stored snapshot lane-aware:

```python
{
  "lane": "global",
  "fingerprint": "...",
  "recorded_at": "...",
  "primary_entity": "...",
  "product_or_model": "...",
  "change_signature": "...",
  "version_or_metric": "...",
  "effective_date": "...",
  "source_url": "https://..."
}
```

Existing entries without `lane` normalize to `"technical"`. Add `classify_global` and make `record_digest` write both `digest.global_events` and `digest.items`. A new number, formal effective date, formal publication, geographic expansion, or primary confirmation is a material update; an exact fingerprint without one of those changes is a duplicate.

- [ ] **Step 6: Run rule/history tests and confirm GREEN**

Run:

```bash
python -m pytest tests/test_global_rules.py tests/test_event_history.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit global editorial rules**

```bash
git add src/ai_news_bot/global_rules.py src/ai_news_bot/event_history.py \
  tests/test_global_rules.py tests/test_event_history.py
git commit -m "Rank and dedupe global AI events"
```

---

### Task 5: Run both lanes and compose one daily briefing

**Files:**
- Create: `src/ai_news_bot/global_pipeline.py`
- Create: `src/ai_news_bot/briefing.py`
- Create: `tests/test_global_pipeline.py`
- Create: `tests/test_briefing.py`
- Modify: `src/ai_news_bot/pipeline.py:306-650`
- Modify: `src/ai_news_bot/cli.py:139-345`
- Modify: `src/ai_news_bot/history.py:17-65`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_history.py`
- Modify: `src/ai_news_bot/web_export.py`
- Modify: `tests/test_web_export.py`

**Interfaces:**
- `run_editorial_pipeline(...) -> PipelineResult` where `PipelineResult.digest` is `TechnicalDigestSlice`.
- `GlobalPipelineDependencies` mirrors the current dependency-injection style.
- `run_global_pipeline(...) -> GlobalPipelineResult`.
- `compose_daily_briefing(technical, global_result, now) -> EditorialDigest`.

- [ ] **Step 1: Write a failing global pipeline sequence test**

```python
def test_global_pipeline_shortlists_fetches_extracts_groups_and_selects() -> None:
    trace: list[str] = []
    result = run_global_pipeline(
        candidates(),
        dependencies=fake_global_dependencies(trace),
        now=NOW,
    )
    assert trace == [
        "shortlist",
        "fetch",
        "extract",
        "corroborate",
        "dedupe",
        "gate",
        "score",
        "select",
    ]
    assert [item.title_zh for item in result.events] == [
        "Acme 正式发布 Model X"
    ]
    assert result.stats.rejected_count == 1
```

Also test that one extraction failure is audited while another event publishes, and all extraction failures raise `GlobalEventExtractionError`.

- [ ] **Step 2: Write failing composition tests**

```python
def test_composer_places_global_events_before_independent_technical_items() -> None:
    digest = compose_daily_briefing(
        technical_slice(items=[technical_item(resource_available=True)]),
        global_result(events=[global_item(candidate_id="same")]),
        NOW,
    )
    assert digest.global_events[0].candidate_id == "same"
    assert digest.items[0].resource_available
    assert "今天" in digest.daily_narrative_zh


def test_composer_drops_non_actionable_cross_lane_duplicate() -> None:
    digest = compose_daily_briefing(
        technical_slice(items=[technical_item(
            candidate_id="same",
            resource_available=False,
            recommended_action=[],
        )]),
        global_result(events=[global_item(candidate_id="same")]),
        NOW,
    )
    assert digest.items == []
```

Add published-state tests for global-only, technical-only, both, and legal empty.

- [ ] **Step 3: Run the new tests and confirm RED**

Run:

```bash
python -m pytest tests/test_global_pipeline.py tests/test_briefing.py -q
```

Expected: missing modules and interfaces.

- [ ] **Step 4: Refactor the technical pipeline to return a slice**

Replace final `EditorialDigest(...)` construction in `run_editorial_pipeline` with `TechnicalDigestSlice(...)`. Change the existing result contract to:

```python
class PipelineResult(BaseModel):
    digest: TechnicalDigestSlice
    audit: PipelineAudit
```

Keep boards, items, technical stats, lookback, and audit behavior identical. Update pipeline tests to assert technical slice content rather than public run status.

- [ ] **Step 5: Implement the global pipeline**

Follow the existing technical pipeline’s dependency-injection pattern:

```python
@dataclass(frozen=True)
class GlobalPipelineDependencies:
    shortlist: GlobalShortlistCallable
    source_fetcher: SourceFetcherLike
    extract: GlobalExtractCallable
    classify: GlobalClassifyCallable
    corroborate: GlobalCorroborateCallable
    gate: GlobalGateCallable
    score: GlobalScoreCallable
    select: GlobalSelectCallable


class GlobalAuditEntry(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=160)
    source_url: str = Field(max_length=1000)
    fetch_status: VerificationStatus
    corroborating_source_count: int = Field(ge=0, le=20)
    rejection_reasons: list[str] = Field(default_factory=list, max_length=20)
    duplicate_status: DuplicateAuditStatus
    score: GlobalEventScore | None = None
    selected: bool = False


class GlobalPipelineAudit(BaseModel):
    generated_at: datetime
    entries: list[GlobalAuditEntry] = Field(max_length=20)
    rejection_reason_counts: dict[str, int] = Field(default_factory=dict)


class GlobalPipelineResult(BaseModel):
    events: list[GlobalEventItem] = Field(max_length=5)
    stats: GlobalPipelineStats
    audit: GlobalPipelineAudit
    fallback_used: bool = False
```

Audit each shortlisted candidate with source status, cluster size, rejection reasons, duplicate status, score, and whether it was selected. Do not store source page bodies or model prompts in the audit.

- [ ] **Step 6: Implement cross-lane composition and narrative**

In `src/ai_news_bot/briefing.py`, keep a technical duplicate only when all are true:

```python
def _independent_technical_angle(item: EditorialNewsItem) -> bool:
    return (
        item.resource_available
        and bool(item.recommended_action)
        and item.category in {
            "ai_coding",
            "agents",
            "image_video",
            "comfyui",
            "open_source",
            "mcp",
            "skills",
        }
    )
```

Rebuild `DigestBoards` after removals so `items == boards.flatten()`. Generate narrative without a third model call:

```python
def build_daily_narrative_zh(
    events: list[GlobalEventItem],
    technical_items: list[EditorialNewsItem],
) -> str:
    if events:
        titles = "；".join(event.title_zh for event in events[:3])
        group_list = list(dict.fromkeys(
            group
            for event in events[:3]
            for group in event.affected_groups_zh
        ))[:4]
        groups = "、".join(group_list)
        return f"今天的全球 AI 重点包括：{titles}。主要影响{groups}，事实与原始来源见下方。"
    if technical_items:
        return f"今天没有全球重大事件通过核验；技术与工具栏有 {len(technical_items)} 条可行动信息。"
    return "今天没有全球重大事件或技术信息通过核验，以下为空榜说明。"
```

Use a normal list before slicing the deduplicated groups; do not slice a `dict_keys` view.

When constructing the final digest, calculate `latest_published_at` and `fresh_count_24h` across both `global_events` and technical `items`, not from the technical lane alone:

```python
all_published_at = [
    *(event.published_at for event in global_events),
    *(item.published_at for item in technical_items),
]
latest_published_at = max(all_published_at, default=None)
fresh_count_24h = sum(
    0 <= (now - published_at).total_seconds() <= 24 * 3600
    for published_at in all_published_at
)
```

Set:

```python
fallback_used = technical.fallback_used or global_result.fallback_used
lookback_hours = max(
    technical.lookback_hours,
    168 if global_result.fallback_used else 48,
)
```

`run_global_pipeline` sets `fallback_used=True` when any selected event is older than 48 hours and no older than 168 hours.

- [ ] **Step 7: Integrate both lanes in the CLI**

Change `_build_pipeline_dependencies` to create one lazy `OpenAI` client closure shared by technical and global extractors. In `run`:

```python
technical = run_editorial_pipeline(unique, technical_dependencies, generation_now)
global_result = run_global_pipeline(unique, global_dependencies, generation_now)
digest = compose_daily_briefing(
    technical.digest,
    global_result,
    generation_now,
)
```

Write the public digest only after both calls succeed. Write separate technical and global audit sections into `.state/latest_audit.json`.

Update `_send_existing_daily_result` so `HistoryStore.record_digest(digest)` records URLs from both lanes and `EventHistoryStore.record_digest(digest)` records both fingerprints.

Implement the URL-history entry point as:

```python
def record_digest(
    self,
    digest: EditorialDigest,
    now: datetime | None = None,
) -> None:
    recorded_at = _aware(now or datetime.now(UTC))
    urls = [
        *(event.source_url for event in digest.global_events),
        *(item.evidence_url for item in digest.items),
    ]
    self._record_urls(urls, recorded_at)
```

Move the existing retention/write logic into `_record_urls(urls: list[str], now: datetime)`. Keep `record(items, now)` as a compatibility wrapper for current tests and callers.

- [ ] **Step 8: Run pipeline, CLI, history, and export tests**

Run:

```bash
python -m pytest tests/test_pipeline.py tests/test_global_pipeline.py \
  tests/test_briefing.py tests/test_cli.py tests/test_history.py \
  tests/test_web_export.py -q
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit dual-lane orchestration**

```bash
git add src/ai_news_bot/global_pipeline.py src/ai_news_bot/briefing.py \
  src/ai_news_bot/pipeline.py src/ai_news_bot/cli.py \
  src/ai_news_bot/history.py src/ai_news_bot/web_export.py \
  tests/test_global_pipeline.py tests/test_briefing.py \
  tests/test_pipeline.py tests/test_cli.py tests/test_history.py \
  tests/test_web_export.py
git commit -m "Compose global and technical news lanes"
```

---

### Task 6: Render a reader-first Feishu card

**Files:**
- Modify: `src/ai_news_bot/feishu.py:22-363`
- Modify: `tests/test_feishu.py`

**Interfaces:**
- `_render_global_event(digest: EditorialDigest, item: GlobalEventItem, index: int) -> list[str]`.
- `_technical_items_for_feishu(digest) -> list[EditorialNewsItem]` returns at most 5 items while preserving board order.
- `build_card(EditorialDigest)` emits one request under 20 KB.

- [ ] **Step 1: Write failing layout tests**

```python
def test_feishu_places_narrative_and_global_events_before_technical() -> None:
    markdown = digest_markdown(schema_v4_digest())
    assert markdown.index("一分钟读懂今天") < markdown.index("全球 AI 重大事件")
    assert markdown.index("全球 AI 重大事件") < markdown.index("技术与工具")


def test_reader_title_is_plain_text_and_source_link_is_explicit() -> None:
    markdown = digest_markdown(schema_v4_digest())
    assert "[Acme 正式发布 Model X](" not in markdown
    assert "[查看原文](https://example.com/model-x)" in markdown


def test_feishu_shows_at_most_five_technical_items() -> None:
    markdown = digest_markdown(maximum_schema_v4_digest())
    assert markdown.count("核查原文") == 5


def test_schema_v4_card_stays_below_feishu_limit() -> None:
    body = json.dumps(
        build_card(maximum_schema_v4_digest()),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(body) < FEISHU_BODY_LIMIT_BYTES
```

- [ ] **Step 2: Run Feishu tests and confirm RED**

Run:

```bash
python -m pytest tests/test_feishu.py -q
```

Expected: schema-v4 headings and explicit source-link behavior are absent.

- [ ] **Step 3: Implement global event rendering**

Use:

```python
GLOBAL_CATEGORY_LABELS = {
    "models_products": "模型与产品",
    "companies_business": "公司与商业",
    "policy_regulation": "政策与监管",
    "research_breakthroughs": "科研突破",
    "adoption_society": "大众应用与社会影响",
}
```

Render:

```python
[
    f"**{index}. 🌍 [{label}] {title}**",
    f"发生了什么：{what_happened}",
    f"为什么重要：{why_it_matters}",
    f"影响：{affected_groups}",
    f"关键事实：{key_facts}",
    f"日期：{event_date}{' · 回看' if fallback else ''}",
    f"来源：{source_name} · [查看原文]({source_url})",
    "",
]
```

Calculate `fallback` from the digest generation time and the event publication time:

```python
fallback = (
    digest.generated_at - item.published_at
).total_seconds() > 48 * 3600
```

Change technical rendering so its title is also plain text and its only link is `[核查原文](...)`.

- [ ] **Step 4: Apply deterministic card budgeting**

Reserve bytes in this order:

1. narrative,
2. each global title,
3. each global occurrence line,
4. each global source link,
5. global importance/impact detail,
6. technical entries.

Never pass a partially truncated URL to `_safe_evidence_url`. Reduce technical count from 5 downward before removing a global event. If five global minimum representations alone exceed the budget, raise `ValueError` and do not send an incomplete card.

Set the subtitle to:

```python
f"全球大事 {len(digest.global_events)} · 技术情报 {len(technical_items)} · AI 增长内部群"
```

- [ ] **Step 5: Run Feishu tests and confirm GREEN**

Run:

```bash
python -m pytest tests/test_feishu.py -q
```

Expected: all selected tests pass and maximum request body is below 20 KB.

- [ ] **Step 6: Commit the Feishu reader layout**

```bash
git add src/ai_news_bot/feishu.py tests/test_feishu.py
git commit -m "Add global events to Feishu digest"
```

---

### Task 7: Add schema-v4 website validation and global-event UI

**Files:**
- Modify: `web/app/news-data.ts:1-640`
- Modify: `web/app/news-dashboard.tsx:14-554`
- Modify: `web/app/summary.ts:1-99`
- Modify: `web/app/globals.css`
- Modify: `web/tests/rendered-html.test.mjs`
- Modify: `web/public/data/latest.json`

**Interfaces:**
- Public `Digest` becomes schema v4.
- Current schema-v3 type becomes `LegacyDigestV3`.
- `normalizeDigest(value)` returns v4 for v4, v3, or v2 input.
- `GlobalEventCard` renders reader-facing global content.

- [ ] **Step 1: Convert the rendered fixture to schema v4 and write failing validator tests**

Add a `GLOBAL_EVENT` fixture with all exact v4 fields and update `PUBLISHED_DIGEST`:

```javascript
const PUBLISHED_DIGEST = {
  schema_version: 4,
  run_status: "published",
  generated_at: "2026-07-29T01:05:00Z",
  candidate_count: 20,
  source_count: 8,
  latest_published_at: "2026-07-29T00:30:00Z",
  fresh_count_24h: 2,
  lookback_hours: 48,
  fallback_used: false,
  daily_narrative_zh: "今天的重点是 Acme 正式发布 Model X。",
  global_events: [GLOBAL_EVENT],
  global_pipeline_stats: {
    candidate_count: 20,
    shortlist_count: 8,
    source_verified_count: 8,
    rejected_count: 7,
    top_rejection_reasons: {},
  },
  boards: { must_read: [MUST_READ_ITEM], try_now: [], watch: [] },
  items: [MUST_READ_ITEM],
  pipeline_stats: {
    candidate_count: 20,
    shortlist_count: 1,
    source_verified_count: 1,
    rejected_count: 0,
    top_rejection_reasons: {},
  },
};
```

Add tests rejecting blank global Chinese fields, invalid category, score mismatch, more than five events, more than two in a category, duplicate event IDs, and overlap with a technical candidate.

- [ ] **Step 2: Run the web tests and confirm RED**

Run:

```bash
cd web
npm test
```

Expected: the v3-only validator rejects the v4 fixture.

- [ ] **Step 3: Implement strict v4 validation and v3 compatibility**

Add TypeScript types matching Python exactly. Add exact-key validation for global events and global scores. Require nonblank Chinese fields and validate the total as:

```typescript
const calculated = value.impact
  + value.global_relevance
  + value.recency
  + value.evidence_quality
  + value.information_gain
  + value.clarity;
return value.total === calculated && value.total <= 100;
```

Rename the current v3 validator to `isLegacyDigestV3`. Normalize v3 to v4 with:

- `global_events: []`,
- a deterministic Chinese migration narrative,
- zeroed `global_pipeline_stats`,
- unchanged technical boards/items.

Continue normalizing v2 through the existing compatibility path, then through the v3-to-v4 path.

- [ ] **Step 4: Render global events above technical filters**

Add `GlobalEventCard` and place this section before the current toolbar:

```tsx
<section className="global-events" aria-labelledby="global-events-title">
  <div className="section-heading">
    <div>
      <span className="eyebrow">GLOBAL AI EVENTS</span>
      <h2 id="global-events-title">{copy.globalEvents}</h2>
    </div>
    <span className="result-count">{currentDigest.global_events.length}</span>
  </div>
  <p className="daily-narrative">{currentDigest.daily_narrative_zh}</p>
  <div className="global-event-grid">
    {currentDigest.global_events.map((event) => (
      <GlobalEventCard event={event} language={language} key={event.event_id} />
    ))}
  </div>
</section>
```

Global cards show category, event date, occurrence text, importance text, affected groups, key facts, source name, and explicit source link. Technical category controls continue to filter only the technical boards.

- [ ] **Step 5: Update daily/weekly summaries**

For daily summaries, select global events first and fill remaining slots from technical items. For weekly summaries, sort global events by global score and technical items by technical score, then merge without duplicate source URLs. Use `what_happened_zh` and `why_it_matters_zh` for the reader-facing summary.

- [ ] **Step 6: Add responsive styles**

Add:

```css
.global-events { padding: 56px var(--page-pad); border-bottom: 1px solid var(--line); }
.daily-narrative { max-width: 880px; font-size: clamp(20px, 2.1vw, 30px); line-height: 1.55; }
.global-event-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.global-event-card { border: 1px solid var(--line); padding: 24px; background: var(--paper); }
@media (max-width: 820px) {
  .global-event-grid { grid-template-columns: 1fr; }
}
```

Extend the existing visual language rather than replacing it.

- [ ] **Step 7: Run full web validation**

Run:

```bash
cd web
npm run lint
npm test
```

Expected: lint passes, build succeeds, and all Node tests pass.

- [ ] **Step 8: Commit website support**

```bash
git add web/app/news-data.ts web/app/news-dashboard.tsx \
  web/app/summary.ts web/app/globals.css \
  web/tests/rendered-html.test.mjs web/public/data/latest.json
git commit -m "Render global AI events on dashboard"
```

---

### Task 8: Add a no-send validation workflow and produce review artifacts

**Files:**
- Create: `scripts/build_global_events_preview.py`
- Create: `tests/fixtures/global_events_validation.json`
- Create: `tests/test_global_events_preview.py`
- Modify: `.github/workflows/daily-ai-news.yml:1-104`
- Modify: `README.md`

**Interfaces:**
- `python scripts/build_global_events_preview.py --output-dir validation-output`.
- Branch workflow emits `validation-output/latest-v4.json` and `validation-output/feishu-card.json`.
- Production send steps execute only on `refs/heads/main`.

- [ ] **Step 1: Write a failing deterministic preview test**

```python
def test_preview_contains_all_global_categories_and_no_linked_title(tmp_path) -> None:
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
```

- [ ] **Step 2: Run the preview test and confirm RED**

Run:

```bash
python -m pytest tests/test_global_events_preview.py -q
```

Expected: preview builder does not exist.

- [ ] **Step 3: Implement the offline preview builder**

The fixture contains exactly one verified event from each global category plus one item in each technical board. The script:

1. validates fixture data through schema-v4 Pydantic models,
2. writes `latest-v4.json`,
3. calls `build_card`,
4. writes the exact Feishu request JSON,
5. raises if the card is at least 20 KB or any required Chinese field is blank.

It does not read environment variables, network sources, `.state`, or Feishu secrets.

- [ ] **Step 4: Guard production sending and add branch validation steps**

Update the workflow conditions:

```yaml
      - name: Generate daily result
        if: >-
          steps.daily_guard.outputs.should_run == 'true' &&
          github.ref == 'refs/heads/main'

      - name: Send persisted daily result
        if: >-
          steps.daily_guard.outputs.should_run == 'true' &&
          github.ref == 'refs/heads/main'
```

Add branch-only steps:

```yaml
      - name: Run Python validation
        if: github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main'
        run: python -m pytest -q

      - name: Build no-send preview
        if: github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main'
        run: python scripts/build_global_events_preview.py --output-dir validation-output

      - name: Set up Node for web validation
        if: github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main'
        uses: actions/setup-node@v6
        with:
          node-version: "22.13.0"
          cache: npm
          cache-dependency-path: web/package-lock.json

      - name: Validate website
        if: github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main'
        working-directory: web
        run: |
          npm ci
          npm run lint
          npm test

      - name: Upload no-send preview
        if: github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main'
        uses: actions/upload-artifact@v6
        with:
          name: global-ai-events-preview
          path: validation-output/
```

No branch-only step receives `FEISHU_WEBHOOK_URL`, `FEISHU_SIGNING_SECRET`, or dashboard write secrets.

- [ ] **Step 5: Document schema v4 and the validation procedure**

Update `README.md` with:

- the two editorial lanes,
- global categories and score threshold,
- one-primary/two-secondary evidence rule,
- schema-v4 status rules,
- exact branch validation command,
- explicit statement that branch validation cannot send Feishu.

- [ ] **Step 6: Run all local verification**

Run:

```bash
python -m pytest -q
python scripts/build_global_events_preview.py --output-dir validation-output
cd web
npm run lint
npm test
```

Expected:

- Python suite: zero failures.
- Preview builder: exits 0 and writes both JSON artifacts.
- ESLint: zero errors.
- Web build and Node tests: zero failures.

- [ ] **Step 7: Confirm no production side effects**

Run:

```bash
git diff target/main -- .github/workflows/daily-ai-news.yml
rg -n "FEISHU_WEBHOOK_URL|FEISHU_SIGNING_SECRET" \
  scripts tests/fixtures validation-output
git status --short
```

Expected:

- workflow diff shows all non-main `workflow_dispatch` paths are no-send,
- no secret names occur in preview code, fixtures, or artifacts,
- only intended files and generated review artifacts are present.

- [ ] **Step 8: Commit validation support**

```bash
git add scripts/build_global_events_preview.py \
  tests/fixtures/global_events_validation.json \
  tests/test_global_events_preview.py \
  .github/workflows/daily-ai-news.yml README.md
git commit -m "Add no-send global digest validation"
```

- [ ] **Step 9: Push and run the branch workflow**

```bash
git push target codex/global-major-events
```

From GitHub Actions, select `codex/global-major-events` and run `Daily AI News`. Verify that the run contains `Run Python validation`, `Build no-send preview`, `Validate website`, and `Upload no-send preview`, while `Generate daily result` and `Send persisted daily result` are skipped.

- [ ] **Step 10: Deliver review evidence**

Report:

- branch workflow URL,
- Python test count,
- web test count,
- preview artifact link,
- final commit SHA and commit message,
- confirmation that no Feishu message was sent,
- remaining decision: approve or reject merging into `main`.

Do not merge until the user explicitly approves the preview.

---

## Final Verification Checklist

- [ ] Schema v4 accepts global-only, technical-only, mixed, and legal-empty digests.
- [ ] Schema v4 rejects missing Chinese content, lane overlap, category overflow, and invalid run status.
- [ ] Global events accept one primary source or two independent secondary hosts.
- [ ] Events older than 48 hours are visibly fallback content and none exceed seven days.
- [ ] Global scores use the specified 30/20/20/15/10/5 weights and require at least 65.
- [ ] Global selection contains no more than five events and no more than two per category.
- [ ] Technical 5/3/3 boards and action/evidence gates remain unchanged.
- [ ] Cross-lane duplicate removal preserves only genuinely actionable technical angles.
- [ ] Feishu shows narrative, global events, then at most five technical items.
- [ ] Reader-facing titles are plain text; source links use explicit link labels.
- [ ] Feishu request body is below 20 KB without broken URLs or partial mandatory fields.
- [ ] Website strictly validates v4 and can read historical v3/v2 data.
- [ ] Branch workflow tests and creates artifacts without any production secret or send step.
- [ ] Full Python tests, web lint, web build, and web tests all pass immediately before completion.
