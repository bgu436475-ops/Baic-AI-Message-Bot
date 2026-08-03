# Local Ollama Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a macOS fallback that checks whether the Beijing-date cloud digest was delivered, then uses local Ollama `qwen3:8b` to generate and send exactly one validated Feishu digest when the cloud path failed.

**Architecture:** Extend the existing structured-model boundary with an explicit loopback-only Ollama backend. A pure cloud-state evaluator and a thin authenticated `gh` client decide whether local work is allowed; a local orchestrator performs preflight, two delivery gates, persisted generation, typed Feishu delivery, local state, and remote ledger synchronization. An idempotent installer provisions a user-local Ollama app, virtual environment, LaunchAgent, protected environment file, logs, state, and Desktop controls.

**Tech Stack:** Python 3.11+, Pydantic 2, OpenAI Python SDK 2, requests, pytest 8, GitHub CLI, GitHub Actions, macOS launchd, Ollama, `qwen3:8b`.

## Global Constraints

- Production Cloudflare/GitHub behavior remains unchanged unless `AI_BACKEND=ollama` is explicitly set locally.
- Ollama requests accept only `http://localhost`, `http://127.0.0.1`, or `http://[::1]` with the `/v1` API path; remote model endpoints are rejected.
- The scheduled time is 09:35 in the Mac system timezone, and automatic execution fails closed unless `/etc/localtime` resolves to `Asia/Shanghai`.
- The runner waits for queued or active cloud work until 09:50, rechecking once per minute.
- A successful `Send persisted daily result` step or a schema-valid Beijing-date remote digest blocks local sending even when the overall cloud run failed.
- Missing/ambiguous GitHub state, model failures, malformed data, invalid credentials, insufficient disk, or clock drift greater than five minutes never trigger a send.
- The runner executes the existing source, evidence-anchor, hard-gate, scoring, 7-day deduplication, schema-v4, and valid-empty-board rules without weakening them.
- Feishu timeouts or indeterminate 2xx responses become `uncertain_delivery` and block automatic retries for that date.
- Secrets never appear in Git, process arguments, logs, notifications, request/response bodies, or GitHub dispatch payloads.
- The first real Feishu send is performed only after a separate explicit user approval.
- Every task uses red-green TDD, passes its focused tests, and ends in its own Git commit.

## File Structure

- `src/ai_news_bot/model_backend.py`: provider specification, loopback validation, client construction, and structured-chat request options.
- `src/ai_news_bot/config.py`: environment parsing and explicit provider selection.
- `src/ai_news_bot/evidence.py`, `src/ai_news_bot/global_editor.py`, `src/ai_news_bot/cli.py`: consume the provider specification without changing editorial rules.
- `src/ai_news_bot/feishu.py`: typed definite and uncertain delivery failures.
- `src/ai_news_bot/send_ledger.py`: record a verified day directly for cloud synchronization.
- `src/ai_news_bot/local_gate.py`: GitHub CLI boundary plus pure cloud-delivery decision logic.
- `src/ai_news_bot/local_state.py`: atomic local fallback status and exclusive run lock.
- `src/ai_news_bot/local_fallback.py`: scheduled/manual orchestration, preflight, generation, second gate, send, sync, notification, and retention.
- `src/ai_news_bot/record_local_delivery.py`: validates repository-dispatch metadata and records cloud delivery state.
- `.github/workflows/record-local-delivery.yml`: serialized state-only workflow; never generates or sends.
- `scripts/install_ollama_macos.py`: user-local notarized Ollama app installation and model pull.
- `scripts/install_local_fallback.py`: runtime, venv, environment, LaunchAgent, and Desktop installation.
- `scripts/uninstall_local_fallback.py`: safe scheduler/Desktop rollback while preserving state and secrets.
- `local-fallback/com.baic.ai-news-bot.local-fallback.plist.template`: LaunchAgent template.
- `local-fallback/run-now.command.template`, `local-fallback/view-logs.command.template`: Desktop templates.
- `tests/test_model_backend.py`, `tests/test_local_gate.py`, `tests/test_local_state.py`, `tests/test_local_fallback.py`, `tests/test_record_local_delivery.py`, `tests/test_local_installer.py`: new focused coverage.
- Existing related tests are extended rather than replaced.

---

### Task 1: Explicit loopback-only Ollama backend

**Files:**
- Create: `src/ai_news_bot/model_backend.py`
- Create: `tests/test_model_backend.py`
- Modify: `src/ai_news_bot/config.py`
- Modify: `src/ai_news_bot/cli.py`
- Modify: `src/ai_news_bot/evidence.py`
- Modify: `src/ai_news_bot/global_editor.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_evidence.py`
- Modify: `tests/test_global_editor.py`
- Modify: `tests/test_cli.py`
- Modify: `scripts/validate_ai_backend.py`
- Modify: `tests/test_validate_ai_backend.py`

