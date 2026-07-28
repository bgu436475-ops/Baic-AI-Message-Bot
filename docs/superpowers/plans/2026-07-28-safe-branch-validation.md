# Safe Branch Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the real AI news generation pipeline on an isolated GitHub
branch without sending Feishu messages or mutating production data.

**Architecture:** Add a branch-scoped manual validation path to the existing
workflow. The path reuses installation and `ai-news-bot --dry-run`, prevents
all external write steps outside `main`, and uploads the generated digest and
private audit as a short-lived artifact for inspection.

**Tech Stack:** GitHub Actions YAML, Python 3.12, pytest, GitHub artifact
storage.

## Global Constraints

- Do not change or merge `main`.
- Do not send a Feishu message.
- Do not commit or push the generated digest.
- Do not publish the generated digest to the private dashboard.
- Trigger validation only with `workflow_dispatch` on
  `codex/validate-grounded-action-editor`.
- Preserve the 09:05 and 09:20 schedules for `main`.

---

### Task 1: Add a safe manual validation path

**Files:**
- Create: `src/ai_news_bot/workflow_mode.py`
- Create: `tests/test_workflow_mode.py`
- Modify: `.github/workflows/daily-ai-news.yml:44-104`

**Interfaces:**
- Consumes: GitHub context values `github.event_name` and `github.ref`.
- Produces: `WorkflowMode(is_validation: bool, allow_delivery: bool)` and
  GitHub step outputs with the same booleans.
- Produces: artifact `grounded-action-validation-${{ github.run_id }}` with
  `web/public/data/latest.json` and `.state/latest_audit.json`.

- [x] **Step 1: Write failing workflow-mode tests**

Add tests that exercise the real mode decision:

```python
def test_manual_validation_branch_cannot_deliver() -> None:
    mode = resolve_workflow_mode(
        "workflow_dispatch",
        "refs/heads/codex/validate-grounded-action-editor",
    )

    assert mode.is_validation is True
    assert mode.allow_delivery is False


def test_main_automatic_run_can_deliver() -> None:
    mode = resolve_workflow_mode("schedule", "refs/heads/main")

    assert mode.is_validation is False
    assert mode.allow_delivery is True


def test_other_branch_cannot_generate_or_deliver() -> None:
    mode = resolve_workflow_mode(
        "workflow_dispatch",
        "refs/heads/untrusted",
    )

    assert mode.is_validation is False
    assert mode.allow_delivery is False
```

- [x] **Step 2: Run the test and confirm RED**

Run:

```bash
PYTHONPATH=src /private/tmp/Baic-AI-Message-Bot-fix-20260728/.venv312/bin/python \
  -m pytest -p no:cacheprovider -q \
  tests/test_workflow_mode.py
```

Expected: collection error because `ai_news_bot.workflow_mode` does not exist.

- [x] **Step 3: Implement the tested mode resolver and safe workflow**

Create `resolve_workflow_mode(event_name: str, ref: str) -> WorkflowMode` and
a module CLI that prints these GitHub output lines:

```text
is_validation=true
allow_delivery=false
```

The module must return `allow_delivery=True` only for
`refs/heads/main`. It must return `is_validation=True` only for a
`workflow_dispatch` event on
`refs/heads/codex/validate-grounded-action-editor`.

Update `Generate daily result` so it runs when either the daily guard permits a
normal `main` run with `allow_delivery=true`, or the resolved mode has
`is_validation=true`. Restrict `Send persisted daily result` to
`allow_delivery=true`. Add an artifact upload step with:

```yaml
- name: Upload validation artifacts
  if: >-
    steps.workflow_mode.outputs.is_validation == 'true' &&
    steps.generate_digest.outcome == 'success'
  uses: actions/upload-artifact@v6
  with:
    name: grounded-action-validation-${{ github.run_id }}
    path: |
      web/public/data/latest.json
      .state/latest_audit.json
    if-no-files-found: error
    retention-days: 7
```

Give the mode step `id: workflow_mode` and the generation step
`id: generate_digest`. Keep persistence, dashboard publication, and state
cache saving dependent on successful `send_digest`, so they remain skipped
during validation.

- [x] **Step 4: Run focused and full tests**

Run:

```bash
PYTHONPATH=src /private/tmp/Baic-AI-Message-Bot-fix-20260728/.venv312/bin/python \
  -m pytest -p no:cacheprovider -q \
  tests/test_workflow_mode.py tests/test_daily_guard.py
```

Then run:

```bash
PYTHONPATH=src /private/tmp/Baic-AI-Message-Bot-fix-20260728/.venv312/bin/python \
  -m pytest -p no:cacheprovider -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit and push the validation branch**

Stage only the workflow, workflow test, plan, and any approved specification
cleanup. Commit:

```bash
git commit -m "Add safe branch validation"
```

Push:

```bash
git push -u origin codex/validate-grounded-action-editor
```

- [ ] **Step 6: Trigger and inspect the branch run**

From the GitHub Actions `Daily AI News` page, choose
`codex/validate-grounded-action-editor` and click `Run workflow`. Confirm the
event is `workflow_dispatch` and the ref is the validation branch.

After completion:

- Confirm `Generate daily result` succeeded.
- Confirm `Send persisted daily result`, Git persistence, dashboard publish,
  and delivery-state save were skipped.
- Inspect the artifact and confirm schema v3 field consistency.
- For a published digest, confirm every selected item has a grounded
  `recommended_action` containing `依据：`.
