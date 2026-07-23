# Structured Editorial Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-pass “model selects about 10 stories” flow with a deterministic two-stage editorial pipeline that verifies original evidence, enforces hard gates, deduplicates seven-day events, produces mutually exclusive 5+3+3 boards, and sends a valid empty Feishu card when nothing qualifies.

**Architecture:** Existing collectors still gather up to 80 candidates. New focused modules shortlist 15–20 candidates, fetch original sources, extract constrained evidence with the model, validate anchors, apply program-owned gates, event deduplication, scoring and board assignment, then serialize schema v3 for Feishu and the existing website. Send success is recorded separately from digest generation so a failed Feishu call remains retryable.

**Tech Stack:** Python 3.11+, Pydantic 2, requests, BeautifulSoup 4, OpenAI Python SDK 2, pytest 8, React 19, TypeScript 5.9, Next.js 16/Vinext, Node.js 22+, GitHub Actions, OpenAI Sites.

## Global Constraints

- The pipeline optimizes decision value per reading minute, not daily coverage.
- Collection is capped at 80 candidates; deterministic shortlisting is capped at 20 and never pads weak candidates to 15.
- “今日必看” is capped at 5, “值得试用” at 3, and “观察项” at 3; the boards are mutually exclusive and may all be empty.
- Main and try items require a verified primary source, a concrete change, a valid evidence anchor, affected audience, affected area and an executable action.
- An inaccessible original source may only enter watch when a trusted secondary source contains a specific fact, and it must be labeled unverified.
- The model extracts facts and classifications only. Program code owns gates, event deduplication, scoring, penalties, board assignment and count limits.
- Event deduplication covers the previous 7 Beijing calendar days.
- A successfully evaluated zero-item run sends exactly one “今日无内容通过硬门槛” Feishu card and is considered successful.
- A single source fetch failure is non-fatal; all shortlisted source fetches failing is a task failure.
- Model parse failure is retried exactly once; the second failure is a task failure.
- Feishu failure does not mark the day as sent. Feishu success followed by web publication failure does mark the day as sent.
- Public JSON contains no full source text, secrets or internal rejection audit.
- Existing Cloudflare and GitHub trigger times remain unchanged.
- Existing `.openai/hosting.json` project ID `appgprj_6a558b7409ec8191bd8c843d592f40eb` must be reused; do not create another Sites project.
- The ignored `web/build/sites-vite-plugin` is a Sites-generated build input, not a source file to commit. Prepare it through the Sites workflow before web build verification.
- Every independently testable feature ends with a short Git commit.

---

## File Structure

- `src/ai_news_bot/models.py`: owns Pydantic transport models, schema v3, board invariants and shared enums.
- `src/ai_news_bot/shortlist.py`: performs deterministic low-cost rough filtering.
- `src/ai_news_bot/source_fetcher.py`: fetches and cleans original documents with bounded failures.
- `src/ai_news_bot/evidence.py`: prompts the model for structured facts, retries parsing once and verifies anchors.
- `src/ai_news_bot/gatekeeper.py`: applies mandatory rejection rules and watch-only source exceptions.
- `src/ai_news_bot/event_history.py`: stores seven-day event fingerprints and classifies duplicates or material updates.
- `src/ai_news_bot/scoring.py`: maps factual signals to deterministic score components and penalties.
- `src/ai_news_bot/boards.py`: creates stable, mutually exclusive 5+3+3 boards.
- `src/ai_news_bot/pipeline.py`: orchestrates the two stages and writes the private audit artifact.
- `src/ai_news_bot/send_ledger.py`: records successful Beijing-date sends, including legal empty sends.
- `src/ai_news_bot/cli.py`: wires collection, pipeline generation, persisted sending and post-send state updates.
- `src/ai_news_bot/feishu.py`: renders board cards and the legal empty card.
- `src/ai_news_bot/daily_guard.py`: checks the successful-send ledger instead of treating generated JSON as proof of delivery.
- `.github/workflows/daily-ai-news.yml`: restores/saves all state and persists public JSON only after Feishu succeeds.
- `web/app/news-data.ts`: validates schema v3 while retaining schema v2 read compatibility.
- `web/app/news-dashboard.tsx`: renders the three boards and evidence/action fields.
- `web/app/summary.ts`: ranks v3 items by `score.total`.
- `web/tests/news-data-contract.test.mjs`: verifies v3 and legacy v2 contracts.
- Python tests mirror each focused module under `tests/`.

---

### Task 1: Define Schema v3 and Editorial Data Contracts

**Files:**
- Modify: `src/ai_news_bot/models.py`
- Create: `tests/test_editorial_models.py`
- Modify: `tests/test_web_export.py`

**Interfaces:**
- Consumes: existing `Candidate` and `Category`.
- Produces: `EvidenceRecord`, `GateDecision`, `ScoreBreakdown`, `EditorialNewsItem`, `DigestBoards`, `PipelineStats`, `EditorialDigest`.

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_editorial_models.py` with fixtures that construct one valid item and assert:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_news_bot.models import (
    ChangeFact,
    EditorialDigest,
    DigestBoards,
    EditorialNewsItem,
    EvidenceAnchor,
    PipelineStats,
    ScoreBreakdown,
)


def item(board: str = "must_read") -> EditorialNewsItem:
    return EditorialNewsItem(
        candidate_id="model-x",
        board=board,
        original_title="Model X API price update",
        title_en="Model X API price update",
        summary_en="Input price falls from $2 to $1 per million tokens.",
        title_zh="Model X API 输入价格减半",
        summary_zh="输入价格从每百万 token 2 美元降至 1 美元。",
        concrete_change="输入价格从每百万 token 2 美元降至 1 美元。",
        affected_audience=["API 开发者"],
        affected_area=["推理成本"],
        recommended_action=["按当前调用量重新计算月成本"],
        evidence_url="https://example.com/pricing",
        verification_status="verified",
        event_fingerprint="example|model-x|price|v2|2026-07-23",
        primary_entity="Example",
        event_entities=["Example", "Model X"],
        change_signature="price",
        version_or_metric="v2-$1",
        resource_available=True,
        source="Example",
        published_at=datetime(2026, 7, 23, tzinfo=UTC),
        category="new_models",
        score=ScoreBreakdown(
            relevance=25,
            actionability=20,
            specificity=15,
            information_gain=15,
            evidence_quality=15,
            time_sensitivity=10,
            penalties=0,
        ),
    )


def test_schema_v3_flattens_mutually_exclusive_boards() -> None:
    story = item()
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, tzinfo=UTC),
        candidate_count=80,
        source_count=20,
        boards=DigestBoards(must_read=[story]),
        items=[story],
        pipeline_stats=PipelineStats(
            candidate_count=80,
            shortlist_count=18,
            source_verified_count=15,
            rejected_count=17,
        ),
    )
    assert digest.schema_version == 3
    assert digest.items == digest.boards.flatten()
    assert digest.run_status == "published"
    assert digest.items[0].score.total == 100


def test_schema_v3_accepts_legal_empty_digest() -> None:
    digest = EditorialDigest(
        generated_at=datetime(2026, 7, 23, tzinfo=UTC),
        candidate_count=12,
        source_count=7,
        run_status="no_qualifying_items",
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=12,
            shortlist_count=4,
            source_verified_count=3,
            rejected_count=4,
            top_rejection_reasons={"missing_concrete_change": 3},
        ),
    )
    assert digest.items == []


def test_schema_v3_rejects_duplicate_or_mismatched_boards() -> None:
    story = item()
    with pytest.raises(ValidationError):
        EditorialDigest(
            generated_at=datetime(2026, 7, 23, tzinfo=UTC),
            candidate_count=1,
            source_count=1,
            boards=DigestBoards(must_read=[story], try_now=[story.model_copy(update={"board": "try_now"})]),
            items=[story],
            pipeline_stats=PipelineStats(
                candidate_count=1,
                shortlist_count=1,
                source_verified_count=1,
                rejected_count=0,
            ),
        )
```