**Interfaces:**
- Produces: `BackendSpec`, `Settings.ai_backend() -> BackendSpec`, and `structured_chat_parse(client, backend, messages, response_format, max_tokens) -> BaseModel | None`.
- Consumes: existing Pydantic response models and `OpenAI` client.

- [ ] **Step 1: Write failing backend-selection and URL tests**

```python
def test_explicit_ollama_ignores_cloud_credentials() -> None:
    settings = Settings(
        ai_backend_name="ollama",
        ollama_base_url="http://127.0.0.1:11434/v1",
        ollama_model="qwen3:8b",
        cloudflare_account_id="wrong-cloud-account",
        cloudflare_ai_api_token="cloud-token",
    )
    backend = settings.ai_backend()
    assert backend.provider_id == "ollama"
    assert backend.api_key == "ollama"
    assert backend.model == "qwen3:8b"
    assert backend.base_url == "http://127.0.0.1:11434/v1"
    assert backend.chat_options == {"temperature": 0, "extra_body": {"think": False}}


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://192.168.1.5:11434/v1",
        "http://user:pass@127.0.0.1:11434/v1",
        "http://127.0.0.1:11434/v1?token=secret",
        "http://127.0.0.1:11434/api",
    ],
)
def test_ollama_rejects_non_loopback_or_malformed_urls(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        Settings(ai_backend_name="ollama", ollama_base_url=url).ai_backend()
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_model_backend.py tests/test_config.py -q`

Expected: FAIL because `ai_backend_name`, Ollama settings, and `BackendSpec` do not exist.

- [ ] **Step 3: Implement the provider specification and explicit selection**

```python
@dataclass(frozen=True)
class BackendSpec:
    provider_id: Literal["cloudflare", "openai", "ollama"]
    provider_label: str
    api_key: str
    model: str
    base_url: str | None
    chat_options: dict[str, Any] = field(default_factory=dict)


def normalize_ollama_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {
        "localhost", "127.0.0.1", "::1"
    }:
        raise ValueError("Ollama base URL must use loopback HTTP")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Ollama loopback URL cannot contain credentials or query data")
    if parsed.path.rstrip("/") != "/v1":
        raise ValueError("Ollama loopback URL must end with /v1")
    return value.rstrip("/")
```

Add `AI_BACKEND`, `OLLAMA_BASE_URL`, and `OLLAMA_MODEL` parsing to `Settings.from_env()`. Unset `AI_BACKEND` preserves the current Cloudflare-then-OpenAI selection; explicit values select only that provider and never silently fall through.

- [ ] **Step 4: Write failing structured-request tests**

```python
def test_ollama_structured_parse_disables_thinking() -> None:
    client = FakeStructuredClient([valid_record()])
    backend = BackendSpec(
        provider_id="ollama",
        provider_label="Ollama",
        api_key="ollama",
        model="qwen3:8b",
        base_url="http://127.0.0.1:11434/v1",
        chat_options={"temperature": 0, "extra_body": {"think": False}},
    )
    result = extract_evidence(candidate(), fetched(), client, backend)
    assert result.candidate_id == "one"
    request = client.requests[0][1]
    assert request["temperature"] == 0
    assert request["extra_body"] == {"think": False}
    assert request["response_format"] is EvidenceRecord
```

- [ ] **Step 5: Run the structured-request tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_evidence.py tests/test_global_editor.py tests/test_cli.py tests/test_validate_ai_backend.py -q`

Expected: FAIL because extraction functions still receive separate model/base URL values.

- [ ] **Step 6: Route all structured chat calls through `BackendSpec`**

Implement:

```python
def structured_chat_parse(
    client: Any,
    backend: BackendSpec,
    messages: list[dict[str, str]],
    response_format: type[BaseModel],
    *,
    max_tokens: int,
) -> BaseModel | None:
    response = client.chat.completions.parse(
        model=backend.model,
        messages=messages,
        max_tokens=max_tokens,
        response_format=response_format,
        **backend.chat_options,
    )
    return response.choices[0].message.parsed
```

OpenAI Responses API behavior remains unchanged for `provider_id == "openai"`; Cloudflare and Ollama use structured chat parsing. Update both evidence lanes, the shared client provider, and the smoke validator to consume the same `BackendSpec`.

- [ ] **Step 7: Verify Task 1**

Run: `.venv/bin/python -m pytest tests/test_model_backend.py tests/test_config.py tests/test_evidence.py tests/test_global_editor.py tests/test_cli.py tests/test_validate_ai_backend.py -q`

Expected: PASS with no network calls.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/ai_news_bot/model_backend.py src/ai_news_bot/config.py src/ai_news_bot/cli.py src/ai_news_bot/evidence.py src/ai_news_bot/global_editor.py scripts/validate_ai_backend.py tests/test_model_backend.py tests/test_config.py tests/test_evidence.py tests/test_global_editor.py tests/test_cli.py tests/test_validate_ai_backend.py
git commit -m "Add local Ollama backend"
```

---

### Task 2: Typed Feishu outcomes and direct-day send ledger recording

