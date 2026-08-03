# macOS 本地 Ollama 后备运维手册

本手册说明 Plan 2 本地后备的安装、无发送验证、日常观察、异常恢复和回滚。它是云端 GitHub Actions 日报的故障后备，而不是第二个独立发送器：任何云端送达证据、未知云端状态或本地送达不确定状态都会阻止自动发送。

本文档只描述可执行的运维步骤。它不表示 Ollama、LaunchAgent、GitHub CLI 或飞书 webhook 已在任何机器上安装、配置、激活或发送过消息。

## 范围与固定安全边界

- 仅支持 Apple Silicon macOS。Ollama 应用安装位置为 `~/Applications/Ollama.app`，模型数据由 Ollama 管理在 `~/.ollama/models/`。
- 后备运行时目录为 `~/Library/Application Support/Baic-AI-Message-Bot/`；其中包括 `venv/`、`bin/gh`、`config/sources.yaml`、`state/`、`runs/` 和受保护的环境文件。
- 环境文件的唯一位置是 `~/Library/Application Support/Baic-AI-Message-Bot/.env`。安装器会以 `0600` 创建或收紧该文件权限；不要将它加入 shell profile、复制到仓库根目录 `.env`，或提交到 Git。
- 本地模型后端固定为 `AI_BACKEND=ollama`，默认 `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1` 和 `OLLAMA_MODEL=qwen3:8b`。地址必须是无凭据、无查询参数的 loopback HTTP `/v1` 地址；不能把它指向局域网或公网服务。Ollama 官方下载、模型请求和健康检查都会忽略 `HTTP_PROXY`/`HTTPS_PROXY` 等环境代理。
- 运行器不提供 force-send、自动重发或绕过云端门槛的参数。所有日期和截止时间按 `Asia/Shanghai` 判断。

## 安装前检查与安装

安装工作需要操作员在本机显式执行，且会下载软件、创建用户目录并在随后按命令模型拉取；不要在未审核分支或未获得本机管理员/所有者授权时执行。

1. 在本地克隆的、已经通过测试的仓库根目录准备一个已登录且能读取目标私有仓库的 GitHub CLI。安装器会验证 `gh auth status`、仓库访问、现有 Ollama App 和至少 8 GiB 可用磁盘；每次安装都会刷新运行时的项目包，即使该运行时 virtualenv 已存在。
2. 安装或验证 Ollama，并拉取模型。脚本仅从官方 Ollama macOS 下载地址获取压缩包；若 `~/Applications/Ollama.app` 已存在，绝不覆盖它，但仍会运行签名/系统评估、启动健康检查并确认模型：

   ```bash
   .venv/bin/python scripts/install_ollama_macos.py --model qwen3:8b
   ```

3. 安装本地运行时和 Desktop 模板。下面的 `gh` 路径及仓库名必须替换为该操作员已验证的实际值：

   ```bash
   .venv/bin/python scripts/install_local_fallback.py \
     --repo-root "$PWD" \
     --gh-path /usr/local/bin/gh \
     --repository bgu436475-ops/Baic-AI-Message-Bot
   ```

   此步骤会创建运行时、`~/Library/Logs/Baic-AI-Message-Bot/`、运行时内的 `staging/com.baic.ai-news-bot.local-fallback.plist` 和“查看 Plan 2 日志”Desktop 控件，但不会写入 `~/Library/LaunchAgents/`、激活定时任务或创建发送控件。运行时使用自己的非编辑安装 virtualenv 和复制的 `gh`，不从 shell 读取密钥。

4. 在受保护文件中填写凭证，保持一行一个 `KEY=VALUE`，无引号、无空行、无 `export`、无 shell 展开。允许的变量名只有：

   ```text
   AI_BACKEND=ollama
   OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
   OLLAMA_MODEL=qwen3:8b
   FEISHU_WEBHOOK_URL=
   FEISHU_SIGNING_SECRET=
   SITE_DIGEST_ENDPOINT=
   SITE_BYPASS_TOKEN=
   SITE_DIGEST_UPDATE_SECRET=
   ```

   `FEISHU_WEBHOOK_URL` 是本地运行所必需的；签名密钥可留空。三个 `SITE_*` 值要么全部留空（不发布网页），要么全部设置（确认发送后才发布）。切勿在终端、日志、Issue、截图或 Git 中粘贴真实值。

