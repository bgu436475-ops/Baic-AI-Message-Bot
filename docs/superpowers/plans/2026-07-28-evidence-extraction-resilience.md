# Evidence Extraction Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Prevent oversized or malformed individual sources from stopping the
daily AI news digest while preserving a hard failure when every extraction
fails.

**Architecture:** Build evidence prompts through one token-budgeted helper.
Retry payload-limit failures with a smaller excerpt. At the pipeline boundary,
convert per-candidate extraction failures into auditable rejection entries and
continue, but re-raise a system failure when no fetched candidate can be
extracted.

**Tech Stack:** Python 3.11+, OpenAI Python SDK, Pydantic 2, pytest.

## Global Constraints

- Do not change Cloudflare, GitHub Actions schedules, Feishu secrets, or webhook
  configuration.
- Keep the GitHub Models request safely below the 8,000-token request limit.
- Every behavior change must follow RED-GREEN TDD.
- A single failed candidate must be auditable as
  `evidence_extraction_failed`.
- If all fetched candidates fail extraction, the pipeline must fail.

---

### Task 1: Bound and shrink evidence prompts

**Files:**
- Modify: `tests/test_evidence.py`
- Modify: `src/ai_news_bot/evidence.py`

**Interfaces:**
- Produces: token-estimated prompt construction for `extract_evidence`.
- Preserves: the existing `extract_evidence(...) -> EvidenceRecord` API.

- [ ] Add a test proving a 30,000-character multilingual source is bounded
  before the first model request.
- [ ] Add a test proving a 413/token-limit response causes the second request
  to contain a smaller `source_text`.
- [ ] Run both tests and confirm they fail on the current implementation.
- [ ] Implement conservative token estimation, prompt budgeting, and the
  smaller payload-limit retry.
- [ ] Run `tests/test_evidence.py` and confirm it passes.

### Task 2: Isolate per-candidate extraction failures

**Files:**
- Modify: `tests/test_pipeline.py`
- Modify: `src/ai_news_bot/models.py`
- Modify: `src/ai_news_bot/pipeline.py`

**Interfaces:**
- Adds: rejection code `evidence_extraction_failed`.
- Produces: an `AuditEntry` for each failed extraction.
- Preserves: a raised `EvidenceExtractionError` if every extraction fails.

- [ ] Add a test proving one failed extraction is rejected while another
  candidate is published.
- [ ] Add a test proving all extraction failures still fail the pipeline.
- [ ] Run both tests and confirm they fail on the current implementation.
- [ ] Catch controlled extraction failures per candidate, append a bounded
  audit rejection, and continue.
- [ ] Run `tests/test_pipeline.py` and confirm it passes.

### Task 3: Verify and publish

**Files:**
- Modify: the files listed above only.

**Interfaces:**
- Produces: one reviewed commit on `main`.

- [ ] Run the focused evidence and pipeline tests.
- [ ] Run the full Python test suite.
- [ ] Run `git diff --check` and inspect the final diff.
- [ ] Commit with a simple bug-fix message.
- [ ] Push `main`, then manually run today's workflow once and verify the
  remote digest date and workflow conclusion.