**Files:**
- Modify: `src/ai_news_bot/feishu.py`
- Modify: `src/ai_news_bot/send_ledger.py`
- Modify: `src/ai_news_bot/cli.py`
- Modify: `tests/test_feishu.py`
- Modify: `tests/test_send_ledger.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `FeishuDeliveryRejected`, `FeishuDeliveryUncertain`, `send_existing_daily_result(web_output, settings) -> EditorialDigest`, and `SendLedger.record_day_success(day, run_status, target, now)`.
- Consumes: existing `EditorialDigest`, Feishu card builder, and atomic ledger writer.

- [ ] **Step 1: Write failing delivery-classification tests**

```python
def test_timeout_is_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout("secret")),
    )
    with pytest.raises(FeishuDeliveryUncertain, match="indeterminate"):
        send_to_feishu(empty_digest(), VALID_WEBHOOK)


def test_nonzero_feishu_code_is_definite_rejection(monkeypatch) -> None:
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(200, {"code": 19001}))
    with pytest.raises(FeishuDeliveryRejected):
        send_to_feishu(empty_digest(), VALID_WEBHOOK)
```

Assert the exception strings never contain response JSON, webhook URLs, signing secrets, or underlying exception messages.

- [ ] **Step 2: Run Feishu tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_feishu.py -q`

Expected: FAIL because the typed exceptions do not exist.

- [ ] **Step 3: Implement safe typed exceptions**

```python
class FeishuDeliveryError(RuntimeError):
    pass


class FeishuDeliveryRejected(FeishuDeliveryError):
    pass


class FeishuDeliveryUncertain(FeishuDeliveryError):
    pass
```

Map `requests.Timeout` and connection loss after request dispatch to `FeishuDeliveryUncertain`; map HTTP responses and parsed nonzero Feishu codes to `FeishuDeliveryRejected`; map invalid JSON after a 2xx response to `FeishuDeliveryUncertain`. Chain no sensitive exception into user-facing logs.

- [ ] **Step 4: Write failing direct-day ledger tests**

```python
def test_record_day_success_creates_cloud_compatible_entry(tmp_path: Path) -> None:
    ledger = SendLedger(tmp_path / "daily_sends.json")
    ledger.record_day_success(
        date(2026, 8, 3),
        run_status="published",
        now=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
    )
    assert ledger.was_sent(date(2026, 8, 3))
```

- [ ] **Step 5: Implement `record_day_success` and extract public send-existing API**

```python
def record_day_success(
    self,
    day: date,
    *,
    run_status: Literal["published", "no_qualifying_items"],
    target: str = "feishu-daily",
    now: datetime | None = None,
) -> None:
    if run_status not in {"published", "no_qualifying_items"}:
        raise ValueError("unsupported successful run status")
    timestamp = now or datetime.now(UTC)
    data = self._load()
    data[f"{day.isoformat()}|{target}"] = {
        "sent_at": timestamp.isoformat(),
        "run_status": run_status,
    }
    self._write(data)


def send_existing_daily_result(
    web_output: Path,
    settings: Settings,
) -> EditorialDigest:
    try:
        digest = EditorialDigest.model_validate_json(
            web_output.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise ValueError("Could not load a valid persisted daily result") from error
    send_to_feishu(
        digest,
        settings.feishu_webhook_url,
        settings.feishu_signing_secret,
        settings.request_timeout,
    )
    SendLedger(settings.send_ledger_path).record_success(digest, "feishu-daily")
    return digest
```

`record_success` delegates to `record_day_success` using the digest date and status. Preserve the existing URL-history and event-history best-effort updates between the success-ledger write and the returned digest.

- [ ] **Step 6: Verify Task 2**

Run: `.venv/bin/python -m pytest tests/test_feishu.py tests/test_send_ledger.py tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/ai_news_bot/feishu.py src/ai_news_bot/send_ledger.py src/ai_news_bot/cli.py tests/test_feishu.py tests/test_send_ledger.py tests/test_cli.py
git commit -m "Classify local delivery outcomes"
```

---

### Task 3: Pure cloud-delivery gate and authenticated GitHub boundary

**Files:**
- Create: `src/ai_news_bot/local_gate.py`
- Create: `tests/test_local_gate.py`

**Interfaces:**
- Produces: `CloudRun`, `RemoteDigestProbe`, `CloudSnapshot`, `CloudGateResult`, `GitHubCLIClient`, `evaluate_cloud_snapshot(day, snapshot)`, and `wait_for_cloud_gate(client, day, deadline, sleep)`.
- Consumes: authenticated `gh`, `EditorialDigest`, and Asia/Shanghai dates.

- [ ] **Step 1: Write failing pure decision tests**