## 无发送验证与激活

先验证健康状态和云端门槛，不生成日报也不调用飞书：

```bash
~/Library/Application\ Support/Baic-AI-Message-Bot/venv/bin/python \
  -m ai_news_bot.local_fallback \
  --gh-path ~/Library/Application\ Support/Baic-AI-Message-Bot/bin/gh \
  --check-only
```

这是日常的手动无发送命令。它会检查受保护环境、磁盘、Ollama 服务和 `qwen3:8b` 模型，并读取 GitHub 云端状态；任何非零退出或 macOS 通知中的 reason code 都应先排查，不要改用发送命令绕过。

如需单独验证模型但不调用飞书，可在本机受控环境中执行现有 smoke validator，且只使用回环 Ollama 设置：

```bash
AI_BACKEND=ollama \
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1 \
OLLAMA_MODEL=qwen3:8b \
~/Library/Application\ Support/Baic-AI-Message-Bot/venv/bin/python \
  scripts/validate_ai_backend.py
```

仅在操作员已审阅无发送结果后，才允许安装器激活定时任务；这两个标志必须同时给出。此时安装器才会把 staging 中的 plist 移入 `~/Library/LaunchAgents/` 并 bootstrap；若 `launchctl print` 显示标签已经加载，或其状态不能明确证明服务不存在，安装器会停止并保留现有文件：

```bash
.venv/bin/python scripts/install_local_fallback.py \
  --repo-root "$PWD" \
  --gh-path /usr/local/bin/gh \
  --repository bgu436475-ops/Baic-AI-Message-Bot \
  --smoke-validated \
  --activate-schedule
```

激活还会经已登录的 GitHub CLI 检查远端 `main` 分支存在 `record-local-delivery.yml`；缺少该工作流时安装器拒绝激活。激活后，`~/Library/LaunchAgents/com.baic.ai-news-bot.local-fallback.plist` 每天北京时间 09:35 运行 `--scheduled`。它不会在 09:35 直接发送：在 09:50 前，即使云端已明确失败，也会每 60 秒重查；使用本机上海时钟确认窗口关闭后才允许本地候选发送。09:50 是送达结论观察窗口的下限，不是送达承诺。

## 云端门槛与本地发送决策

每次本地候选发送会在生成前、生成后和持久化预发送状态前各检查一次云端；每次云端门槛返回后都会重新读取北京时间，避免用轮询开始前的旧时间作 09:50 决策。任何后续检查发现云端已经送达时，都会丢弃本地预览而不发送。该流程使用本地互斥锁，但不能把 GitHub 与飞书变成同一把全局原子锁；时间或云端状态不确定时一律停止。

| 云端观察结果 | 本地行为 |
| --- | --- |
| 已找到当天成功的 `Send persisted daily result` 步骤 | `skip_delivered`，不生成、不发送。 |
| 当前北京日期的远端 `latest.json` 能通过 schema 验证 | `skip_delivered`，不发送。有效的空榜（`no_qualifying_items`）也属于送达证据，不能因“没有新闻”而补发。 |
| 当天云端任务仍在执行 | 等待，最多到 09:50；之后以 `cloud_wait_timeout` 停止。 |
| 当天云端任务均完成但无发送证据，且远端状态清楚 | 09:50 前继续观察；09:50 后才 `run_local` 并生成候选。 |
| GitHub 认证/API/时钟、远端 JSON 或状态无法验证 | fail closed：停止自动发送，先修复原因。 |

本地也会检查当天的发送账本和本地 `state/fallback.json`。云端运行历史通过 `gh` 的分页 `--limit` 查询到北京时间日期边界；只有当天的 `schedule` 与 `repository_dispatch` 运行会再以 `gh run view` 检查发送步骤，历史或其他触发事件不会造成逐条检查。正常超过 30 条历史不会阻断当天成功证据，但在高限额内仍无法确认边界时会 fail closed。已确认发送、远端已送达、已有本地发送账本或另一进程占有锁时，都不产生第二条飞书消息。