Add a schema-v3 export test to `tests/test_web_export.py` that expects `schema_version == 3`, populated `boards`, and flattened `items`; keep the existing schema-v2 regression tests until the production switch in Task 7.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
pytest tests/test_editorial_models.py tests/test_web_export.py -q
```

Expected: collection fails because the schema v3 classes do not exist.

- [ ] **Step 3: Add exact enums and Pydantic models**

In `src/ai_news_bot/models.py`, retain `Candidate`, `NewsItem` and the schema-v2 `DailyDigest` during migration, and add the independent schema-v3 types below. Production switches to `EditorialDigest` in Task 7; keeping the v2 types until then keeps every intermediate commit importable.

```python
from pydantic import BaseModel, Field, computed_field, model_validator

SourceType = Literal[
    "official_announcement", "paper", "model_card", "repository",
    "law_or_regulation", "financial_filing", "official_demo",
    "trusted_secondary",
]
VerificationStatus = Literal["verified", "unavailable", "blocked", "insufficient"]
BoardName = Literal["must_read", "try_now", "watch"]
RejectionCode = Literal[
    "funding_only", "opinion_without_evidence",
    "policy_without_terms_or_date", "vague_claim_without_evidence",
    "title_body_conflict", "scientific_claim_unverified",
    "duplicate_without_material_update", "missing_concrete_change",
    "missing_action", "missing_affected_audience", "missing_affected_area",
    "invalid_evidence_anchor", "unverified_primary_source",
]


class ChangeFact(BaseModel):
    change_type: str
    statement: str
    numbers: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class EvidenceAnchor(BaseModel):
    quote: str = Field(min_length=4, max_length=500)
    locator: str = Field(min_length=1, max_length=200)


class EvidenceRecord(BaseModel):
    candidate_id: str
    title_zh: str
    summary_zh: str
    category: Category
    extra_categories: list[Category] = Field(default_factory=list, max_length=3)
    source_url: str
    source_type: SourceType
    verification_status: VerificationStatus
    concrete_changes: list[ChangeFact] = Field(default_factory=list)
    evidence_anchors: list[EvidenceAnchor] = Field(default_factory=list)
    affected_audience: list[str] = Field(default_factory=list)
    affected_area: list[str] = Field(default_factory=list)
    recommended_action: list[str] = Field(default_factory=list)
    event_entities: list[str] = Field(default_factory=list)
    primary_entity: str
    product_or_model: str = ""
    change_signature: str
    version_or_metric: str = ""
    effective_date: str | None = None
    relevance_signal: Literal["direct", "adjacent", "low"] = "low"
    action_horizon_days: int | None = Field(default=None, ge=0)
    resource_available: bool = False
    funding_only: bool = False
    opinion_only: bool = False
    policy_claim: bool = False
    vague_claim_without_evidence: bool = False
    title_body_conflict: bool = False
    scientific_claim: bool = False
    original_paper_or_independent_validation: bool = False
    marketing_exaggeration: bool = False
    evidence_covers_full_claim: bool = True


class GateDecision(BaseModel):
    eligible_main_try: bool
    eligible_watch: bool
    rejection_reasons: list[RejectionCode] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    relevance: int = Field(ge=0, le=25)
    actionability: int = Field(ge=0, le=20)
    specificity: int = Field(ge=0, le=15)
    information_gain: int = Field(ge=0, le=15)
    evidence_quality: int = Field(ge=0, le=15)
    time_sensitivity: int = Field(ge=0, le=10)
    penalties: int = Field(default=0, le=0)

    @computed_field
    @property
    def total(self) -> int:
        return max(0, self.relevance + self.actionability + self.specificity
                   + self.information_gain + self.evidence_quality
                   + self.time_sensitivity + self.penalties)


class EditorialDraft(BaseModel):
    candidate_id: str
    original_title: str
    title_en: str = ""
    summary_en: str = ""
    title_zh: str
    summary_zh: str
    concrete_change: str
    affected_audience: list[str]
    affected_area: list[str]
    recommended_action: list[str]
    evidence_url: str
    verification_status: VerificationStatus
    event_fingerprint: str
    update_of: str | None = None
    primary_entity: str
    event_entities: list[str]
    change_signature: str
    version_or_metric: str = ""
    effective_date: str | None = None
    resource_available: bool = False
    scientific_verified: bool = False
    source: str
    published_at: datetime
    category: Category
    extra_categories: list[Category] = Field(default_factory=list)
    score: ScoreBreakdown


class EditorialNewsItem(EditorialDraft):
    board: BoardName


class DigestBoards(BaseModel):
    must_read: list[EditorialNewsItem] = Field(default_factory=list, max_length=5)
    try_now: list[EditorialNewsItem] = Field(default_factory=list, max_length=3)
    watch: list[EditorialNewsItem] = Field(default_factory=list, max_length=3)

    def flatten(self) -> list[EditorialNewsItem]:
        return [*self.must_read, *self.try_now, *self.watch]


class PipelineStats(BaseModel):
    candidate_count: int = Field(ge=0)
    shortlist_count: int = Field(ge=0)
    source_verified_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    top_rejection_reasons: dict[str, int] = Field(default_factory=dict)


class EditorialDigest(BaseModel):
    schema_version: Literal[3] = 3
    run_status: Literal["published", "no_qualifying_items"] = "published"
    generated_at: datetime
    candidate_count: int
    source_count: int
    latest_published_at: datetime | None = None
    fresh_count_24h: int = 0
    lookback_hours: int = 36
    fallback_used: bool = False
    boards: DigestBoards
    items: list[EditorialNewsItem]
    pipeline_stats: PipelineStats

    @model_validator(mode="after")
    def validate_contract(self) -> "EditorialDigest":
        flattened = self.boards.flatten()
        fingerprints = [item.event_fingerprint for item in flattened]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("board items must be mutually exclusive")
        if self.items != flattened:
            raise ValueError("items must equal the flattened boards")
        if self.run_status == "published" and not flattened:
            raise ValueError("published digests require an item")
        if self.run_status == "no_qualifying_items" and flattened:
            raise ValueError("empty digests cannot include items")
        return self
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
pytest tests/test_editorial_models.py tests/test_web_export.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ai_news_bot/models.py tests/test_editorial_models.py tests/test_web_export.py
git commit -m "Add editorial schema v3"
```

---

### Task 2: Add Deterministic Rough Shortlisting

**Files:**
- Create: `src/ai_news_bot/shortlist.py`
- Create: `tests/test_shortlist.py`

**Interfaces:**
- Consumes: `list[Candidate]`, `now: datetime`.
- Produces: `shortlist_candidates(candidates, now, limit=20) -> list[Candidate]`.

- [ ] **Step 1: Write failing boundary and quality tests**

Create `tests/test_shortlist.py` with candidates that assert:

```python
def test_shortlist_caps_at_twenty_and_is_stable() -> None:
    candidates = [candidate(i, title=f"Model {i} API price drops to ${i}") for i in range(30)]
    first = shortlist_candidates(candidates, NOW)
    second = shortlist_candidates(list(reversed(candidates)), NOW)
    assert len(first) == 20
    assert [item.id for item in first] == [item.id for item in second]


