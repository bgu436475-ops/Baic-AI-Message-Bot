# Local Primary Delivery Design

## Objective

Make the user's always-on Mac the sole automatic producer and Feishu sender for
the daily AI digest. The local Ollama model must produce Chinese editorial
content at 09:05 Asia/Shanghai. GitHub Actions and Cloudflare remain available
for repository state and manual diagnostics, but must not automatically create
or send a second digest.

## Delivery model

- A macOS LaunchAgent invokes `ai_news_bot.local_fallback --primary-scheduled`
  at 09:05 in the Mac's Asia/Shanghai timezone.
- `--primary-scheduled` uses the existing local lock, protected local send
  ledger, Ollama preflight, evidence validation, hard editorial gates, Feishu
  delivery handling, state synchronization, dashboard publication and artifact
  pruning.
- Primary mode never asks GitHub whether cloud delivery succeeded and never
  waits for the legacy 09:50 cloud observation window. It still fails closed
  for invalid clock, environment, model, digest, delivery or local-state
  conditions.
- Before Feishu delivery, it writes the existing uncertain-delivery marker; a
  transport result that cannot be proven safe blocks retries for that date.
- After a confirmed local send, the existing repository-dispatch recorder
  writes cloud delivery state so manual cloud runs do not resend that date.

## Cloud change

- `daily-ai-news.yml` is retained for manually dispatched diagnostics only.
- Its `schedule` and `repository_dispatch` triggers are removed, and its main
  send steps are guarded so no cloud event can generate or send Feishu content.
- The separate local-delivery recorder workflow remains active because it only
  records proven local delivery state and never calls a model or Feishu.

## Installation and activation

1. Preserve the runtime secret file at
   `~/Library/Application Support/Baic-AI-Message-Bot/.env`; it must explicitly
   select `AI_BACKEND=ollama` and contain the Feishu webhook.
2. Confirm Ollama is reachable at `127.0.0.1:11434` and `qwen3:8b` is already
   installed. The scheduled task never downloads models.
3. Install the runtime and run a no-send local smoke test plus a generated
   preview validation.
4. Only after those checks pass, install the LaunchAgent and the Desktop
   `立即运行 Plan 2.command` control. The manual control runs the same primary
   idempotency checks; it is not force-send.

## Testing and acceptance

- Unit tests cover primary mode bypassing the cloud gate and the former 09:50
  wait while retaining preflight, local ledger and pre-send safety behavior.
- Workflow tests prove there are no automatic GitHub delivery triggers.
- A local no-send smoke test proves the actual Ollama model returns a grounded
  Chinese evidence record.
- A final manual Feishu send is a separate explicit approval after the preview
  is reviewed.

## Rollback

Use the existing uninstaller to unload the LaunchAgent and remove Desktop
controls. This retains the protected environment, model data, logs and ledgers
for audit. Re-enabling a cloud sender is a separate reviewed change.
