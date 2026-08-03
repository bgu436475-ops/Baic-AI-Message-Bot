# Local Ollama Fallback Design

## Objective

Provide an independent macOS fallback for the AI news bot. When no cloud run has successfully delivered the Beijing-date digest, a Mac mini that remains powered on and awake will generate the digest with a local Ollama model and send it to Feishu automatically.

The fallback optimizes continuity without weakening the existing editorial gates. It must not fill an empty board with low-value items, bypass evidence validation, expose secrets, or send a duplicate merely because a cloud run reported an overall failure.

## Chosen Approach

Use a macOS LaunchAgent at 09:35 local time, backed by Ollama `qwen3:8b` and the existing Python editorial pipeline. Before local generation, a gate inspects both the remote digest and individual GitHub Actions delivery steps. After a successful local send, a repository dispatch records the delivery in the cloud ledger so later manual or automatic cloud runs skip the date.

This is preferred over two alternatives:

- Always running locally at 09:35 is simpler but can duplicate a delayed cloud delivery.
- Reusing Cloudflare from the Mac avoids a model download but does not remain available when Cloudflare configuration or service is the failure source.

## Scope

### Included

- Ollama integration through its loopback OpenAI-compatible endpoint.
- `qwen3:8b` as the default local model on the M4 Mac mini with 16 GB memory.
- Automatic fallback evaluation at 09:35 Asia/Shanghai.
- Waiting for cloud work that is still queued or running, up to 09:50.
- Local generation, validation, Feishu delivery, local idempotency, cloud delivery-state synchronization, desktop launchers, local notifications, and sanitized logs.
- A manual no-send validation path and an explicitly invoked immediate fallback path.

### Excluded

- Replacing the normal Cloudflare/GitHub production path.
- Running when the Mac is powered off or asleep.
- Automatically waking a sleeping Mac.
- Publishing credentials, model files, local state, or logs to Git.
- Automatically downloading or upgrading the model during a scheduled run.
- Treating a successful model response as sufficient without the existing schema, source, evidence-anchor, hard-gate, and deduplication checks.

## Runtime Layout

The repository contains versioned scripts, templates, tests, and documentation. Installation creates user-owned runtime files outside the repository:

| Purpose | Location |
| --- | --- |
| Runtime root | `~/Library/Application Support/Baic-AI-Message-Bot/` |
| Secret environment | `~/Library/Application Support/Baic-AI-Message-Bot/.env` |
| Local state and ledger | `~/Library/Application Support/Baic-AI-Message-Bot/state/` |
| Per-run output | `~/Library/Application Support/Baic-AI-Message-Bot/runs/<date-time>/` |
| Logs | `~/Library/Logs/Baic-AI-Message-Bot/` |
| LaunchAgent | `~/Library/LaunchAgents/com.baic.ai-news-bot.local-fallback.plist` |
| Desktop controls | `~/Desktop/立即运行 Plan 2.command` and `~/Desktop/查看 Plan 2 日志.command` |

The installer sets the secret file to mode `0600`. Logs may include provider, model, HTTP status, counts, rejection reasons, and run IDs, but never environment values, request bodies, response bodies, webhook URLs, signatures, tokens, account IDs, or stack traces containing them.

## Components

### Ollama backend adapter

Extend backend configuration with explicit local-only variables:

- `OLLAMA_BASE_URL`, defaulting to `http://127.0.0.1:11434/v1` only when local mode is selected.
- `OLLAMA_MODEL`, defaulting to `qwen3:8b`.
- `AI_BACKEND`, with supported values `cloudflare`, `openai`, and `ollama`.

Production keeps its current provider selection. The local wrapper sets `AI_BACKEND=ollama`, so Cloudflare or OpenAI credentials cannot silently override the intended fallback. The adapter uses the existing OpenAI-compatible client and Pydantic response schema. Requests use temperature `0`, disable Qwen thinking output, and require the JSON schema; the pipeline still validates every evidence anchor against fetched source text.

Only loopback Ollama URLs are accepted. Hostnames and remote IP addresses are rejected so the local fallback cannot become an unreviewed third-party API route.

### Cloud delivery gate

The gate evaluates the current Beijing date in this order:

1. Acquire an atomic local run lock. If another Plan 2 process owns it, exit successfully without sending.
2. If the local send ledger already records the date, exit successfully.
3. Read recent `main` runs of `Daily AI News`, including `repository_dispatch`, `schedule`, and `workflow_dispatch` events.
4. Inspect job steps rather than relying only on the run conclusion. If `Send persisted daily result` succeeded for the date, treat delivery as complete even if a later publication or state-save step failed.
5. Read remote `main:web/public/data/latest.json`. Treat it as delivered only when `generated_at` is the current Beijing date and schema/status/content invariants are valid.
6. If any relevant cloud run is queued or running, poll once per minute until 09:50. Re-evaluate steps and the remote digest after each poll.
7. Fail closed on GitHub authentication errors, API uncertainty, malformed remote data, or an unclassifiable cloud state. Ambiguity produces a local notification, not a send.
8. Run locally only when the gate can prove there is no successful delivery and no relevant cloud work remains active.

GitHub access uses an authenticated `gh` CLI available to the logged-in macOS user. The installer records a stable executable path and validates access to the private repository without printing the token.

