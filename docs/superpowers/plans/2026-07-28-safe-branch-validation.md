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
- Modify: `.github/workflows/daily-ai-news.yml:44-104`
- Modify: `tests/test_daily_guard.py:150-220`

**Interfaces:**
- Consumes: GitHub context values `github.event_name` and `github.ref`.
- Produces: artifact `grounded-action-validation-${{ github.run_id }}` with
  `web/public/data/latest.json` and `.state/latest_audit.json`.

- [ ] **Step 1: Write a failing workflow safety test**

Add a test that asserts the workflow:

```python
def test_branch_validation_is_manual_read_only_and_uploads_artifacts() -> None:
    workflow = _workflow()
    send_step = workflow[
        workflow.index("- name: Send persisted daily result") :
        workflow.index("- name: Persist latest web digest")
    ]

    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert (
        "github.ref == 'refs/heads/codex/validate-grounded-action-editor'"
        in workflow
    )
    assert "github.ref == 'refs/heads/main'" in send_step
    assert "uses: actions/upload-artifact@v6" in workflow
    assert "web/public/data/latest.json" in workflow
    assert ".state/latest_audit.json" in workflow
```

- [ ] **Step 2: Run the test and confirm RED**

Run:

```bash
PYTHONPATH=src /private/tmp/Baic-AI-Message-Bot-fix-20260728/.venv312/bin/python \
  -m pytest -p no:cacheprovider -q \
  tests/test_daily_guard.py::test_branch_validation_is_manual_read_only_and_uploads_artifacts
```

Expected: fail because the workflow has no branch-scoped artifact path and the
send step is not restricted to `main`.

- [ ] **Step 3: Implement the minimal safe workflow**

Update `Generate daily result` so it runs when either the daily guard permits a
normal `main` run or the event is a manual dispatch on the validation branch.
Restrict `Send persisted daily result` to `refs/heads/main`. Add an artifact
upload step with:

```yaml
- name: Upload validation artifacts
  if: >-
    github.event_name == 'workflow_dispatch' &&
    github.ref == 'refs/heads/codex/validate-grounded-action-editor' &&
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

Give the generation step `id: generate_digest`. Keep persistence, dashboard
publication, and state cache saving dependent on successful `send_digest`, so
they remain skipped during validation.

- [ ] **Step 4: Run focused and full tests**

Run:

```bash
PYTHONPATH=src /private/tmp/Baic-AI-Message-Bot-fix-20260728/.venv312/bin/python \
  -m pytest -p no:cacheprovider -q tests/test_daily_guard.py
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
