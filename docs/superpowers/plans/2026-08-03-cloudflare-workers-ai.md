# Cloudflare Workers AI Free Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the retired GitHub Models inference fallback with Cloudflare Workers AI while preserving OpenAI as an explicitly configured, non-automatic paid alternative.

**Architecture:** Extend `Settings` with a Cloudflare credential pair and model, then return Cloudflare's OpenAI-compatible base URL through the existing model-client provider. Keep structured Chat Completions for compatible providers and Responses for OpenAI. Inject secrets in GitHub Actions, add a one-request no-send smoke validator, and remove obsolete GitHub Models setup instructions.

**Tech Stack:** Python 3.12, Pydantic 2, OpenAI Python SDK 2.x, pytest 8, GitHub Actions, Cloudflare Workers AI OpenAI-compatible API.

## Global Constraints

- Production baseline is the current `origin/main`; all work stays on `codex/cloudflare-workers-ai` until reviewed.
- Cloudflare Workers AI is selected only when both `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_AI_API_TOKEN` exist.
- Default Cloudflare model is `@cf/meta/llama-3.1-8b-instruct-fast`.
- OpenAI is selected only when Cloudflare is wholly unconfigured and `OPENAI_API_KEY` exists.
- A partial Cloudflare credential pair is a configuration error and must never silently fall back.
- `GITHUB_TOKEN` remains available for GitHub collection and repository writes but never selects an inference backend.
- No runtime fallback from Cloudflare to a potentially billed OpenAI request.
- Existing evidence gates, dedupe, boards, global-event lane, Feishu output, website output, prompt budgets, and schedules remain unchanged.
- Every production behavior change follows red-green-refactor and ends in a simple Git commit.

---

### Task 1: Cloudflare backend selection and client wiring

**Files:**
- Modify: `tests/test_config.py`
- Modify: `tests/test_cli.py`
- Modify: `src/ai_news_bot/config.py`

**Interfaces:**
- Consumes: `Settings.from_env() -> Settings`; `Settings.ai_backend() -> tuple[str, str, str | None, str]`.
- Produces: settings fields `cloudflare_account_id: str`, `cloudflare_ai_api_token: str`, `cloudflare_ai_model: str`; Cloudflare backend tuple `(token, model, base_url, "Cloudflare Workers AI")`.

- [ ] **Step 1: Write failing configuration tests**

Replace the retired-provider assertions in `tests/test_config.py` with behavior tests equivalent to:

```python
def test_ai_backend_prefers_complete_cloudflare_configuration() -> None:
    settings = Settings(
        cloudflare_account_id="account-123",
        cloudflare_ai_api_token="cf-token",
        openai_api_key="openai-key",
        github_token="github-token",
    )
    assert settings.ai_backend() == (
        "cf-token",
        "@cf/meta/llama-3.1-8b-instruct-fast",
        "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1",
        "Cloudflare Workers AI",
    )


def test_ai_backend_uses_openai_when_cloudflare_is_unconfigured() -> None:
    assert Settings(openai_api_key="openai-key").ai_backend() == (
        "openai-key", "gpt-5.6-luna", None, "OpenAI"
    )


@pytest.mark.parametrize(
    ("account_id", "token"),
    [("account-123", ""), ("", "cf-token")],
)
def test_ai_backend_rejects_partial_cloudflare_configuration(
    account_id: str, token: str
) -> None:
    settings = Settings(
        cloudflare_account_id=account_id,
        cloudflare_ai_api_token=token,
        openai_api_key="openai-key",
    )
    with pytest.raises(ValueError, match="Cloudflare"):
        settings.ai_backend()


def test_github_token_alone_is_not_an_ai_backend() -> None:
    with pytest.raises(ValueError, match="CLOUDFLARE|OPENAI"):
        Settings(github_token="github-token").ai_backend()
```

Add an environment test that sets the three Cloudflare variables and asserts whitespace is stripped and the default/override model is retained exactly.

- [ ] **Step 2: Run configuration tests and confirm the new contract fails**

Run: `python -m pytest tests/test_config.py -q`

Expected: FAIL because the three Cloudflare settings fields do not exist and GitHub Token still selects GitHub Models.

- [ ] **Step 3: Implement the minimal settings behavior**

In `src/ai_news_bot/config.py`, add the three fields, read them in `from_env`, remove `github_models_model` and `github_models_base_url`, and make `ai_backend` follow this exact branch order:

```python
cloudflare_configured = bool(self.cloudflare_account_id)
cloudflare_token_configured = bool(self.cloudflare_ai_api_token)
if cloudflare_configured != cloudflare_token_configured:
    raise ValueError(
        "Cloudflare Workers AI 配置不完整；必须同时设置 "
        "CLOUDFLARE_ACCOUNT_ID 和 CLOUDFLARE_AI_API_TOKEN"
    )
if cloudflare_configured:
    base_url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{self.cloudflare_account_id}/ai/v1"
    )
    return (
        self.cloudflare_ai_api_token,
        self.cloudflare_ai_model,
        base_url,
        "Cloudflare Workers AI",
    )
if self.openai_api_key:
    return self.openai_api_key, self.openai_model, None, "OpenAI"
raise ValueError(
    "缺少 Cloudflare Workers AI 或 OpenAI 凭证；无法执行结构化证据提取"
)
```

