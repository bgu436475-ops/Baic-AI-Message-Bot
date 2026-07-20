# AI 新闻 Bot 可靠外部定时设计

## 目标

让 AI 新闻 Bot 在每天北京时间 09:05 左右稳定启动，同时保留 GitHub Actions 原生定时任务作为备用。无论外部触发、GitHub 主定时和备用定时以什么顺序到达，同一天最多自动发送一次；人工点击 `Run workflow` 仍可显式补发。

## 已确认问题

生产工作流中的 UTC 定时换算是正确的：`5 1 * * *` 对应北京时间 09:05，`20 1 * * *` 对应北京时间 09:20。2026-07-18 和 2026-07-19 的 `schedule` 事件分别延迟约 6 小时和 8 小时才由 GitHub 创建，而事件创建后的工作流执行仅耗时几十秒。因此故障位于 GitHub 定时事件投递层，不在新闻采集、模型处理或飞书发送层。

## 方案选择

采用 Cloudflare Worker Cron Trigger 作为主时钟，并用 GitHub `repository_dispatch` 事件启动现有工作流。

未采用的方案：

- cron-job.org：配置简单，但需要将 GitHub 调用密钥交给通用第三方定时服务。
- 本机 `launchd`：无需云账号，但电脑关机、休眠或断网时不能工作。
- 只调整 GitHub cron 分钟：只能降低普通排队概率，无法消除连续数小时的 `schedule` 投递延迟。

## 架构

```text
Cloudflare Cron 09:05 (01:05 UTC)
        |
        | POST /repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches
        v
GitHub repository_dispatch: daily-ai-news
        |
        v
Daily guard ---- 当天已成功发送 ----> 跳过
        |
        v
采集与筛选 → 持久化当天结果 → 飞书发送 → 更新网页和状态

GitHub schedule 09:05 / 09:20 ------------------^
人工 workflow_dispatch ------------------------> 强制执行
```

Cloudflare 只负责发出一个最小触发请求，不接触飞书 Webhook、签名密钥、模型密钥或新闻内容。新闻处理继续全部运行在 GitHub Actions 中。

## 仓库侧改动

### GitHub 工作流

`.github/workflows/daily-ai-news.yml` 增加：

```yaml
repository_dispatch:
  types: [daily-ai-news]
```

保留现有两个 `schedule` 条目和 `workflow_dispatch`。`concurrency.group` 继续使用 `daily-ai-news`，保证同一时间只执行一个日报工作流。

### 每日去重

`daily_guard` 将 `schedule` 与 `repository_dispatch` 都视为自动触发：

- 当远端日报或持久化历史表明北京时间当天已经成功发送时，返回 `should_run=false`。
- 当日报缺失、日期不是当天、状态无效或当天尚未成功时，返回 `should_run=true`。
- `workflow_dispatch` 仍视为人工强制执行，不受自动去重阻止。

这样即使 GitHub 09:05 的原生定时事件在下午才到达，也会因为 Cloudflare 已完成当天发送而直接跳过，不会重复推送。

## Cloudflare Worker

新增独立目录 `cloudflare/ai-news-scheduler/`：

- `src/index.js`：实现 `scheduled()` 处理器，调用 GitHub Repository Dispatch API。
- `wrangler.jsonc`：声明每天 `01:05 UTC` 的 Cron Trigger、日志和所需密钥。
- `test/index.test.js`：使用 Node 内置测试验证请求地址、请求头、事件类型、成功响应和失败响应。
- `package.json`：提供 `test`、本地 scheduled 测试和部署命令。
- `README.md`：提供 Cloudflare 登录、密钥创建、部署和验证步骤。

Worker 使用 GitHub fine-grained personal access token，范围仅限 `bgu436475-ops/Baic-AI-Message-Bot`，仓库权限仅启用 `Contents: Read and write`。密钥名为 `GITHUB_DISPATCH_TOKEN`，只通过 Cloudflare Secret 保存，不进入 Git、日志或客户端页面。

请求固定为：

- URL：`https://api.github.com/repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches`
- 方法：`POST`
- 事件类型：`daily-ai-news`
- 成功状态：`204 No Content`
- `client_payload.source`：`cloudflare-cron`
- `client_payload.scheduled_at`：Cloudflare 提供的计划执行时间 ISO 字符串

非 204 响应必须抛出不含密钥的错误。Worker 最多尝试三次；最终失败时 Cloudflare 日志只记录 HTTP 状态码，绝不记录 GitHub 响应体。

## 自检规则

现有北京时间 09:35 自检继续运行，但判断主任务时同时接受：

- 成功的 `repository_dispatch`，事件类型为 `daily-ai-news`；或
- 成功的 GitHub `schedule` 运行。

若 09:05 外部触发成功并且远端日报有效，自检记录正常。若外部触发失败但 09:20 原生任务成功，则提醒“主任务异常，备用任务已恢复”。若两者都未成功，立即告警，但不自动补发。

## 错误处理

- Cloudflare 请求失败：有限重试三次，之后失败并记录可核查日志。
- GitHub 接受请求但 Actions 暂时不可用：`repository_dispatch` 运行会在 GitHub 侧排队；09:20 原生定时仍保留。
- 两个触发同时到达：GitHub concurrency 串行化，后一个运行由 `daily_guard` 跳过。
- 密钥失效：GitHub 返回 401/403；Worker 日志只记录 HTTP 状态码，不记录请求头或响应体。
- 当天没有合格新闻：日报流程按现有规则生成合法的空榜状态，不通过重复触发补足低价值内容。

## 测试和验证

实施时采用测试先行：

1. 增加失败测试，证明 `repository_dispatch` 在当天已发送时应被拦截，而人工 `workflow_dispatch` 仍可执行。
2. 增加失败测试，证明工作流声明指定的 Repository Dispatch 事件且保留两个 UTC schedule。
3. 增加 Worker 单元测试，覆盖 204、401/403、500 重试和请求体字段。
4. 运行完整 Python 测试套件和 Worker 测试套件。
5. 部署后手动调用一次 Cloudflare scheduled 测试入口，确认 GitHub 运行事件为 `repository_dispatch`；测试当天只允许在用户明确同意补发时进入飞书发送步骤。
6. 次日观察 09:05 外部主触发、09:20 原生兜底和 09:35 自检结果。

## 发布顺序

1. 先发布仓库侧 `repository_dispatch` 和自动去重支持。
2. 创建最小权限 GitHub token，并保存为 Cloudflare Secret。
3. 部署 Worker 和 Cron Trigger。
4. 更新 09:35 自检规则。
5. 进行不补发的只读核查，等待次日真实定时窗口完成最终验证。

每个独立功能完成测试后单独提交，不把定时可靠性修改与新闻内容优化混在同一个 commit 中。

## 成功标准

- 连续三个自然日，09:05 外部触发在目标时间后 5 分钟内出现在 GitHub Actions。
- 每天自动推送不超过一次。
- 外部主触发失败时，09:20 备用触发可被自检识别。
- 仓库和日志中不存在 GitHub token、飞书密钥或其他明文凭据。
- 手动 `Run workflow` 的补发能力保持不变。
