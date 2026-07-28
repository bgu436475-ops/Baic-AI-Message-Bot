# Grounded Action Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate conservative, auditable actions from verified structured
changes without allowing missing evidence to bypass editorial gates.

**Architecture:** Add a focused `action_editor` module between provenance
binding and gate evaluation. It replaces model-authored actions with one
deterministic action derived from the first concrete change, affected audience,
affected area, change type, and action horizon.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest.

## Global Constraints

- Do not add another model request.
- Do not invent facts, numbers, versions, dates, entities, or conclusions.
- Missing change, audience, or affected area must still fail the hard gates.
- Invalid evidence and unverified primary sources must remain ineligible.
- Do not trigger or resend today's Feishu digest.

---

### Task 1: Define the deterministic action editor

**Files:**
- Create: `src/ai_news_bot/action_editor.py`
- Create: `tests/test_action_editor.py`

**Interfaces:**
- Consumes: `EvidenceRecord`.
- Produces: `derive_recommended_action(record: EvidenceRecord) -> EvidenceRecord`.

- [ ] Write failing tests for pricing, release, policy, benchmark, repository,
  generic changes, action horizons, replacement of model-authored actions, and
  missing required inputs.
- [ ] Run the new test module and confirm RED because the module is absent.
- [ ] Implement the smallest deterministic templates that satisfy the tests.
- [ ] Run the new test module and confirm GREEN.

### Task 2: Integrate before hard gates

**Files:**
- Modify: `src/ai_news_bot/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: provenance-bound and anchor-validated `EvidenceRecord`.
- Produces: action-edited record passed to sanitization and hard gates.

- [ ] Write a failing pipeline test where an otherwise eligible record has an
  empty action and must be published after action editing.
- [ ] Write a guard test showing invalid evidence still cannot publish.
- [ ] Run the focused tests and confirm RED.
- [ ] Call `derive_recommended_action` before `_sanitize_record`.
- [ ] Run pipeline and gate tests and confirm GREEN.

### Task 3: Verify and publish

**Files:**
- Modify: the files listed above and the approved design documentation.

**Interfaces:**
- Produces: one implementation commit on `main`.

- [ ] Run action editor, pipeline, gatekeeper, scoring, Feishu, and web export
  tests.
- [ ] Run the full Python test suite.
- [ ] Run syntax compilation and `git diff --check`.
- [ ] Commit with a short message and push `main`.
- [ ] Do not dispatch the workflow today.