```python
DAY = date(2026, 8, 3)


def run_with(
    *,
    status: str = "completed",
    conclusion: str | None = "failure",
    send_step: str | None = "failure",
) -> CloudRun:
    return CloudRun(
        run_id=1,
        event="repository_dispatch",
        status=status,
        conclusion=conclusion,
        created_at=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        url="https://github.com/o/r/actions/runs/1",
        send_step_conclusion=send_step,
    )


def snapshot(
    runs: tuple[CloudRun, ...],
    digest_status: str = "missing",
    digest: EditorialDigest | None = None,
) -> CloudSnapshot:
    return CloudSnapshot(
        runs=runs,
        remote_digest=RemoteDigestProbe(digest_status, digest),
        server_time=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
    )


def test_successful_send_step_blocks_local_even_if_run_failed() -> None:
    result = evaluate_cloud_snapshot(
        DAY,
        snapshot((run_with(send_step="success"),)),
    )
    assert result.decision == "skip_delivered"


def test_active_run_waits_instead_of_sending() -> None:
    result = evaluate_cloud_snapshot(
        DAY,
        snapshot((run_with(status="in_progress", conclusion=None, send_step=None),)),
    )
    assert result.decision == "wait"


def test_all_completed_failures_allow_local_run() -> None:
    result = evaluate_cloud_snapshot(DAY, snapshot((run_with(),)))
    assert result.decision == "run_local"


def test_malformed_remote_digest_blocks_automatic_send() -> None:
    result = evaluate_cloud_snapshot(
        DAY,
        snapshot((run_with(),), digest_status="malformed"),
    )
    assert result.decision == "blocked"
```

Add table cases for no runs, manual runs, valid empty-board digest, previous-day digest, authentication failure, API uncertainty, and an active run that later succeeds.

- [ ] **Step 2: Run gate tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_local_gate.py -q`

Expected: FAIL because `local_gate` does not exist.

- [ ] **Step 3: Implement immutable boundary types and pure evaluation**

```python
GateDecision = Literal["skip_delivered", "wait", "run_local", "blocked"]


@dataclass(frozen=True)
class CloudRun:
    run_id: int
    event: str
    status: str
    conclusion: str | None
    created_at: datetime
    url: str
    send_step_conclusion: str | None


@dataclass(frozen=True)
class CloudGateResult:
    decision: GateDecision
    reason_code: str
    run_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class RemoteDigestProbe:
    status: Literal["missing", "valid", "malformed", "unavailable"]
    digest: EditorialDigest | None = None


@dataclass(frozen=True)
class CloudSnapshot:
    runs: tuple[CloudRun, ...]
    remote_digest: RemoteDigestProbe
    server_time: datetime
```

Convert every timestamp to Asia/Shanghai before date comparison. Accept a remote digest only by calling `EditorialDigest.model_validate_json` and checking its generated date plus schema-v4 status/content invariants.

- [ ] **Step 4: Write failing GitHub CLI boundary tests**

Use a fake `CommandRunner` returning complete `gh run list`, `gh run view --json jobs`, `gh api -i rate_limit`, and base64 contents responses. Assert:

```python
assert client.snapshot(DAY).runs[0].send_step_conclusion == "success"
assert client.snapshot(DAY).server_time == datetime(2026, 8, 3, 2, 0, tzinfo=UTC)
assert all("token" not in argument.casefold() for call in fake.calls for argument in call)
```

- [ ] **Step 5: Implement `GitHubCLIClient` and bounded polling**

The client constructor is exact:

```python
GitHubCLIClient(
    gh_path: Path,
    repository: str = "bgu436475-ops/Baic-AI-Message-Bot",
    branch: str = "main",
    command_runner: CommandRunner = run_command,
)
```

It passes JSON through stdin for `repository_dispatch` and never passes credentials. `wait_for_cloud_gate` polls only while the decision is `wait`, once per minute, and returns `blocked/cloud_wait_timeout` at 09:50 rather than sending.

- [ ] **Step 6: Verify Task 3**

Run: `.venv/bin/python -m pytest tests/test_local_gate.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/ai_news_bot/local_gate.py tests/test_local_gate.py
git commit -m "Add cloud delivery gate"
```

---

### Task 4: Atomic local state and fallback orchestration

**Files:**
- Create: `src/ai_news_bot/local_state.py`
- Create: `src/ai_news_bot/local_fallback.py`
- Create: `tests/test_local_state.py`
- Create: `tests/test_local_fallback.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `FallbackLedger`, `exclusive_run_lock(path)`, `LocalFallbackConfig`, `LocalFallbackDependencies`, `GitHubStateSyncError`, `run_local_fallback(config, dependencies) -> int`, and console entry point `ai-news-local-fallback`.
- Consumes: Tasks 1–3, existing CLI generation/send functions, Ollama HTTP API, macOS notification command, and local filesystem.

- [ ] **Step 1: Write failing local state tests**