## Desktop 控件、状态和恢复

完成无发送 smoke validation 后，以 `--smoke-validated` 重新运行安装器才会创建“立即运行 Plan 2”控件；在此之前只创建日志控件。该步骤不激活定时任务，也不会自行发送；只在操作员明确批准后，才按上文使用 `--activate-schedule` 激活排程。两个精确名称的 Desktop 文件为：

- `~/Desktop/立即运行 Plan 2.command`：运行 `--run-now`，仅在北京时间 09:50 后并通过三次云端门槛时才可发送；它不是强制发送按钮。
- `~/Desktop/查看 Plan 2 日志.command`：打开 `~/Library/Logs/Baic-AI-Message-Bot/`。

关键诊断位置如下：

- 标准输出：`~/Library/Logs/Baic-AI-Message-Bot/local-fallback.stdout.log`
- 标准错误：`~/Library/Logs/Baic-AI-Message-Bot/local-fallback.stderr.log`（运行器的结构化诊断日志写入这里）
- 每次本地预览：`~/Library/Application Support/Baic-AI-Message-Bot/runs/<UTC 时间戳>/latest.json`
- 本地发送/同步状态：`~/Library/Application Support/Baic-AI-Message-Bot/state/fallback.json`
- 本地日报账本、历史和审计：同一 `state/` 目录中的 `daily_sends.json`、`history.json`、`events.json` 和 `latest_audit.json`

系统会保留最近 14 个 run 目录和 30 天日志。先读取 reason code 与上述文件；日志和通知只应包含安全 reason code，不应包含 webhook、令牌或命令输出。

`uncertain_delivery` 表示飞书请求已经可能到达、但本地无法确认响应，或请求后本地持久化出现异常。此状态下**不会自动重试发送**。操作员必须先在飞书群确认当天是否已收到消息，并核对当天云端运行和 `state/fallback.json`；在送达情况仍不明确时，保持停止状态并人工升级处理，绝不能重跑以“试一次”。

确认送达后，本地会先记录不可重复的 delivery ID，再通过 GitHub `repository_dispatch` 触发 `Record local AI news delivery`。dispatch 的 HTTP 接受本身**不会**清除 `cloud_sync_pending`：运行器会按 delivery ID 关联工作流运行，等待该运行成功并确认 `Save delivery state` 步骤成功后才清除 pending。该工作流只记录当天已确认的 `published` 或 `no_qualifying_items` 状态，绝不调用飞书或模型。工作流缺失、失败、状态缓存失败或确认超时，以及网页发布暂时失败，都会保留 pending；下一次本地运行只重试状态同步/网页发布，**不会自动重试发送**。若有前一天 pending 状态，先人工解决该状态，系统会用 `stale_pending_delivery` 阻止新一天发送。

## 回滚

要停用 Plan 2 控件但保留故障排查证据，执行：

```bash
.venv/bin/python scripts/uninstall_local_fallback.py
```

脚本总会先用 `launchctl print` 检查标签（即使 plist 已缺失）；仅退出码 `3`，或退出码 `113` 且标准错误规范化后包含已知的 service-not-found 文本（如 `Could not find specified service`），才视为未加载。仅标签已加载时才 `bootout`，随后再次用 `launchctl print` 确认标签不再加载。任何其他非零状态都视为不明确的失败。只有检查与卸载成功时才删除以下项目；标签未加载时视为幂等成功。若失败或标签仍加载，脚本以非零退出、报告明确原因并保留 plist 和 Desktop 控件供排障：

- `~/Library/LaunchAgents/com.baic.ai-news-bot.local-fallback.plist`
- `~/Desktop/立即运行 Plan 2.command`
- `~/Desktop/查看 Plan 2 日志.command`

它刻意保留运行时、`.env`、状态、run 输出、日志和 `~/.ollama/models/`，也没有 `--remove-data` 选项。保留数据便于审计；如需删除任何数据或 Ollama 应用，请先备份并按组织的数据保留和变更流程另行操作。
