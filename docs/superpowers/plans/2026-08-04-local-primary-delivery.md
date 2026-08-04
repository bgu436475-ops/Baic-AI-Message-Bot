# Local Primary Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one Chinese AI-news digest from the always-on Mac at 09:05 Asia/Shanghai using Ollama, with no automatic cloud Feishu sender.

**Architecture:** Add explicit primary-local mode to the existing runner. It keeps preflight, grounded editorial validation, local ledgers and uncertain-delivery handling, but bypasses cloud observation and the 09:50 delay. A LaunchAgent invokes that mode at 09:05. GitHub remains a manual no-send diagnostics workflow.

**Tech Stack:** Python 3.12, Pydantic, pytest, macOS launchd, Ollama loopback API, GitHub Actions YAML.

## Global Constraints

- Use only `AI_BACKEND=ollama` at `http://127.0.0.1:11434/v1` with preinstalled `qwen3:8b`.
- Preserve the protected local environment and never expose secrets in logs, Git, arguments or artifacts.
- Keep uncertain-delivery, local lock and local send-ledger protections.
- Each independently verifiable task is committed.

---

### Task 1: Add primary-local execution mode

**Files:**
- Modify: `src/ai_news_bot/local_fallback.py`
- Modify: `tests/test_local_fallback.py`

**Interfaces:**
- Add `LocalFallbackConfig.primary_mode: bool = False`.
- Add `--primary-scheduled`, which sets `scheduled=True` and `primary_mode=True`.
- Continue using `run_local_fallback(config, dependencies) -> int`.

- [ ] **Step 1: Write failing tests**

```python
def test_primary_mode_sends_at_0905_without_cloud_gate():
    config = make_config(primary_mode=True, scheduled=True)
    dependencies = make_dependencies(now=shanghai_datetime(9, 5))

    assert run_local_fallback(config, dependencies) == 0
    assert dependencies.cloud_gate_calls == 0
    assert dependencies.send_calls == 1
```

- [ ] **Step 2: Verify the new test fails**

Run: `PYTHONPATH="$PWD" .venv/bin/pytest -q tests/test_local_fallback.py -k primary_mode`

Expected: FAIL because `primary_mode` does not exist.

- [ ] **Step 3: Implement the minimal branch**

```python
def _local_delivery_allowed(config, dependencies, day):
    if config.primary_mode:
        return True, 0
    return _cloud_allows_local(dependencies, day)
```

Use this helper for all three existing cloud checks. Skip the cloud schedule window only in primary mode. Keep preflight, model, digest, Feishu and ledger paths intact.

- [ ] **Step 4: Verify task tests**

Run: `PYTHONPATH="$PWD" .venv/bin/pytest -q tests/test_local_fallback.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_news_bot/local_fallback.py tests/test_local_fallback.py
git commit -m "Run local news bot as primary"
```

### Task 2: Install a 09:05 primary LaunchAgent

**Files:**
- Modify: `local-fallback/com.baic.ai-news-bot.local-fallback.plist.template`
- Modify: `tests/test_local_installer.py`
- Modify: `docs/local-ollama-fallback-operations.md`

**Interfaces:**
- The rendered plist contains `--primary-scheduled` and `StartCalendarInterval` 09:05.
- Existing installer activation flags remain required.

- [ ] **Step 1: Write failing test**

```python
def test_launch_agent_runs_primary_mode_at_0905(tmp_path):
    rendered = render_launch_agent(context(tmp_path)).decode()

    assert "--primary-scheduled" in rendered
    assert "<integer>5</integer>" in rendered
    assert "--scheduled" not in rendered
```

- [ ] **Step 2: Verify the test fails**

Run: `PYTHONPATH="$PWD" .venv/bin/pytest -q tests/test_local_installer.py -k primary_mode`

Expected: FAIL because the template uses `--scheduled` at 09:35.

- [ ] **Step 3: Update the template and guide**

Use:

```xml
<string>--primary-scheduled</string>
<key>Minute</key>
<integer>5</integer>
```