def test_shortlist_does_not_pad_weak_opinion_items_to_fifteen() -> None:
    strong = [candidate(i, title=f"SDK v{i} adds API support") for i in range(4)]
    weak = [
        candidate(100 + i, title="AI may transform the future", summary="A broad opinion.")
        for i in range(20)
    ]
    assert [item.id for item in shortlist_candidates(strong + weak, NOW)] == [
        item.id for item in strong
    ]


def test_shortlist_prefers_primary_recent_specific_sources() -> None:
    primary = candidate(1, title="API v2 price is $1", tier=1, hours_old=2)
    secondary = candidate(2, title="API v2 price is $1", tier=3, hours_old=2)
    old = candidate(3, title="API v3 price is $2", tier=1, hours_old=120)
    result = shortlist_candidates([secondary, old, primary], NOW)
    assert result[0].id == primary.id
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
pytest tests/test_shortlist.py -q
```

Expected: import fails because `ai_news_bot.shortlist` does not exist.

- [ ] **Step 3: Implement signal detection and stable ranking**

Create `src/ai_news_bot/shortlist.py`:

```python
from __future__ import annotations

import math
import re
from datetime import datetime

from .models import Candidate

SPECIFIC = re.compile(
    r"(?ix)(\\b(?:api|sdk|model|benchmark|license|pricing|price|tokens?|"
    r"parameters?|revenue|customers?|effective|v\\d+(?:\\.\\d+)*)\\b|"
    r"\\d+(?:\\.\\d+)?\\s*(?:%|x|b|m|k|usd|dollars?|tokens?|params?))"
)
WEAK_ONLY = re.compile(
    r"(?i)\\b(?:may|might|could|potential|future|有望|预示|潜力|值得关注)\\b"
)


def _rough_score(item: Candidate, now: datetime) -> tuple[float, str]:
    text = f"{item.title} {item.summary}"
    age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600)
    freshness = max(0.0, 30 - min(30, age_hours / 4))
    authority = {1: 40, 2: 25, 3: 10}[item.source_tier]
    specificity = 25 if SPECIFIC.search(text) else 0
    repository = min(10, math.log10(float(item.metrics.get("stars", 0)) + 1) * 3)
    return authority + freshness + specificity + item.source_weight * 5 + repository, item.id


def shortlist_candidates(
    candidates: list[Candidate], now: datetime, limit: int = 20
) -> list[Candidate]:
    eligible = []
    for item in candidates:
        text = f"{item.title} {item.summary}"
        if not SPECIFIC.search(text):
            continue
        if WEAK_ONLY.search(text) and not re.search(r"\\d|\\b(?:api|sdk|v\\d)\\b", text, re.I):
            continue
        eligible.append(item)
    return sorted(eligible, key=lambda item: (-_rough_score(item, now)[0], item.id))[:limit]
```

- [ ] **Step 4: Run focused and collection tests**

Run:

```bash
pytest tests/test_shortlist.py tests/test_collectors.py tests/test_dedupe.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ai_news_bot/shortlist.py tests/test_shortlist.py
git commit -m "Add deterministic candidate shortlist"
```

---

### Task 3: Fetch and Clean Original Sources

**Files:**
- Create: `src/ai_news_bot/source_fetcher.py`
- Create: `tests/test_source_fetcher.py`

**Interfaces:**
- Consumes: `list[Candidate]`.
- Produces: `FetchedSource`, `fetch_sources(candidates) -> list[FetchedSource]`.
- Raises: `AllSourcesUnavailableError` only when every shortlisted source fails.

- [ ] **Step 1: Write failing fetch tests with injected HTTP sessions**

Create tests for successful HTML cleaning, redirect URL retention, a single timeout continuing, and all failures raising:

```python
def test_fetch_sources_keeps_success_when_another_source_times_out() -> None:
    session = FakeSession([
        requests.Timeout("slow"),
        FakeResponse(
            url="https://example.com/final",
            text="<h1>Model X v2</h1><p>Input price is $1 per million tokens.</p>",
        ),
    ])
    result = SourceFetcher(session=session, timeout=5).fetch_many([one(), two()])
    assert [item.status for item in result] == ["unavailable", "verified"]
    assert "Input price is $1" in result[1].text
    assert result[1].final_url == "https://example.com/final"


def test_fetch_sources_raises_when_every_original_is_unavailable() -> None:
    session = FakeSession([requests.Timeout("slow"), requests.ConnectionError("down")])
    with pytest.raises(AllSourcesUnavailableError):
        SourceFetcher(session=session, timeout=5).fetch_many([one(), two()])
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
pytest tests/test_source_fetcher.py -q
```

Expected: import fails because `source_fetcher.py` does not exist.

- [ ] **Step 3: Implement bounded original-document fetching**

Create `src/ai_news_bot/source_fetcher.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from .models import Candidate


class AllSourcesUnavailableError(RuntimeError):
    pass


class FetchedSource(BaseModel):
    candidate_id: str
    requested_url: str
    final_url: str
    status: Literal["verified", "unavailable", "blocked", "insufficient"]
    status_code: int | None = None
    title: str = ""
    text: str = ""
    fetched_at: datetime
    error: str = ""