### Local editorial run

Before generating, the runner verifies:

- Ollama is reachable on loopback.
- `qwen3:8b` is already installed.
- Required Feishu configuration is present.
- The repository revision and Python environment are usable.
- At least 8 GB of disk space is free for model/runtime headroom.

The runner creates a timestamped output directory and performs these phases:

1. Generate with the existing dry-run pipeline into the run directory.
2. Validate the digest schema and state invariants.
3. Require grounded evidence and all existing hard gates; a valid `no_qualifying_items` digest remains a successful empty board.
4. Re-run the cloud delivery gate immediately before sending.
5. Send exactly the validated persisted artifact with `--send-existing`.
6. Record the local ledger atomically before any optional publication work.
7. Dispatch a `local-ai-news-delivered` event carrying only the Beijing date and a random delivery ID. A GitHub workflow under the existing concurrency group updates the cloud send ledger without generating or sending content.
8. If configured, publish the same validated digest through the existing private dashboard endpoint. Failure here does not resend Feishu and is reported separately.

The local runner never pushes generated files directly to `main`.

### Scheduler and desktop controls

The LaunchAgent uses `StartCalendarInterval` at 09:35 according to the Mac system timezone. The runner itself sets `TZ=Asia/Shanghai` and refuses to run automatically if the macOS timezone is not Asia/Shanghai. During the authenticated GitHub status request, it compares the HTTP `Date` header with local UTC time; a difference greater than five minutes is a fail-closed clock error.

`立即运行 Plan 2.command` runs the same gate and therefore is safe to click repeatedly. A separate `--force-send` capability is not exposed on the Desktop. Any override that can bypass the cloud gate remains a terminal-only, explicit maintenance operation.

`查看 Plan 2 日志.command` opens the log directory and the latest sanitized log without displaying the secret environment file.

## Idempotency and Race Handling

The local ledger prevents repeated local sends. The remote job-step inspection catches the important case where Feishu delivery succeeded but a later GitHub step failed. The pre-send second gate closes the normal race between a slow cloud job and local generation. The post-send repository dispatch synchronizes future cloud decisions.

There is no claim of mathematically perfect distributed exactly-once delivery. A network partition can occur after Feishu accepts the card but before either ledger is updated. In that case the runner records an `uncertain_delivery` state, blocks automatic retry for the date, and asks for manual review rather than risking a duplicate.

## Error Handling

- Missing Ollama, missing model, invalid secrets, insufficient disk, schema failure, evidence failure, or cloud-state ambiguity: do not send; notify locally and log a sanitized reason.
- Feishu timeout or indeterminate response: mark `uncertain_delivery`; do not retry automatically that day.
- Definite Feishu rejection: mark failure and notify; do not loop.
- Cloud-ledger synchronization failure after confirmed Feishu delivery: keep the local success ledger, notify locally, and retry synchronization without resending.
- Dashboard publication failure after confirmed delivery: notify and retry publication only.
- Retain 30 days of logs and the latest 14 run directories; never prune the send ledger automatically.

## Installation and Secrets

The installer is idempotent and performs explicit checks before changing user runtime state. It:

1. Verifies macOS, Apple Silicon, Python, authenticated GitHub CLI access, and free disk.
2. Installs Ollama only after user approval, then downloads `qwen3:8b` only after user approval.
3. Creates an isolated Python virtual environment and installs the checked-out project.
4. Creates the runtime directories and a `0600` environment template.
5. Refuses to activate scheduling until Feishu credentials are present and a no-send Ollama smoke test succeeds.
6. Installs and loads the LaunchAgent.
7. Creates the two Desktop controls.

The user supplies local Feishu values interactively or copies them from a trusted local `.env`; the installer never reads GitHub Actions secret values because GitHub does not expose them after creation.

## Testing and Acceptance

Automated tests cover:

- Explicit Ollama selection, loopback URL validation, and provider precedence.
- Structured extraction through a fake OpenAI-compatible Ollama response.
- Every cloud-gate state: sent step succeeded, valid remote digest, queued/running, failed, missing, malformed, authentication failure, and timeout.
- Local lock and ledger behavior, including `uncertain_delivery`.
- Pre-send recheck preventing a delayed cloud duplicate.
- Cloud ledger dispatch payload excluding secrets and content.
- LaunchAgent generation and `plutil -lint` validation.
- Installer idempotency, file modes, and Desktop controls.
- Redaction tests for logs and notifications.

Before activation, run the full Python and web suites, a real Ollama no-send smoke test, a generated preview review, and a scheduler dry run with Feishu disabled. The first live Feishu send is a separate, explicit user-approved operation. Success means:

- The no-send smoke test returns a valid grounded evidence record from `qwen3:8b`.
- Repeated fallback invocations do not duplicate a sent date.
- A simulated cloud success prevents the local send.
- A simulated cloud failure permits one validated local send.
- Secrets remain absent from Git, artifacts, logs, process arguments, and notifications.

## Rollback

Rollback unloads and removes the LaunchAgent and Desktop controls while preserving logs, model data, secrets, and send history for diagnosis. Removing Ollama, the model, or preserved state is a separate explicit action. The production GitHub/Cloudflare path continues unchanged throughout installation and rollback.
