# Pipeline Delivery Review Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining delivery-security, fallback-selection,
configuration, and workflow-concurrency review gaps.

**Architecture:** Keep egress normalization at the pipeline boundary and URL
credential stripping in the shared URL sanitizer. Merge fallback candidates
with shortlist-qualified candidates ahead of recency-only candidates while
retaining the hard cap. Remove dead count configuration and use one
non-cancelling workflow concurrency group for every trigger.

**Tech Stack:** Python 3.12, Pydantic 2, pytest, GitHub Actions YAML.

## Global Constraints

- Use strict red-green-refactor TDD for every behavior change.
- Public digest and private audit output must not contain model/source secrets.
- Candidate input to the editorial pipeline must never exceed 80.
- Manual dispatch bypasses the daily-send guard but all workflow runs serialize.
- Make one commit named `Close pipeline delivery review gaps`.
- Do not push, access the network, call Feishu, or dispatch a workflow.

---

### Task 1: Close every egress sanitization path

**Files:**
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_source_fetcher.py`
- Modify: `tests/test_boards.py`
- Modify: `src/ai_news_bot/pipeline.py`
- Modify: `src/ai_news_bot/source_fetcher.py`
- Modify: `src/ai_news_bot/boards.py`
- Modify: `src/ai_news_bot/models.py`

**Interfaces:**
- Consumes: `DuplicateAssessment.update_of`, `EvidenceRecord.source_url`.
- Produces: sanitized `EditorialDraft.update_of`, safe evidence/audit URLs, and
  bounded `EditorialNewsItem`/`AuditEntry` fields.

- [ ] **Step 1: Write failing hostile egress tests**

```python
def test_pipeline_redacts_update_links_env_keys_and_path_credentials():
    assessment = DuplicateAssessment(
        status="material_update",
        update_of="ACCESS_TOKEN=raw-secret " + "x" * 2000,
    )
    # Run the real pipeline and real boards, then assert every secret is absent,
    # update_of is at most 500 characters, and public/audit URLs contain
    # REDACTED while retaining their scheme/host/non-secret path context.
```

```python
def test_url_sanitizer_redacts_secret_bearing_path_segments():
    sanitized = _sanitize_url(
        "https://example.com/hooks/access_token/raw-secret/releases"
    )
    assert sanitized == (
        "https://example.com/hooks/access_token/REDACTED/releases"
    )
```

- [ ] **Step 2: Run tests and verify RED**

Run:
`python -m pytest -p no:cacheprovider tests/test_pipeline.py
tests/test_source_fetcher.py tests/test_boards.py -q
-k 'hostile or path or material_update_link'`

Expected: raw `update_of`, underscored key secrets, or path credentials remain.

- [ ] **Step 3: Implement minimal central sanitization**

```python
def _to_item(candidate, board):
    return EditorialNewsItem(
        **candidate.draft.model_dump(),
        board=board,
    )
```

Extend assigned-secret matching to identifier keys ending in `token`,
`secret`, `password`, or `api_key`, sanitize known path credential forms in
`_sanitize_url`, cap `event_fingerprint`, and add Pydantic max-length/list
limits matching pipeline constants so egress invariants are enforced.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:
`python -m pytest -p no:cacheprovider tests/test_pipeline.py
tests/test_source_fetcher.py tests/test_boards.py -q`

Expected: all tests pass with no secret values in serialized public/audit data.

### Task 2: Preserve strong fallback candidates inside hard 80

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/ai_news_bot/cli.py`

**Interfaces:**
- Consumes: current and expanded-lookback `CollectionOutcome.candidates`.
- Produces: `_merge_fallback_candidates(..., now) -> list[Candidate]` with
  shortlist-qualified candidates first, deterministic remainder order, and
  maximum length 80.

- [ ] **Step 1: Write the failing full-run regression**

```python
def test_run_keeps_older_strong_candidate_ahead_of_eighty_current_weak(...):
    # First collection returns 80 recent candidates with no specific signal.
    # Expanded collection returns one older tier-1 API v2 release.
    # Run cli.run with real run_editorial_pipeline and real build_boards.
    assert output.boards.must_read[0].candidate_id == "older-strong"
```

- [ ] **Step 2: Run the test and verify RED**

Run:
`python -m pytest -p no:cacheprovider tests/test_cli.py -q -k older_strong`

Expected: the older strong candidate is missing because recency truncation
keeps the 80 current weak candidates.

- [ ] **Step 3: Implement the quality-first deterministic merge**