class SourceFetcher:
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 20,
        max_chars: int = 80_000,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_chars = max_chars

    def fetch_one(self, candidate: Candidate) -> FetchedSource:
        now = datetime.now(UTC)
        try:
            response = self.session.get(
                candidate.url,
                timeout=self.timeout,
                headers={"User-Agent": "AI-News-Bot/0.2 (+evidence verification)"},
            )
            status = response.status_code
            if status in {401, 403, 429}:
                return FetchedSource(
                    candidate_id=candidate.id, requested_url=candidate.url,
                    final_url=response.url, status="blocked", status_code=status,
                    fetched_at=now, error=f"HTTP {status}",
                )
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", "text/html").lower():
                raise ValueError("unsupported content type")
            soup = BeautifulSoup(response.text, "html.parser")
            for node in soup(["script", "style", "nav", "footer", "noscript"]):
                node.decompose()
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            text = "\\n".join(
                part.strip() for part in soup.get_text("\\n").splitlines() if part.strip()
            )[: self.max_chars]
            state = "verified" if len(text) >= 80 else "insufficient"
            return FetchedSource(
                candidate_id=candidate.id, requested_url=candidate.url,
                final_url=response.url, status=state, status_code=status,
                title=title, text=text, fetched_at=now,
            )
        except (requests.RequestException, ValueError) as error:
            return FetchedSource(
                candidate_id=candidate.id, requested_url=candidate.url,
                final_url=candidate.url, status="unavailable", fetched_at=now,
                error=type(error).__name__,
            )

    def fetch_many(self, candidates: list[Candidate]) -> list[FetchedSource]:
        results = [self.fetch_one(candidate) for candidate in candidates]
        if results and all(item.status != "verified" for item in results):
            raise AllSourcesUnavailableError("all shortlisted original sources failed")
        return results
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_source_fetcher.py -q
```

Expected: all tests pass without real network access.

- [ ] **Step 5: Commit**

```bash
git add src/ai_news_bot/source_fetcher.py tests/test_source_fetcher.py
git commit -m "Add original source verification"
```

---

### Task 4: Extract Structured Evidence and Validate Anchors

**Files:**
- Create: `src/ai_news_bot/evidence.py`
- Create: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `Candidate`, `FetchedSource`, OpenAI-compatible client.
- Produces: `extract_evidence(candidate, source, client, model) -> EvidenceRecord`.
- Raises: `EvidenceExtractionError` after exactly two failed parse attempts.

- [ ] **Step 1: Write failing extraction and anchor tests**

Create tests that assert a parse failure retries once, a second failure raises, and a fabricated quote changes verification to insufficient:

```python
def test_extractor_retries_once_then_returns_record() -> None:
    client = FakeStructuredClient([ValueError("bad json"), valid_record()])
    result = extract_evidence(candidate(), fetched(), client, "test-model")
    assert result.candidate_id == "one"
    assert client.calls == 2


def test_extractor_stops_after_second_parse_failure() -> None:
    client = FakeStructuredClient([ValueError("bad"), ValueError("bad again")])
    with pytest.raises(EvidenceExtractionError):
        extract_evidence(candidate(), fetched(), client, "test-model")
    assert client.calls == 2


def test_anchor_validator_rejects_quote_not_present_in_source() -> None:
    record = valid_record().model_copy(update={
        "evidence_anchors": [EvidenceAnchor(quote="invented price", locator="Pricing")]
    })
    checked = validate_anchors(record, fetched())
    assert checked.verification_status == "insufficient"
    assert checked.evidence_anchors == []
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
pytest tests/test_evidence.py -q
```

Expected: import fails because `evidence.py` does not exist.

- [ ] **Step 3: Implement constrained extraction and literal anchor validation**

Create `src/ai_news_bot/evidence.py`. The system prompt must state that page content is untrusted, facts must come only from the supplied source, and scores/boards must not be produced. Implement:

```python
class EvidenceBatch(BaseModel):
    records: list[EvidenceRecord]


class EvidenceExtractionError(RuntimeError):
    pass


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def validate_anchors(record: EvidenceRecord, source: FetchedSource) -> EvidenceRecord:
    body = _normalized(source.text)
    anchors = [
        anchor for anchor in record.evidence_anchors
        if _normalized(anchor.quote) in body
    ]
    status = record.verification_status
    if source.status != "verified" or not anchors:
        status = "insufficient" if source.status == "verified" else source.status
    return record.model_copy(update={
        "source_url": source.final_url,
        "verification_status": status,
        "evidence_anchors": anchors,
    })


def extract_evidence(
    candidate: Candidate,
    source: FetchedSource,
    client,
    model: str,
) -> EvidenceRecord:
    messages = [
        {"role": "system", "content": EVIDENCE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({
            "candidate_id": candidate.id,
            "candidate_title": candidate.title,
            "candidate_summary": truncate(candidate.summary, 1200),
            "source_url": source.final_url,
            "source_title": source.title,
            "source_text": truncate(source.text, 30_000),
        }, ensure_ascii=False)},
    ]
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            parsed = client.responses.parse(
                model=model, input=messages, text_format=EvidenceRecord
            ).output_parsed
            if parsed is None or parsed.candidate_id != candidate.id:
                raise ValueError("missing or mismatched evidence record")
            return validate_anchors(parsed, source)
        except (ValueError, TypeError) as error:
            last_error = error
    raise EvidenceExtractionError("model evidence parsing failed twice") from last_error
```

For GitHub Models compatibility, add this private adapter. Tests inject a fake client and never call a live model:

```python
def _parse_response(client, model: str, messages: list[dict[str, str]], base_url: str | None):
    if base_url:
        response = client.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=EvidenceRecord,
        )
        return response.choices[0].message.parsed
    response = client.responses.parse(
        model=model,
        input=messages,
        text_format=EvidenceRecord,
    )
    return response.output_parsed
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_evidence.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ai_news_bot/evidence.py tests/test_evidence.py
git commit -m "Add structured evidence extraction"
```

---

### Task 5: Enforce Non-Bypassable Editorial Gates

**Files:**
- Create: `src/ai_news_bot/gatekeeper.py`
- Create: `tests/test_gatekeeper.py`

**Interfaces:**
- Consumes: `EvidenceRecord`, duplicate classification.
- Produces: `evaluate_gates(record, duplicate_status) -> GateDecision`.

- [ ] **Step 1: Write one parameterized failing test per mandatory rejection**

Create `tests/test_gatekeeper.py` with a valid-record fixture and:

```python
@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"funding_only": True}, "funding_only"),
        ({"opinion_only": True}, "opinion_without_evidence"),
        ({"policy_claim": True, "effective_date": None}, "policy_without_terms_or_date"),
        ({"vague_claim_without_evidence": True}, "vague_claim_without_evidence"),
        ({"title_body_conflict": True}, "title_body_conflict"),
        (
            {"scientific_claim": True, "original_paper_or_independent_validation": False},
            "scientific_claim_unverified",
        ),
        ({"concrete_changes": []}, "missing_concrete_change"),
        ({"recommended_action": []}, "missing_action"),
        ({"evidence_anchors": []}, "invalid_evidence_anchor"),
    ],
)
def test_forced_rejections(changes: dict, reason: str) -> None:
    decision = evaluate_gates(valid_record().model_copy(update=changes), "unique")
    assert not decision.eligible_main_try
    assert reason in decision.rejection_reasons


def test_unavailable_original_is_watch_only_with_trusted_specific_secondary() -> None:
    record = valid_record().model_copy(update={
        "source_type": "trusted_secondary",
        "verification_status": "unavailable",
    })
    decision = evaluate_gates(record, "unique")
    assert not decision.eligible_main_try
    assert decision.eligible_watch