- [ ] **Step 4: Run configuration tests and confirm green**

Run: `python -m pytest tests/test_config.py -q`

Expected: all configuration tests PASS.

- [ ] **Step 5: Write a failing production-wiring test**

Update the backend parameterization in `tests/test_cli.py` so the Cloudflare case creates complete Cloudflare settings and expects:

```python
(
    "cloudflare",
    "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1",
    "chat",
    "@cf/meta/llama-3.1-8b-instruct-fast",
)
```

Keep the OpenAI case expecting `base_url=None`, interface `responses`, and model `gpt-5.6-luna`. The test must exercise the real CLI dependency builder while faking only network collection/model responses.

- [ ] **Step 6: Run the wiring test and confirm red**

Run: `python -m pytest tests/test_cli.py::test_production_pipeline_wiring_uses_backend_adapter_and_real_stages -q`

Expected: FAIL until the test fixture supplies the new Cloudflare settings and old GitHub branch assumptions are removed.

- [ ] **Step 7: Make the minimum test-fixture and naming updates**

Update `_settings`/parameter setup without changing the production evidence pipeline. Rename GitHub-specific structured-chat test names in `tests/test_evidence.py` to provider-neutral OpenAI-compatible names; keep their observable assertions on Chat Completions request shape.

- [ ] **Step 8: Run focused backend and extraction tests**

Run: `python -m pytest tests/test_config.py tests/test_cli.py tests/test_evidence.py tests/test_global_editor.py -q`

Expected: PASS with Cloudflare using Chat Completions and OpenAI using Responses.

- [ ] **Step 9: Commit Task 1**

```bash
git add src/ai_news_bot/config.py tests/test_config.py tests/test_cli.py tests/test_evidence.py tests/test_global_editor.py
git commit -m "Add Cloudflare AI backend"
```

---

### Task 2: GitHub Actions injection and no-send provider smoke test

**Files:**
- Create: `scripts/validate_ai_backend.py`
- Create: `tests/test_validate_ai_backend.py`
- Create: `tests/test_daily_workflow.py`
- Modify: `.github/workflows/daily-ai-news.yml`

**Interfaces:**
- Consumes: `Settings.ai_backend()`, `OpenAI(api_key=..., base_url=...)`, `extract_evidence(...)`.
- Produces: `validate_backend(settings: Settings, client_factory: Callable[..., Any] = OpenAI) -> EvidenceRecord`; CLI exit code 0 only after a valid, anchor-verified structured record.

- [ ] **Step 1: Write a failing smoke-validator behavior test**

Create `tests/test_validate_ai_backend.py` with a fake factory that captures `api_key` and `base_url`, returns the repository's existing structured-client test double shape, and asserts that `validate_backend`:

```python
record = validate_backend(settings, client_factory=fake_factory)
assert record.candidate_id == "cloudflare-smoke-test"
assert record.verification_status == "verified"
assert captured == {
    "api_key": "cf-token",
    "base_url": (
        "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1"
    ),
}
```

The synthetic source must contain the literal statement used by the returned evidence anchor so the real `validate_anchors` code executes.

- [ ] **Step 2: Run the smoke-validator test and confirm red**

Run: `python -m pytest tests/test_validate_ai_backend.py -q`

Expected: FAIL because `scripts.validate_ai_backend` does not exist.

- [ ] **Step 3: Implement the one-request validator**

Create a synthetic `Candidate` and `FetchedSource` with ID `cloudflare-smoke-test`, call `settings.ai_backend()`, construct one SDK client, and pass the values into `extract_evidence`. Reject a returned record unless its ID matches, verification status is `verified`, it has at least one concrete change, and it has at least one literal evidence anchor. The script must print only provider/model/success metadata and never print tokens, Account ID, full model payloads, or environment values.

- [ ] **Step 4: Run the validator test and confirm green**

Run: `python -m pytest tests/test_validate_ai_backend.py -q`

Expected: PASS.

- [ ] **Step 5: Write a failing workflow structure test**

Create `tests/test_daily_workflow.py`. Parse `.github/workflows/daily-ai-news.yml` using `yaml.load(..., Loader=yaml.BaseLoader)`, locate the `Generate daily result` step and a new `Validate AI backend without sending` step by name, then assert:

```python
assert generate_env["CLOUDFLARE_ACCOUNT_ID"] == (
    "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
)
assert generate_env["CLOUDFLARE_AI_API_TOKEN"] == (
    "${{ secrets.CLOUDFLARE_AI_API_TOKEN }}"
)
assert generate_env["CLOUDFLARE_AI_MODEL"] == (
    "${{ vars.CLOUDFLARE_AI_MODEL || "
    "'@cf/meta/llama-3.1-8b-instruct-fast' }}"
)
assert "GITHUB_MODELS_MODEL" not in generate_env
assert smoke_step["run"] == "python scripts/validate_ai_backend.py"
```