```python
def test_uncertain_delivery_blocks_same_day_retry(tmp_path: Path) -> None:
    ledger = FallbackLedger(tmp_path / "fallback.json")
    ledger.mark_uncertain(DAY, at=NOW)
    assert ledger.blocks_send(DAY)


def test_exclusive_lock_rejects_second_process(tmp_path: Path) -> None:
    with exclusive_run_lock(tmp_path / "run.lock"):
        with pytest.raises(LocalRunAlreadyActive):
            with exclusive_run_lock(tmp_path / "run.lock"):
                pass
```

- [ ] **Step 2: Run state tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_local_state.py -q`

Expected: FAIL because local state does not exist.

- [ ] **Step 3: Implement atomic state and `fcntl.flock` locking**

Persist `LocalDayState(delivery_status, delivery_id, run_status, cloud_sync_pending, dashboard_pending, updated_at)`. `delivery_status` accepts `sent`, `uncertain_delivery`, or `failed`; only `sent` and `uncertain_delivery` block a same-day send. `mark_sent` stores the non-secret delivery ID and sets pending flags, while `mark_sync_complete` and `mark_dashboard_complete` clear only their respective flags. Use same-directory temporary files, `fsync`, `os.replace`, and `LOCK_EX | LOCK_NB`.

- [ ] **Step 4: Write failing orchestration matrix tests**

```python
def test_cloud_success_never_calls_generate_or_send(deps, config) -> None:
    deps.cloud_gate.return_value = CloudGateResult("skip_delivered", "cloud_send_step")
    assert run_local_fallback(config, deps) == 0
    assert deps.generate.calls == 0
    assert deps.send.calls == 0


def test_cloud_failure_generates_rechecks_and_sends_once(deps, config) -> None:
    deps.cloud_gate.side_effects = [
        CloudGateResult("run_local", "cloud_failed"),
        CloudGateResult("run_local", "cloud_failed"),
    ]
    assert run_local_fallback(config, deps) == 0
    assert deps.generate.calls == 1
    assert deps.send.calls == 1
    assert deps.dispatch_delivery.calls == 1


def test_delayed_cloud_success_on_second_gate_discards_local_preview(deps, config) -> None:
    deps.cloud_gate.side_effects = [
        CloudGateResult("run_local", "cloud_failed"),
        CloudGateResult("skip_delivered", "cloud_completed_during_generation"),
    ]
    assert run_local_fallback(config, deps) == 0
    assert deps.generate.calls == 1
    assert deps.send.calls == 0


def test_feishu_timeout_records_uncertain_and_never_dispatches(deps, config) -> None:
    deps.send.side_effect = FeishuDeliveryUncertain("indeterminate delivery")
    assert run_local_fallback(config, deps) == 2
    assert deps.fallback_ledger.day_state(DAY).delivery_status == "uncertain_delivery"
    assert deps.dispatch_delivery.calls == 0


def test_sync_failure_never_resends_and_retries_only_sync(deps, config) -> None:
    deps.dispatch_delivery.side_effect = GitHubStateSyncError("sync_failed")
    assert run_local_fallback(config, deps) == 2
    state = deps.fallback_ledger.day_state(DAY)
    assert state.delivery_status == "sent"
    assert state.cloud_sync_pending is True
    deps.dispatch_delivery.side_effect = None
    assert run_local_fallback(config, deps) == 0
    assert deps.send.calls == 1
    assert deps.dispatch_delivery.calls == 2
```

Add cases for invalid digest, no qualifying items, missing model, less than 8 GB free, wrong timezone symlink, GitHub clock drift, dashboard failure after send, sync failure after send, retention, and redacted notifications.

- [ ] **Step 5: Run orchestration tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_local_fallback.py -q`

Expected: FAIL because the orchestrator and entry point do not exist.

- [ ] **Step 6: Implement config, strict environment loading, preflight, and orchestration**

```python
@dataclass(frozen=True)
class LocalFallbackConfig:
    runtime_root: Path
    env_path: Path
    gh_path: Path
    ollama_app_path: Path
    repository: str
    cloud_wait_deadline: time = time(9, 50)
    timezone: str = "Asia/Shanghai"
    model: str = "qwen3:8b"
    minimum_free_bytes: int = 8 * 1024**3


@dataclass
class LocalFallbackDependencies:
    cloud_gate: Callable[[date], CloudGateResult]
    generate: Callable[[Path], EditorialDigest]
    send: Callable[[Path], EditorialDigest]
    dispatch_delivery: Callable[[date, str, str], None]
    publish_dashboard: Callable[[Path], None]
    notify: Callable[[str], None]
    send_ledger: SendLedger
    fallback_ledger: FallbackLedger
    now: Callable[[], datetime]
    sleep: Callable[[float], None]


class GitHubStateSyncError(RuntimeError):
    pass
```

The strict environment loader accepts only `KEY=VALUE` lines for an allowlist and rejects shell substitutions, command syntax, NUL/control characters, duplicate keys, and group/world-readable secret files. The runner starts the user-local Ollama app with `/usr/bin/open -gj -a <path>` only when loopback health is unavailable, waits at most 30 seconds, and never pulls a model during a scheduled run.