```python
def _merge_fallback_candidates(current, older, history, max_candidates, now):
    cap = max(0, min(max_candidates, 80))
    unique = hard_dedupe(
        [item for item in current + older if not history.contains(item.url)]
    )
    priority = shortlist_candidates(unique, now)
    priority_ids = {item.id for item in priority}
    remaining = sorted(
        (item for item in unique if item.id not in priority_ids),
        key=lambda item: (-item.published_at.timestamp(), -item.source_weight, item.id),
    )
    return (priority + remaining)[:cap]
```

Use this helper only after fallback collection; retain `_prepare_candidates`
for initial collection and keep `fallback_used` behavior unchanged.

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run: `python -m pytest -p no:cacheprovider tests/test_cli.py -q`

Expected: the older strong candidate reaches the real shortlist and board,
input remains at most 80, and ordering is deterministic.

### Task 3: Remove dead target-count configuration

**Files:**
- Modify: `tests/test_config.py`
- Modify: `tests/test_cli.py`
- Modify: `src/ai_news_bot/config.py`
- Modify: `README.md`

**Interfaces:**
- Removes: `Settings.target_news_count` and `TARGET_NEWS_COUNT`.
- Preserves: CLI rejection of the already-removed `--target-count`.

- [ ] **Step 1: Write the failing absence test**

```python
def test_settings_has_no_legacy_target_news_count(monkeypatch):
    monkeypatch.setenv("TARGET_NEWS_COUNT", "3")
    settings = Settings.from_env()
    assert "target_news_count" not in Settings.model_fields
    assert "target_news_count" not in settings.model_dump()
```

- [ ] **Step 2: Run the test and verify RED**

Run:
`python -m pytest -p no:cacheprovider tests/test_config.py -q -k target_news`

Expected: the field is still present.

- [ ] **Step 3: Remove the setting and documentation**

Delete the Pydantic field, environment read, test helper argument, and README
entry. Keep unknown environment variables harmlessly ignored.

- [ ] **Step 4: Run config and CLI tests and verify GREEN**

Run:
`python -m pytest -p no:cacheprovider tests/test_config.py tests/test_cli.py -q`

Expected: all pass and `rg 'target_news_count|TARGET_NEWS_COUNT'` finds no
repository usage outside historical plans/reports.

### Task 4: Serialize manual and automatic workflow runs

**Files:**
- Modify: `tests/test_daily_guard.py`
- Modify: `.github/workflows/daily-ai-news.yml`

**Interfaces:**
- Produces: one `daily-ai-news` concurrency group with
  `cancel-in-progress: false`.
- Preserves: `workflow_dispatch` guard bypass in `daily_guard`.

- [ ] **Step 1: Tighten the workflow concurrency test**

```python
def test_workflow_serializes_manual_and_automatic_runs():
    workflow = _workflow()
    assert "group: daily-ai-news" in workflow
    assert "github.run_id" not in workflow
    assert "cancel-in-progress: false" in workflow
```

- [ ] **Step 2: Run the workflow tests and verify RED**

Run:
`python -m pytest -p no:cacheprovider tests/test_daily_guard.py -q -k workflow`

Expected: the workflow still assigns each manual run a unique group.

- [ ] **Step 3: Use one non-cancelling group**

```yaml
concurrency:
  group: daily-ai-news
  cancel-in-progress: false
```

- [ ] **Step 4: Run workflow tests and verify GREEN**

Run:
`python -m pytest -p no:cacheprovider tests/test_daily_guard.py -q -k workflow`

Expected: all workflow tests pass while the existing manual guard test still
asserts `workflow_dispatch` returns `true`.

### Task 5: Verify, report, and commit once

**Files:**
- Modify: `.superpowers/sdd/task-7-report.md`

**Interfaces:**
- Produces: one reviewable commit and a complete RED/GREEN evidence record.

- [ ] **Step 1: Run focused and full verification**

Run the focused pipeline/source/boards/CLI/config/guard suite, then
`python -m pytest -p no:cacheprovider -q`, `git diff --check`, and a
line-length scan of all changed source/test files.

- [ ] **Step 2: Append exact results and self-review**

Record RED and GREEN results, final test counts, URL/security reasoning,
fallback ordering, concurrency behavior, and any remaining limitations in
`.superpowers/sdd/task-7-report.md`.

- [ ] **Step 3: Stage only intended files and validate**

Run `git diff --cached --check` and inspect the staged stat/diff. Keep
pre-existing `.superpowers/` artifacts untracked unless explicitly requested.

- [ ] **Step 4: Commit**

Run: `git commit -m "Close pipeline delivery review gaps"`.

- [ ] **Step 5: Report without external actions**

Return the commit SHA, focused/full counts, diff-check status, report path,
and concerns. Do not push or dispatch anything.