def test_duplicate_without_material_update_is_rejected_everywhere() -> None:
    decision = evaluate_gates(valid_record(), "duplicate")
    assert decision.rejection_reasons == ["duplicate_without_material_update"]
    assert not decision.eligible_watch
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
pytest tests/test_gatekeeper.py -q
```

Expected: import fails because `gatekeeper.py` does not exist.

- [ ] **Step 3: Implement explicit reason accumulation**

Create `src/ai_news_bot/gatekeeper.py` with a fixed check table:

```python
def evaluate_gates(
    record: EvidenceRecord,
    duplicate_status: Literal["unique", "material_update", "minor_update", "duplicate"],
) -> GateDecision:
    reasons: list[RejectionCode] = []
    checks = [
        (record.funding_only, "funding_only"),
        (record.opinion_only, "opinion_without_evidence"),
        (record.policy_claim and not record.effective_date, "policy_without_terms_or_date"),
        (record.vague_claim_without_evidence, "vague_claim_without_evidence"),
        (record.title_body_conflict, "title_body_conflict"),
        (
            record.scientific_claim
            and not record.original_paper_or_independent_validation,
            "scientific_claim_unverified",
        ),
        (not record.concrete_changes, "missing_concrete_change"),
        (not record.recommended_action, "missing_action"),
        (not record.affected_audience, "missing_affected_audience"),
        (not record.affected_area, "missing_affected_area"),
        (not record.evidence_anchors, "invalid_evidence_anchor"),
        (
            duplicate_status in {"duplicate", "minor_update"},
            "duplicate_without_material_update",
        ),
    ]
    reasons.extend(code for failed, code in checks if failed)
    verified_primary = (
        record.verification_status == "verified"
        and record.source_type != "trusted_secondary"
    )
    if not verified_primary:
        reasons.append("unverified_primary_source")
    fatal_watch = set(reasons) - {"unverified_primary_source"}
    trusted_watch = (
        record.source_type == "trusted_secondary"
        and record.verification_status in {"unavailable", "blocked"}
        and bool(record.concrete_changes)
        and bool(record.evidence_anchors)
    )
    return GateDecision(
        eligible_main_try=verified_primary and not reasons,
        eligible_watch=(not fatal_watch) and (verified_primary or trusted_watch),
        rejection_reasons=list(dict.fromkeys(reasons)),
    )
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_gatekeeper.py -q
```

Expected: all gate tests pass and every rejection exposes a stable code.

- [ ] **Step 5: Commit**

```bash
git add src/ai_news_bot/gatekeeper.py tests/test_gatekeeper.py
git commit -m "Enforce editorial hard gates"
```

---

### Task 6: Add Seven-Day Event History, Scoring and Boards

**Files:**
- Create: `src/ai_news_bot/event_history.py`
- Create: `src/ai_news_bot/scoring.py`
- Create: `src/ai_news_bot/boards.py`
- Create: `tests/test_event_history.py`
- Create: `tests/test_scoring.py`
- Create: `tests/test_boards.py`

**Interfaces:**
- Produces: `event_fingerprint(record) -> str`.
- Produces: `EventHistoryStore.classify(record, now) -> DuplicateAssessment`.
- Produces: `EventHistoryStore.record(records: list[EvidenceRecord], now: datetime) -> None` for deterministic tests and `record_digest(digest: EditorialDigest, now: datetime | None = None) -> None` for post-send production state.
- Produces: `score_record(record, assessment, published_at, now) -> ScoreBreakdown`.
- Produces: `build_boards(items_with_decisions) -> DigestBoards`.

- [ ] **Step 1: Write failing event-history tests**

Test exact duplicates, entity/signature near duplicates, material version/price updates and retention:

```python
def test_exact_event_with_no_new_fact_is_duplicate(tmp_path: Path) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    store.record([event("v2", "$1")], NOW)
    assert store.classify(event("v2", "$1"), NOW + timedelta(days=1)).status == "duplicate"


def test_changed_version_or_metric_is_material_update(tmp_path: Path) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    old = event("v2", "$2")
    store.record([old], NOW)
    result = store.classify(event("v3", "$1"), NOW + timedelta(days=1))
    assert result.status == "material_update"
    assert result.update_of == event_fingerprint(old)


def test_events_older_than_seven_beijing_days_do_not_dedupe(tmp_path: Path) -> None:
    store = EventHistoryStore(tmp_path / "events.json")
    store.record([event("v2", "$1")], NOW - timedelta(days=8))
    assert store.classify(event("v2", "$1"), NOW).status == "unique"
```

- [ ] **Step 2: Write failing score and board tests**

Assert exact totals, all penalties, thresholds, caps, exclusivity and company concentration:

```python
def test_score_maps_factual_signals_and_penalties_exactly() -> None:
    score = score_record(
        valid_record().model_copy(update={
            "marketing_exaggeration": True,
            "evidence_covers_full_claim": False,
        }),
        DuplicateAssessment(status="material_update"),
        published_at=NOW - timedelta(hours=80),
        now=NOW,
    )
    assert score.model_dump() == {
        "relevance": 25, "actionability": 20, "specificity": 15,
        "information_gain": 10, "evidence_quality": 15,
        "time_sensitivity": 2, "penalties": -35, "total": 52,
    }
    assert score.total == 52


def test_boards_are_mutually_exclusive_and_never_pad() -> None:
    result = build_boards([
        scored("a", total=80, evidence=15, gain=15, action=20),
        scored("b", total=65, evidence=12, gain=9, action=16, resource=True),
        scored("c", total=49, evidence=15, gain=15, action=20),
    ])
    assert [item.candidate_id for item in result.must_read] == ["a"]
    assert [item.candidate_id for item in result.try_now] == ["b"]
    assert result.watch == []
    assert len({item.event_fingerprint for item in result.flatten()}) == 2


def test_third_item_from_same_company_cannot_enter_main_or_try() -> None:
    result = build_boards([scored("a", company="Acme"), scored("b", company="Acme"),
                           scored("c", company="Acme")])
    assert [item.candidate_id for item in result.must_read + result.try_now] == ["a", "b"]
```

- [ ] **Step 3: Run and verify RED**

Run:

```bash
pytest tests/test_event_history.py tests/test_scoring.py tests/test_boards.py -q
```

Expected: imports fail because the three modules do not exist.

- [ ] **Step 4: Implement fingerprints and seven-day classification**

In `event_history.py`, normalize with `casefold`, Unicode word tokens and sorted entities. Persist:

```json
{
  "events": [
    {
      "fingerprint": "acme|model-x|price|v2-$1|2026-07-23",
      "recorded_at": "2026-07-23T01:05:00+00:00",
      "entities": ["acme", "model-x"],
      "change_signature": "price",
      "version_or_metric": "v2-$1",
      "source_url": "https://example.com/pricing"
    }
  ]
}
```

Define:

```python
class DuplicateAssessment(BaseModel):
    status: Literal["unique", "material_update", "minor_update", "duplicate"]
    update_of: str | None = None


def event_fingerprint(record: EvidenceRecord) -> str:
    parts = [
        record.primary_entity, record.product_or_model,
        record.change_signature, record.version_or_metric,
        record.effective_date or "",
    ]
    return "|".join(_slug(part) for part in parts)
```

`classify` first checks exact fingerprints, then entity overlap plus equal change signature. A changed `version_or_metric`, `effective_date`, newly available resource, or newly verified scientific evidence is `material_update`; equal facts are `duplicate`; only descriptive wording changes are `minor_update`.

- [ ] **Step 5: Implement deterministic scoring**

In `scoring.py`, use these exact mappings:

```python
RELEVANCE = {"direct": 25, "adjacent": 15, "low": 5}
INFORMATION_GAIN = {
    "unique": 15, "material_update": 10, "minor_update": 3, "duplicate": 0
}
EVIDENCE = {
    "official_announcement": 15, "paper": 15, "model_card": 15,
    "repository": 14, "law_or_regulation": 15, "financial_filing": 15,
    "official_demo": 12, "trusted_secondary": 8,
}