Generate into `runs/<UTC timestamp>/latest.json`, validate it with `EditorialDigest`, run the second cloud gate, call `send_existing_daily_result`, then dispatch the date and a `secrets.token_hex(16)` delivery ID through stdin. If synchronization is pending on a later invocation, retry only the dispatch and exit without generating or sending. If dashboard credentials are configured, publish the same validated JSON with `requests.post`; track `dashboard_pending` separately and retry only publication. Prune logs older than 30 days and all but the latest 14 run directories. Write only reason codes to logs/notifications.

- [ ] **Step 7: Add the console entry point**

```toml
ai-news-local-fallback = "ai_news_bot.local_fallback:main"
```

Expose `--scheduled`, `--run-now`, `--check-only`, and `--dry-run`. `--run-now` uses the same cloud gate; no Desktop-accessible force flag exists.

- [ ] **Step 8: Verify Task 4**

Run: `.venv/bin/python -m pytest tests/test_local_state.py tests/test_local_fallback.py tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```bash
git add src/ai_news_bot/local_state.py src/ai_news_bot/local_fallback.py pyproject.toml tests/test_local_state.py tests/test_local_fallback.py tests/test_cli.py
git commit -m "Add local fallback runner"
```

---

### Task 5: Cloud delivery-state synchronization workflow

**Files:**
- Create: `src/ai_news_bot/record_local_delivery.py`
- Create: `.github/workflows/record-local-delivery.yml`
- Create: `tests/test_record_local_delivery.py`
- Modify: `tests/test_daily_workflow.py`

**Interfaces:**
- Produces: `record_dispatched_delivery(payload, ledger_path, now) -> date` and repository dispatch type `local-ai-news-delivered`.
- Consumes: `SendLedger.record_day_success`, GitHub `client_payload.delivery_date`, and the existing `daily-ai-news` concurrency group/cache prefix.

- [ ] **Step 1: Write failing payload-validation tests**

```python
def test_records_only_current_beijing_day(tmp_path: Path) -> None:
    payload = {"delivery_date": "2026-08-03", "delivery_id": "a" * 32, "run_status": "published"}
    day = record_dispatched_delivery(payload, tmp_path / "daily_sends.json", NOW)
    assert day == date(2026, 8, 3)
    assert SendLedger(tmp_path / "daily_sends.json").was_sent(day)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"delivery_date": "2026-08-02", "delivery_id": "a" * 32, "run_status": "published"},
        {"delivery_date": "2026-08-03", "delivery_id": "not-safe", "run_status": "published"},
        {"delivery_date": "2026-08-03", "delivery_id": "a" * 32, "run_status": "failed"},
    ],
)
def test_rejects_invalid_or_noncurrent_payload(payload, tmp_path) -> None:
    with pytest.raises(ValueError):
        record_dispatched_delivery(payload, tmp_path / "daily_sends.json", NOW)
```

- [ ] **Step 2: Run recorder tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_record_local_delivery.py -q`

Expected: FAIL because the recorder does not exist.

- [ ] **Step 3: Implement the state-only recorder CLI**

Read payload JSON from `--payload` path, require `delivery_id` to match `[0-9a-f]{32}`, require the Beijing day to equal `now`, accept only `published` or `no_qualifying_items`, and call `record_day_success` for `feishu-daily`. Emit only `recorded_date=YYYY-MM-DD`.

- [ ] **Step 4: Write failing workflow-structure tests**

Assert the new workflow:

```python
assert workflow["on"]["repository_dispatch"]["types"] == ["local-ai-news-delivered"]
assert workflow["concurrency"]["group"] == "daily-ai-news"
assert workflow["concurrency"]["cancel-in-progress"] == "false"
assert "ai-news-history-" in workflow_text
assert "FEISHU" not in workflow_text
assert "CLOUDFLARE" not in workflow_text
assert "ai-news-bot --dry-run" not in workflow_text
assert "ai-news-bot --send-existing" not in workflow_text
```

- [ ] **Step 5: Implement `.github/workflows/record-local-delivery.yml`**

The exact step order is checkout, restore `.state/`, set up Python 3.12, install project, write `github.event.client_payload` to a `0600` temporary JSON file, invoke `python -m ai_news_bot.record_local_delivery`, then save `.state/` with key `ai-news-history-${{ github.run_id }}`. Permissions are `contents: read`; no model, Feishu, dashboard, or repository secret is exposed.

- [ ] **Step 6: Verify Task 5**

Run: `.venv/bin/python -m pytest tests/test_record_local_delivery.py tests/test_daily_workflow.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/ai_news_bot/record_local_delivery.py .github/workflows/record-local-delivery.yml tests/test_record_local_delivery.py tests/test_daily_workflow.py
git commit -m "Sync local delivery state"
```

---

### Task 6: Idempotent macOS installer, LaunchAgent, and Desktop controls