Document that local generation/sending is primary and Cloudflare/GitHub do not send automatically. Do not add a force-send control.

- [ ] **Step 4: Verify task tests and plist syntax**

Run: `PYTHONPATH="$PWD" .venv/bin/pytest -q tests/test_local_installer.py && plutil -lint local-fallback/com.baic.ai-news-bot.local-fallback.plist.template`

Expected: PASS and `OK`.

- [ ] **Step 5: Commit**

```bash
git add local-fallback/com.baic.ai-news-bot.local-fallback.plist.template tests/test_local_installer.py docs/local-ollama-fallback-operations.md
git commit -m "Schedule local primary delivery at 0905"
```

### Task 3: Disable automatic cloud sending

**Files:**
- Modify: `.github/workflows/daily-ai-news.yml`
- Modify: `tests/test_daily_workflow.py`
- Modify: `README.md`

**Interfaces:**
- Daily workflow accepts only `workflow_dispatch`.
- It contains validation and preview steps only, never model generation or Feishu send steps.

- [ ] **Step 1: Write failing test**

```python
def test_daily_workflow_is_manual_no_send_diagnostics_only():
    workflow = load_workflow()

    assert workflow[True] == {"workflow_dispatch": None}
    assert "Generate daily result" not in step_names(workflow)
    assert "Send persisted daily result" not in step_names(workflow)
```

- [ ] **Step 2: Verify test fails**

Run: `PYTHONPATH="$PWD" .venv/bin/pytest -q tests/test_daily_workflow.py -k manual_no_send`

Expected: FAIL because schedules and sender steps are still present.

- [ ] **Step 3: Make the workflow manual diagnostics only**

Set its trigger to `workflow_dispatch`. Retain checkout, test, backend validation, preview, web validation and artifact upload for non-main branches. Remove cloud generation, Feishu send, persistence, dashboard publication and cache save steps.

- [ ] **Step 4: Verify workflow tests**

Run: `PYTHONPATH="$PWD" .venv/bin/pytest -q tests/test_daily_workflow.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/daily-ai-news.yml tests/test_daily_workflow.py README.md
git commit -m "Disable cloud AI news delivery"
```

### Task 4: Verify and install

**Files:**
- No source changes expected.

- [ ] **Step 1: Run full repository tests**

Run: `PYTHONPATH="$PWD" .venv/bin/pytest -q`

Expected: PASS.

- [ ] **Step 2: Push tested branch**

Run: `git push origin codex/local-ollama-fallback`

Expected: remote branch is current; automatic workflow scheduling is absent.

- [ ] **Step 3: Refresh runtime without activation**

Run: `.venv/bin/python scripts/install_local_fallback.py --repo-root "$PWD" --gh-path "$HOME/Library/Application Support/Baic-AI-Message-Bot/bin/gh" --repository bgu436475-ops/Baic-AI-Message-Bot`

Expected: protected `.env` remains present and no LaunchAgent loads.

- [ ] **Step 4: Run real local no-send smoke validation**

Run: `~/Library/Application\ Support/Baic-AI-Message-Bot/venv/bin/python -m ai_news_bot.local_fallback --runtime-root ~/Library/Application\ Support/Baic-AI-Message-Bot --env-path ~/Library/Application\ Support/Baic-AI-Message-Bot/.env --gh-path ~/Library/Application\ Support/Baic-AI-Message-Bot/bin/gh --ollama-app-path ~/Applications/Ollama.app --repository bgu436475-ops/Baic-AI-Message-Bot --check-only --primary-scheduled`

Expected: exit 0 with no Feishu request.

- [ ] **Step 5: Obtain separate approval before activation or any live Feishu send**

Activation remains: `.venv/bin/python scripts/install_local_fallback.py --repo-root "$PWD" --gh-path "$HOME/Library/Application Support/Baic-AI-Message-Bot/bin/gh" --repository bgu436475-ops/Baic-AI-Message-Bot --smoke-validated --activate-schedule`.