def score_record(record, assessment, published_at, now) -> ScoreBreakdown:
    actionability = (
        20 if record.resource_available and record.action_horizon_days is not None
        and record.action_horizon_days <= 7
        else 14 if record.recommended_action else 0
    )
    specificity = min(
        15,
        len(record.concrete_changes) * 7
        + (4 if record.version_or_metric else 0)
        + (4 if record.effective_date else 0),
    )
    evidence_quality = EVIDENCE[record.source_type]
    age_hours = max(0, (now - published_at).total_seconds() / 3600)
    time_sensitivity = 10 if age_hours <= 24 else 7 if age_hours <= 72 else 2
    penalties = 0
    if assessment.status == "minor_update":
        penalties -= 20
    if not record.evidence_covers_full_claim:
        penalties -= 15
    if record.marketing_exaggeration:
        penalties -= 10
    if age_hours > 72 and not record.effective_date:
        penalties -= 10
    return ScoreBreakdown(
        relevance=RELEVANCE[record.relevance_signal],
        actionability=actionability,
        specificity=specificity,
        information_gain=INFORMATION_GAIN[assessment.status],
        evidence_quality=evidence_quality,
        time_sensitivity=time_sensitivity,
        penalties=penalties,
    )
```

- [ ] **Step 6: Implement stable board allocation**

`boards.py` receives this explicitly defined wrapper and sorts by `(-total, -information_gain, -evidence_quality, -published_timestamp, fingerprint)`:

```python
class ScoredEditorialCandidate(BaseModel):
    record: EvidenceRecord
    decision: GateDecision
    assessment: DuplicateAssessment
    draft: EditorialDraft
```

Allocate:

```python
must = eligible_main_try and total >= 75 and evidence_quality >= 12 and information_gain >= 10
try_now = (
    eligible_main_try and total >= 62 and actionability >= 14
    and record.resource_available and record.action_horizon_days is not None
    and record.action_horizon_days <= 7
)
watch = eligible_watch and total >= 50
```

Process must first (max 5), then remaining try (max 3), then remaining watch (max 3). Maintain a `main_try_company_counts` dictionary and skip a third item from the same primary entity in the first two boards. Convert a selected draft with `EditorialNewsItem(**candidate.draft.model_dump(), board=board_name)`.

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/test_event_history.py tests/test_scoring.py tests/test_boards.py -q
```

Expected: all tests pass with stable order across repeated runs.

- [ ] **Step 8: Commit**

```bash
git add src/ai_news_bot/event_history.py src/ai_news_bot/scoring.py src/ai_news_bot/boards.py tests/test_event_history.py tests/test_scoring.py tests/test_boards.py
git commit -m "Add event scoring and boards"
```

---

### Task 7: Orchestrate the Pipeline and Correct Send-State Semantics

**Files:**
- Create: `src/ai_news_bot/pipeline.py`
- Create: `src/ai_news_bot/send_ledger.py`
- Create: `tests/test_pipeline.py`
- Create: `tests/test_send_ledger.py`
- Modify: `src/ai_news_bot/config.py`
- Modify: `src/ai_news_bot/cli.py`
- Modify: `src/ai_news_bot/daily_guard.py`
- Modify: `src/ai_news_bot/history.py`
- Modify: `.github/workflows/daily-ai-news.yml`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_daily_guard.py`

**Interfaces:**
- Produces: `run_editorial_pipeline(candidates, dependencies, now) -> PipelineResult`.
- Produces: `SendLedger.was_sent(day: date, target: str = "feishu-daily") -> bool`.
- Produces: `SendLedger.record_success(digest: EditorialDigest, target: str = "feishu-daily", now: datetime | None = None) -> None`.
- Changes: `--send-existing` sends both published and legal empty digests.

- [ ] **Step 1: Write failing orchestration tests**

Test the stage order and legal empty/system failure distinction:

```python
def test_pipeline_shortlists_fetches_extracts_gates_scores_and_builds_digest() -> None:
    trace: list[str] = []
    result = run_editorial_pipeline(
        candidates(),
        dependencies=fakes(trace, qualifying=True),
        now=NOW,
    )
    assert trace == ["shortlist", "fetch", "extract", "gates", "dedupe", "score", "boards"]
    assert result.digest.run_status == "published"
    assert result.digest.items
    assert result.audit.rejected


def test_successful_pipeline_with_zero_qualifiers_is_legal_empty() -> None:
    result = run_editorial_pipeline(
        candidates(), dependencies=fakes([], qualifying=False), now=NOW
    )
    assert result.digest.run_status == "no_qualifying_items"
    assert result.digest.items == []


def test_all_fetches_failed_is_not_legal_empty() -> None:
    with pytest.raises(AllSourcesUnavailableError):
        run_editorial_pipeline(
            candidates(), dependencies=fakes([], all_fetches_fail=True), now=NOW
        )
```

- [ ] **Step 2: Write failing send and guard tests**

Update `tests/test_cli.py`:

```python
def test_send_existing_sends_empty_card_and_records_daily_success(monkeypatch, tmp_path):
    digest = legal_empty_digest()
    output = tmp_path / "latest.json"
    output.write_text(digest.model_dump_json(), encoding="utf-8")
    sent, ledger = [], []
    monkeypatch.setattr(cli, "send_to_feishu", lambda value, *args: sent.append(value))
    monkeypatch.setattr(cli.SendLedger, "record_success",
                        lambda self, value, target, now=None: ledger.append(value.run_status))
    assert cli.run(_send_existing_args(output)) == 0
    assert sent == [digest]
    assert ledger == ["no_qualifying_items"]


def test_feishu_failure_does_not_record_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "send_to_feishu",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("Feishu down")))
    recorded = []
    monkeypatch.setattr(cli.SendLedger, "record_success",
                        lambda *args: recorded.append(True))
    with pytest.raises(RuntimeError, match="Feishu down"):
        cli.run(_send_existing_args(write_published(tmp_path)))
    assert recorded == []