Also assert the smoke step runs only for manual, non-main branch validation and has no Feishu secrets.

- [ ] **Step 6: Run the workflow test and confirm red**

Run: `python -m pytest tests/test_daily_workflow.py -q`

Expected: FAIL because the workflow still injects GitHub Models and has no smoke step.

- [ ] **Step 7: Implement workflow injection and validation step**

In `.github/workflows/daily-ai-news.yml`:

- Add Cloudflare Account ID, API Token, and default model to `Generate daily result`.
- Remove `GITHUB_MODELS_MODEL`; retain `GITHUB_TOKEN` for GitHub collection.
- Add `Validate AI backend without sending` for `workflow_dispatch` on non-main branches after Python tests and before web validation.
- Give the smoke step only Cloudflare/OpenAI model credentials; do not inject Feishu or site-publishing secrets.

- [ ] **Step 8: Run Task 2 tests**

Run: `python -m pytest tests/test_validate_ai_backend.py tests/test_daily_workflow.py -q`

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git add .github/workflows/daily-ai-news.yml scripts/validate_ai_backend.py tests/test_validate_ai_backend.py tests/test_daily_workflow.py
git commit -m "Validate Cloudflare AI in Actions"
```

---

### Task 3: Operator configuration and retired-provider cleanup

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `outputs/AI新闻Bot-交付说明.md`

**Interfaces:**
- Consumes: repository operator setup flow.
- Produces: exact secret names, default model, token permission guidance, provider priority, and validation instructions matching Tasks 1-2.

- [ ] **Step 1: Update `.env.example`**

Place Cloudflare first and include:

```dotenv
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_AI_API_TOKEN=
CLOUDFLARE_AI_MODEL=@cf/meta/llama-3.1-8b-instruct-fast
```

Keep `OPENAI_API_KEY`/`OPENAI_MODEL` under an optional paid-alternative comment. Remove `GITHUB_MODELS_MODEL` and `GITHUB_MODELS_BASE_URL`; retain `GITHUB_TOKEN` as a GitHub collection credential.

- [ ] **Step 2: Update README and delivery guide**

Document Cloudflare dashboard steps: obtain Account ID, create a least-privilege Workers AI token, save both values as GitHub Actions Repository Secrets, optionally set `CLOUDFLARE_AI_MODEL` as a Repository Variable, and manually run the feature branch once for the no-send validator. State that ChatGPT/Copilot subscriptions do not provide OpenAI API credits and that no provider can promise permanent free allocation.

- [ ] **Step 3: Check obsolete operator claims are gone**

Run:

```bash
rg -n "GitHub Models|GITHUB_MODELS_MODEL|GITHUB_MODELS_BASE_URL|未配置.*OPENAI.*GITHUB" .env.example README.md outputs src tests .github
```

Expected: no active configuration or documentation claims remain; provider-neutral historical test fixture URLs are allowed only where explicitly testing generic compatible adapters, otherwise rename them.

- [ ] **Step 4: Run complete Python regression suite**

Run: `python -m pytest -q`

Expected: all tests PASS with zero failures.

- [ ] **Step 5: Run complete web regression suite**

Run: `npm ci && npm run lint && npm test` from `web/`.

Expected: install, lint, and rendered/dashboard tests all exit 0.

- [ ] **Step 6: Commit Task 3**

```bash
git add .env.example README.md outputs/AI新闻Bot-交付说明.md
git commit -m "Document Cloudflare AI setup"
```

---

### Task 4: Final verification and branch handoff

**Files:**
- Verify only; modify files only if a failing test identifies a real defect, following a fresh red-green cycle.

**Interfaces:**
- Consumes: all Task 1-3 commits.
- Produces: a pushed review branch and evidence needed before merging.

- [ ] **Step 1: Confirm clean diff and intended commit scope**

Run: `git status --short --branch && git log --oneline origin/main..HEAD && git diff --check origin/main...HEAD`

Expected: only the migration commits are present, working tree clean, and no whitespace errors.

- [ ] **Step 2: Run final fresh verification**

Run: `python -m pytest -q`

Run from `web/`: `npm run lint && npm test`

Expected: every command exits 0 in this step's fresh output.

- [ ] **Step 3: Push the isolated branch**

Run: `git push -u origin codex/cloudflare-workers-ai`

- [ ] **Step 4: Configure secrets and run no-send validation**

After the user stores `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_AI_API_TOKEN`, manually dispatch `Daily AI News` on `codex/cloudflare-workers-ai`. Confirm `Validate AI backend without sending` succeeds and that all Feishu delivery/persist/publish steps remain skipped on the branch.

- [ ] **Step 5: Recommend merge only with live evidence**

Report the run URL, provider/model, test counts, three commit messages, and any Cloudflare quota/model limitation observed. Do not merge to `main` or trigger a production send until the user explicitly approves after this report.