**Files:**
- Create: `scripts/install_ollama_macos.py`
- Create: `scripts/install_local_fallback.py`
- Create: `scripts/uninstall_local_fallback.py`
- Create: `local-fallback/com.baic.ai-news-bot.local-fallback.plist.template`
- Create: `local-fallback/run-now.command.template`
- Create: `local-fallback/view-logs.command.template`
- Create: `tests/test_local_installer.py`

**Interfaces:**
- Produces: user-local Ollama installation, runtime venv, protected config, LaunchAgent, and two Desktop controls.
- Consumes: checked-out repository, authenticated GitHub CLI binary, official Ollama zip, and Task 4 console command.

- [ ] **Step 1: Write failing installer rendering and permissions tests**

```python
def test_install_layout_is_idempotent_and_secret_is_0600(tmp_path: Path) -> None:
    result = install_local_fallback(fake_context(tmp_path))
    second = install_local_fallback(fake_context(tmp_path))
    assert result.runtime_root == second.runtime_root
    assert stat.S_IMODE(result.env_path.stat().st_mode) == 0o600
    assert result.launch_agent.exists()
    assert result.run_now.exists()
    assert result.view_logs.exists()


def test_launch_agent_runs_at_0935_and_passes_no_secrets(tmp_path: Path) -> None:
    plist = plistlib.loads(render_launch_agent(fake_context(tmp_path)))
    assert plist["StartCalendarInterval"] == {"Hour": 9, "Minute": 35}
    assert plist["ProgramArguments"][-1] == "--scheduled"
    assert "EnvironmentVariables" not in plist
```

Add tests that the installer refuses missing/nonexecutable `gh`, unauthenticated repository access, missing Ollama, less than 8 GB free, and an active schedule before smoke validation. Test uninstall preservation of `.env`, state, model data, and logs.

- [ ] **Step 2: Run installer tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_local_installer.py -q`

Expected: FAIL because installer modules/templates do not exist.

- [ ] **Step 3: Implement safe user-local Ollama installation**

`install_ollama_macos.py` downloads `https://ollama.com/download/Ollama-darwin.zip` to a temporary directory, extracts only `Ollama.app`, verifies with:

```bash
/usr/bin/codesign --verify --deep --strict Ollama.app
/usr/sbin/spctl --assess --type execute Ollama.app
```

It installs to `~/Applications/Ollama.app` only when no app exists, starts it with `/usr/bin/open -gj -a`, waits for loopback health, then runs the bundled CLI as `ollama pull qwen3:8b`. It never replaces an existing app or model during scheduled execution.

- [ ] **Step 4: Implement runtime installation and exact templates**

The installer creates the documented directories, copies the authenticated `gh` executable to `runtime/bin/gh`, creates `runtime/venv`, installs the project non-editably, copies `config/sources.yaml`, creates a mode-0600 environment template, and renders absolute paths into the LaunchAgent/Desktop templates.

The LaunchAgent contains:

```xml
<key>Label</key><string>com.baic.ai-news-bot.local-fallback</string>
<key>ProgramArguments</key>
<array>
  <string>__PYTHON__</string>
  <string>-m</string>
  <string>ai_news_bot.local_fallback</string>
  <string>--scheduled</string>
</array>
<key>StartCalendarInterval</key>
<dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>35</integer></dict>
<key>StandardOutPath</key><string>__STDOUT_LOG__</string>
<key>StandardErrorPath</key><string>__STDERR_LOG__</string>
```

Activation uses `launchctl bootstrap gui/<uid> <plist>` only after `--smoke-validated` is present. Desktop commands invoke the installed Python with `--run-now` and open the logs without sourcing the secret file in a shell.

- [ ] **Step 5: Implement rollback**

`uninstall_local_fallback.py` uses `launchctl bootout`, removes only the LaunchAgent and two exact Desktop files, and prints preserved runtime/state/log locations. `--remove-data` is intentionally absent.

- [ ] **Step 6: Verify Task 6**

Run: `.venv/bin/python -m pytest tests/test_local_installer.py -q`

Run: `plutil -lint local-fallback/com.baic.ai-news-bot.local-fallback.plist.template`

Expected: tests PASS and plist reports `OK` after test placeholder rendering.

- [ ] **Step 7: Commit Task 6**

```bash
git add scripts/install_ollama_macos.py scripts/install_local_fallback.py scripts/uninstall_local_fallback.py local-fallback tests/test_local_installer.py
git commit -m "Add macOS fallback installer"
```

---

### Task 7: Documentation, security regression, and full repository verification

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `README.md`
- Create: `docs/local-ollama-fallback-operations.md`
- Modify: `tests/test_daily_workflow.py`
- Modify: `tests/test_cross_language_web_contract.py` only if schema validation reuse requires it.

**Interfaces:**
- Produces: operator instructions and complete regression evidence.
- Consumes: all prior tasks.

- [ ] **Step 1: Add documentation assertions before documentation**

Extend an existing documentation test to require these literal operator facts:

```python
assert "09:35" in readme
assert "qwen3:8b" in readme
assert "uncertain_delivery" in operations
assert "不会自动重试发送" in operations
assert "~/Library/Application Support/Baic-AI-Message-Bot/.env" in operations
```

- [ ] **Step 2: Run the documentation tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_daily_workflow.py -q`

Expected: FAIL because Plan 2 operations are not documented.

- [ ] **Step 3: Document install, operation, status, recovery, and rollback**

Document exact environment names, runtime paths, 09:35/09:50 behavior, cloud gate decisions, valid empty-board behavior, manual no-send command, Desktop controls, `uncertain_delivery` manual review, log locations, model storage, state-sync workflow, and rollback. Add local runtime paths, `.env`, run outputs, and installer downloads to `.gitignore` without ignoring versioned templates.

- [ ] **Step 4: Run the full Python suite**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests PASS, zero failures.

- [ ] **Step 5: Run web validation**

Run: `npm ci && npm run lint && npm test && npm run build`

Working directory: `web/`

Expected: all commands exit 0.

- [ ] **Step 6: Run repository safety checks**

Run:

```bash
git diff --check
git status --short
rg -n "FEISHU_WEBHOOK_URL=https|CLOUDFLARE_AI_API_TOKEN=|gho_|github_pat_" . --glob '!docs/**'
```

Expected: no whitespace errors, only intended tracked files before commit, and no committed secret values.

- [ ] **Step 7: Commit Task 7**

```bash
git add .env.example .gitignore README.md docs/local-ollama-fallback-operations.md tests/test_daily_workflow.py tests/test_cross_language_web_contract.py
git commit -m "Document local Ollama fallback"
```

---

### Task 8: User-local installation and no-send acceptance

**Files changed outside Git:**
- Create: `~/Applications/Ollama.app`
- Create model-managed files under: `~/.ollama/models/`
- Create runtime-managed files under: `~/Library/Application Support/Baic-AI-Message-Bot/`
- Create after validation: `~/Library/LaunchAgents/com.baic.ai-news-bot.local-fallback.plist`
- Create after validation: the two documented Desktop controls.

**Interfaces:**
- Produces: installed but initially no-send-validated local fallback.
- Consumes: verified branch artifacts and user-provided local Feishu credentials.

- [ ] **Step 1: Ask for installation approval and install Ollama**

Run only after the execution environment grants network and `~/Applications` write approval:

```bash
.venv/bin/python scripts/install_ollama_macos.py --model qwen3:8b
```

Expected: notarization checks pass, loopback health succeeds, and `qwen3:8b` appears in `/api/tags`.

- [ ] **Step 2: Install runtime without activating the schedule**

```bash
.venv/bin/python scripts/install_local_fallback.py \
  --repo-root "$PWD" \
  --gh-path "/absolute/path/to/authenticated/gh"
```

Expected: runtime, protected environment template, venv, logs, and inactive templates exist; no LaunchAgent is loaded.

- [ ] **Step 3: Obtain local credentials without reading GitHub Secrets**

Ask the user to enter `FEISHU_WEBHOOK_URL` and optional `FEISHU_SIGNING_SECRET` into the protected environment file. Validate file mode and key presence while printing only `SET`/`UNSET`.

- [ ] **Step 4: Run real Ollama no-send smoke validation**

```bash
AI_BACKEND=ollama \
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1 \
OLLAMA_MODEL=qwen3:8b \
~/Library/Application\ Support/Baic-AI-Message-Bot/venv/bin/python \
  scripts/validate_ai_backend.py
```

Expected: `provider=Ollama model=qwen3:8b success=true`; no Feishu request occurs.

- [ ] **Step 5: Generate and inspect a no-send preview**

```bash
~/Library/Application\ Support/Baic-AI-Message-Bot/venv/bin/python \
  -m ai_news_bot.local_fallback --dry-run
```

Expected: schema-v4 preview and audit are created in the timestamped run directory; no Feishu or GitHub state dispatch occurs. Review source URLs, Chinese summaries, evidence anchors, and empty-board semantics.

- [ ] **Step 6: Simulate cloud success and failure gates**

Run the installed check command once against a fixture reporting a successful send step and once against completed failures. Expected decisions are `skip_delivered` and `run_local`, with the send dependency disabled in both acceptance simulations.

- [ ] **Step 7: Activate the LaunchAgent and Desktop controls**

```bash
.venv/bin/python scripts/install_local_fallback.py \
  --repo-root "$PWD" \
  --gh-path "/absolute/path/to/authenticated/gh" \
  --smoke-validated \
  --activate-schedule
```

Expected: `launchctl print gui/<uid>/com.baic.ai-news-bot.local-fallback` succeeds and the next scheduled time is 09:35.

- [ ] **Step 8: Stop before any first live send**

Report the no-send evidence, latest preview path, gate result, and installed scheduler status. Ask the user explicitly whether to perform the first live Plan 2 run for the current Beijing date. Do not invoke `--run-now` until the user says to send.

No Git commit is created for user-local runtime files.