```

Update `tests/test_daily_guard.py` so a generated digest without a successful ledger remains runnable, while a ledger entry for today blocks both schedule and repository dispatch.

- [ ] **Step 3: Implement the private audit and pipeline orchestration**

In `pipeline.py`, define `AuditEntry`, `PipelineAudit`, `PipelineResult` and dependency callables. `run_editorial_pipeline` must:

1. call `shortlist_candidates`;
2. call `SourceFetcher.fetch_many`;
3. extract and anchor-check every fetched source;
4. classify each event;
5. apply gates and scores;
6. construct candidate output copy;
7. call `build_boards`;
8. aggregate rejection reason counts;
9. return a schema v3 published or legal empty digest;
10. write audit JSON only through `write_audit(result.audit, path)`.

The public digest receives counts only. Audit entries include candidate ID, source URL, fetch status, anchor locators, gate reasons, duplicate status and score breakdown, but never full fetched text.

- [ ] **Step 4: Implement a successful-send ledger**

Create `send_ledger.py`:

```python
class SendLedger:
    def __init__(self, path: Path, timezone: str = "Asia/Shanghai") -> None:
        self.path = path
        self.zone = ZoneInfo(timezone)

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(value.get("successful_sends", {}))
        except (OSError, ValueError, TypeError):
            return {}

    def was_sent(self, day: date, target: str = "feishu-daily") -> bool:
        return f"{day.isoformat()}|{target}" in self._load()

    def record_success(
        self, digest: EditorialDigest, target: str = "feishu-daily",
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        day = digest.generated_at.astimezone(self.zone).date()
        data = self._load()
        data[f"{day.isoformat()}|{target}"] = {
            "sent_at": timestamp.isoformat(),
            "run_status": digest.run_status,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"successful_sends": data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
```

Add `event_history_path`, `send_ledger_path` and `audit_path` to `Settings`, defaulting to `.state/events.json`, `.state/daily_sends.json` and `.state/latest_audit.json`.

- [ ] **Step 5: Rewire CLI state changes after Feishu success**

Generation mode calls the new pipeline and writes the digest/audit but does not mutate history, event history or send ledger.

Remove the production imports of `build_digest`, `select_with_openai` and `select_without_ai` from `cli.py`. Persisted results are loaded with `EditorialDigest.model_validate_json(...)`; the old schema-v2 curator remains importable only for its existing regression tests during this migration.

`_send_existing_daily_result` must execute in this order:

```python
send_to_feishu(digest, webhook_url, signing_secret, timeout)
SendLedger(settings.send_ledger_path).record_success(digest)
if digest.items:
    HistoryStore(settings.state_path).record(digest.items)
    EventHistoryStore(settings.event_history_path).record_digest(digest)
```

Update `HistoryStore.record` to accept `list[EditorialNewsItem]` and canonicalize `item.evidence_url`. `EventHistoryStore.record_digest` reads the event metadata carried by each selected item, so it never needs the private fetched source text.

Remove the early return that currently skips Feishu for `no_qualifying_items`.

- [ ] **Step 6: Make the daily guard depend on successful delivery**

Replace digest/history timestamp inference with:

```python
def should_run_daily_digest(
    event_name: str,
    ledger_path: Path,
    timezone: str = "Asia/Shanghai",
    now: datetime | None = None,
) -> bool:
    if event_name not in AUTOMATED_EVENTS:
        return True
    zone = ZoneInfo(timezone)
    current = now or datetime.now(UTC)
    return not SendLedger(ledger_path, timezone).was_sent(
        current.astimezone(zone).date()
    )
```

Change the CLI arguments from `--digest/--history` to `--ledger`.

- [ ] **Step 7: Reorder and persist workflow state**

In `.github/workflows/daily-ai-news.yml`:

- restore and save the whole `.state/` directory;
- call the guard with `--ledger .state/daily_sends.json`;
- generate the digest;
- send the persisted digest;
- persist `web/public/data/latest.json` only after the send step succeeds;
- publish the dashboard after persistence;
- keep the cache-save step under `if: always() && steps.send_digest.outcome == 'success'`.

This order guarantees a Feishu failure remains retryable and a post-send Git/Sites failure does not duplicate the Feishu message.

- [ ] **Step 8: Run focused and full Python tests**

Run:

```bash
pytest tests/test_pipeline.py tests/test_send_ledger.py tests/test_cli.py tests/test_daily_guard.py -q
pytest -q
```

Expected: focused tests and the full Python suite pass with zero failures.

- [ ] **Step 9: Commit**

```bash
git add src/ai_news_bot/pipeline.py src/ai_news_bot/send_ledger.py src/ai_news_bot/config.py src/ai_news_bot/cli.py src/ai_news_bot/daily_guard.py src/ai_news_bot/history.py .github/workflows/daily-ai-news.yml tests/test_pipeline.py tests/test_send_ledger.py tests/test_cli.py tests/test_daily_guard.py
git commit -m "Wire editorial pipeline delivery"
```

---

### Task 8: Render Three Feishu Boards and Legal Empty Cards

**Files:**
- Modify: `src/ai_news_bot/feishu.py`
- Modify: `tests/test_feishu.py`

**Interfaces:**
- Consumes: schema v3 `EditorialDigest`.
- Produces: an interactive card for published and legal empty results.

- [ ] **Step 1: Write failing card tests**

Add:

```python
def test_published_card_has_three_board_sections_and_action_evidence() -> None:
    content = build_card(three_board_digest())["card"]["body"]["elements"][0]["content"]
    assert "今日必看" in content
    assert "值得试用" in content
    assert "观察项" in content
    assert "建议行动" in content
    assert "核查原文" in content
    assert "这对行业具有重要意义" not in content


def test_legal_empty_card_is_sent_as_normal_success_content() -> None:
    card = build_card(legal_empty_digest())
    content = card["card"]["body"]["elements"][0]["content"]
    assert "今日无内容通过硬门槛" in content
    assert "候选 12 条" in content
    assert "已核查来源 3 条" in content
    assert "缺少具体变化：3" in content
    assert card["card"]["header"]["subtitle"]["content"] == "严格筛选完成 · AI 增长内部群"
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
pytest tests/test_feishu.py -q
```

Expected: tests fail because the current renderer is a single flat list and empty content has no explicit message.

- [ ] **Step 3: Implement board-oriented markdown**

Add board labels and rejection labels:

```python
BOARD_LABELS = {
    "must_read": "今日必看",
    "try_now": "值得试用",
    "watch": "观察项",
}
REJECTION_LABELS = {
    "missing_concrete_change": "缺少具体变化",
    "invalid_evidence_anchor": "证据无法核查",
    "duplicate_without_material_update": "过去 7 天重复",
    "missing_action": "缺少可执行行动",
}
```

For every non-empty board, render each item as:

```text
**1. [中文标题](evidence_url)** `总分 82`
变化：具体变化
影响：受影响对象 · 受影响内容
行动：建议行动
[核查原文](evidence_url)
```

Watch-only inaccessible originals append `⚠ 原始来源暂不可核查`.

For `no_qualifying_items`, render:

```text
**今日无内容通过硬门槛**

已检查候选 {candidate_count} 条，粗筛 {shortlist_count} 条，已核查来源 {source_verified_count} 条。

主要淘汰原因：
- {中文原因}：{count}
```

Keep `_truncate_utf8` at 18 KB and the official webhook validation unchanged.

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_feishu.py -q
```

Expected: all Feishu tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ai_news_bot/feishu.py tests/test_feishu.py
git commit -m "Render editorial Feishu boards"
```

---

### Task 9: Upgrade the Website to Schema v3 and Validate Through Sites

**Files:**
- Modify: `web/app/news-data.ts`
- Modify: `web/app/news-dashboard.tsx`
- Modify: `web/app/summary.ts`
- Modify: `web/app/page.tsx`
- Modify: `web/tests/news-data-contract.test.mjs`
- Modify: `web/tests/rendered-html.test.mjs`
- Modify: `web/public/data/latest.json`

**Interfaces:**
- Consumes: schema v3 `boards`, flattened `items`, score/evidence/action fields.
- Retains: read compatibility for valid schema v2 published and empty digests.

- [ ] **Step 1: Write failing schema and rendered-content tests**

Update `news-data-contract.test.mjs` to assert:

```javascript
assert.match(source, /schema_version:\\s*3/);
assert.match(source, /boards:\\s*DigestBoards/);
assert.match(source, /must_read:\\s*NewsItem\\[\\]/);
assert.match(source, /candidate\\.schema_version\\s*===\\s*3/);
assert.match(source, /candidate\\.items\\.length\\s*===\\s*flattened\\.length/);
assert.match(source, /candidate\\.schema_version\\s*===\\s*2/);
```

Update `rendered-html.test.mjs` so the schema v3 fixture asserts the rendered HTML contains “今日必看”, “值得试用”, “建议行动” and the evidence URL. Add an empty v3 fixture that asserts “今日无内容通过硬门槛”.

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```bash
cd web
node --test tests/news-data-contract.test.mjs
```

Expected: assertions fail because `news-data.ts` only defines schema v2.

- [ ] **Step 3: Implement schema v3 validation with v2 compatibility**

Define:

```typescript
export type BoardName = "must_read" | "try_now" | "watch";
export type ScoreBreakdown = {
  relevance: number;
  actionability: number;
  specificity: number;
  information_gain: number;
  evidence_quality: number;
  time_sensitivity: number;
  penalties: number;
  total: number;
};
export type NewsItem = {
  candidate_id: string;
  board: BoardName;
  original_title: string;
  title_en?: string;
  summary_en?: string;
  title_zh: string;
  summary_zh: string;
  concrete_change: string;
  affected_audience: string[];
  affected_area: string[];
  recommended_action: string[];
  evidence_url: string;
  verification_status: "verified" | "unavailable" | "blocked" | "insufficient";
  event_fingerprint: string;
  update_of?: string | null;
  primary_entity: string;
  event_entities: string[];
  change_signature: string;
  version_or_metric: string;
  effective_date?: string | null;
  resource_available: boolean;
  scientific_verified: boolean;
  source: string;
  published_at: string;
  category: Exclude<Category, "all">;
  extra_categories: Exclude<Category, "all">[];
  score: ScoreBreakdown;
};
export type DigestBoards = {
  must_read: NewsItem[];
  try_now: NewsItem[];
  watch: NewsItem[];
};
export type Digest = {
  schema_version: 3;
  run_status: "published" | "no_qualifying_items";
  generated_at: string;
  candidate_count: number;
  source_count: number;
  boards: DigestBoards;
  items: NewsItem[];
  pipeline_stats: {
    candidate_count: number;
    shortlist_count: number;
    source_verified_count: number;
    rejected_count: number;
    top_rejection_reasons: Record<string, number>;
  };
};
```

`isDigest` validates board caps, unique fingerprints, flattened order equality, HTTPS evidence URLs and status/items agreement. Keep a narrow `LegacyDigestV2` validator and add `normalizeDigest(value: unknown) -> Digest`: valid v3 is returned unchanged; valid v2 items map `url` to `evidence_url`, `importance` to a compatibility score, and the whole list to `must_read` only for reading old persisted data during rollout. Export `digest = normalizeDigest(latestDigest)` instead of a type assertion.

- [ ] **Step 4: Render boards without adding client fetch waterfalls**

Keep `initialDigest` server-provided. In `news-dashboard.tsx`, derive visible board arrays with `useMemo` from the existing filter/search state. Render three sections in board order and reuse a top-level `StoryCard`; do not define components inside `NewsDashboard`.

Each story shows:

- specific change;
- affected audience and area;
- recommended action;
- evidence link;
- total score;
- unverified warning when applicable.

For a legal empty digest, render “今日无内容通过硬门槛” plus pipeline counts. Update page metadata from “每天筛选约 10 条” to “每天严格核查高决策价值 AI 信息，宁缺毋滥”.

In `summary.ts`, sort with:

```typescript
const sorted = [...digest.items].sort((a, b) => b.score.total - a.score.total);
```

and build narrative summaries from `concrete_change`, impact and action rather than the prohibited generic wording.

- [ ] **Step 5: Replace the checked-in sample with valid schema v3**

Generate `web/public/data/latest.json` through the Python schema rather than hand-editing it. Use one story per board in the fixture so both website and Python contract tests load the same shape.

- [ ] **Step 6: Prepare the existing Sites project and run web verification**

Read `web/.openai/hosting.json` first and reuse its exact project ID. Use the Sites capability workflow to prepare the ignored `build/sites-vite-plugin` for this source tree, then run:

```bash
cd web
npm run build
node --test tests/*.test.mjs
```

Expected: build succeeds and all Node tests pass. Do not commit `web/build/`, `.vinext/`, `dist/`, `.wrangler/` or a newly generated workspace file.

- [ ] **Step 7: Run Python contract regression**

Run:

```bash
pytest tests/test_web_export.py tests/test_cli.py -q
```

Expected: all tests pass against schema v3.

- [ ] **Step 8: Commit**

```bash
git add web/app/news-data.ts web/app/news-dashboard.tsx web/app/summary.ts web/app/page.tsx web/tests/news-data-contract.test.mjs web/tests/rendered-html.test.mjs web/public/data/latest.json
git commit -m "Show editorial boards on web"
```

---

### Task 10: Full Regression, Documentation and Deployment Gate

**Files:**
- Modify: `README.md`
- Create: `docs/editorial-pipeline.md`
- Modify: tests only if verification exposes a real regression; every regression fix receives its own commit before this task’s documentation commit.

**Interfaces:**
- Documents operational states and exact audit/recovery behavior.
- Does not change Cloudflare or GitHub schedule times.

- [ ] **Step 1: Document production behavior**

`docs/editorial-pipeline.md` must describe:

- the two stages and module ownership;
- schema v3 fields;
- all rejection codes and scoring weights;
- event-history and successful-send files;
- legal empty versus system failure;
- manual dry-run and persisted-send commands;
- how to inspect `.state/latest_audit.json` without publishing it;
- how to roll back to the last known good commit.

Update README wording from fixed “about 10 stories” to the 5+3+3 maximum and zero-item policy.

- [ ] **Step 2: Run all local verification**

Run:

```bash
pytest -q
cd cloudflare/ai-news-scheduler && npm test
cd ../../web && npm run build && node --test tests/*.test.mjs
git diff --check
```

Expected:

- complete Python suite has zero failures;
- all Worker tests pass;
- web build succeeds;
- all Node tests pass;
- `git diff --check` emits no output.

- [ ] **Step 3: Run deterministic fixture twice**

Run the pipeline twice with the same frozen candidates, source documents, model responses and `now`. Compare the two JSON outputs after removing only generated file paths. Expected: identical scores, fingerprints, board membership, order and rejection reasons.

- [ ] **Step 4: Verify state transitions without live Feishu**

Using a temporary state directory and mocked webhook:

1. published send success creates URL history, event history and the daily ledger;
2. legal empty send success creates only the daily ledger;
3. Feishu failure creates none of those success records;
4. a later dashboard publication failure leaves the successful ledger intact;
5. automatic retry skips after either successful published or successful legal empty delivery.

Expected: all five assertions pass.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md docs/editorial-pipeline.md
git commit -m "Document editorial pipeline operations"
```

- [ ] **Step 6: Review the complete branch before any production change**

Run:

```bash
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git status --short
```

Expected: one short commit per independently testable feature, only intended files changed, and a clean worktree.

Do not push, merge, deploy or trigger `Run workflow` until the user approves this verified branch. After approval, push the branch, review the diff, merge intentionally, use Sites to save and deploy the exact pushed source version, and observe the next automatic run without manually sending a duplicate.
