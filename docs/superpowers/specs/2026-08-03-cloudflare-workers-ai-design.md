# Cloudflare Workers AI 免费后端迁移设计

## 目标

将已经永久退役的 GitHub Models 后端替换为 Cloudflare Workers AI，使每日 AI 新闻流水线在没有 OpenAI API 余额时仍能自动完成中文结构化证据提取。迁移不得降低现有硬门槛、事件去重、技术榜/全球重大事件榜、飞书发送和网页输出的完整性。

## 已确认约束

- 生产基线是 GitHub 远端 `origin/main`，不是落后的本地 `main`。
- Cloudflare Workers AI 是首选后端；OpenAI 仅作为显式配置备用。
- 不做运行中自动切换到 OpenAI，避免 Cloudflare 超额后产生不可预期费用。
- GitHub Models 已退役，不再作为任何自动回退路径。
- 免费额度不足或模型输出无法通过结构校验时允许少发或空榜，不允许降低证据标准补足数量。
- 改动先在 `codex/cloudflare-workers-ai` 隔离分支验证，不直接影响生产 `main`。

## 方案比较

### A. Cloudflare Workers AI 主后端（采用）

复用项目已有的 OpenAI Python SDK，通过 Cloudflare 的 OpenAI 兼容 Chat Completions 接口调用模型。优点是改动集中、支持结构化 JSON、已有 Cloudflare 账户可复用，并有每天重置的免费额度。缺点是免费额度和模型可用性不是永久承诺，且开源小模型的提取质量低于付费旗舰模型。

### B. Gemini API Free Tier

免费层可用且中文质量通常更好，但存在地区、项目配额和 Google 服务可达性差异，还会引入第二套账户和密钥管理。本次不采用，保留为未来第二供应商。

### C. GitHub Copilot CLI

可在 Actions 中运行，但不是当前结构化模型 API 的直接替代，需要重写调用与配额归属逻辑，不适合每日多条原文证据提取。本次不采用。

## 配置与后端选择

新增以下配置：

- `CLOUDFLARE_ACCOUNT_ID`：Cloudflare Account ID。
- `CLOUDFLARE_AI_API_TOKEN`：只授予 Workers AI 所需权限的 API Token。
- `CLOUDFLARE_AI_MODEL`：默认 `@cf/meta/llama-3.1-8b-instruct-fp8`。

Cloudflare 基础地址由程序构造为：

`https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1`

后端选择顺序为：

1. 两项 Cloudflare 凭证都存在时使用 Cloudflare Workers AI。
2. Cloudflare 凭证都不存在且存在 `OPENAI_API_KEY` 时使用 OpenAI。
3. Cloudflare 只配置一项时立即给出明确配置错误，不静默回退。
4. 两个后端都没有时立即失败，并说明需要哪些密钥。

`GITHUB_TOKEN` 继续仅用于 GitHub 新闻采集和仓库操作，不再被误用为模型凭证。

## 数据流与额度控制

候选采集、原文抓取、技术证据提取、全球事件证据提取和所有确定性门槛保持不变。Cloudflare 使用 Chat Completions 结构化解析路径；OpenAI 保持 Responses 结构化解析路径。

默认 Cloudflare 模型选择 8B FP8，是为了让技术榜与全球事件榜最坏情况下约 40 次证据提取仍有机会落在每日免费额度内。现有单条请求 4,500 token 上限和超限后 2,200 token 重试上限继续生效。程序不为了凑榜绕过证据验证；模型能力不足时记录提取失败并少发或输出正常空榜。

本次不增加自动付费、自动切换付费模型或自动重试整轮任务。后续可根据 Cloudflare 仪表盘的真实用量再调低 shortlist 或更换模型。

## 工作流和文档

GitHub Actions 的生成步骤将传入三个 Cloudflare 配置值。`CLOUDFLARE_AI_MODEL` 使用 GitHub Actions Variable，可不创建；两个凭证必须作为 Repository Secrets 保存。

README、`.env.example` 和交付说明将移除“GitHub Models 免费回退”的过期描述，改成 Cloudflare 配置步骤，并明确 OpenAI API 与 ChatGPT/Copilot 订阅相互独立。

## 错误处理

- Cloudflare 凭证不完整：生成前失败，日志不输出任何密钥内容。
- 401/403：保留供应商错误并由 Actions 标红，提示检查 Token 权限或 Account ID。
- 429/免费额度用尽：任务失败，不发送旧简报；09:20 备用任务即使重试也受同一日额度约束。
- 单条结构化解析失败：沿用现有二次解析与审计逻辑；失败候选被淘汰，不污染榜单。
- Cloudflare 整体不可用：不自动调用可能计费的 OpenAI；需人工显式切换配置。

## 测试与验收

采用测试驱动方式完成：

1. 先增加后端选择测试，验证 Cloudflare 优先级、URL、默认模型、环境变量读取、半配置报错和 GitHub Token 不再触发模型后端。
2. 先增加适配器测试，验证 Cloudflare 走结构化 Chat Completions，OpenAI 仍走 Responses。
3. 增加工作流静态测试或断言，确保只从 Secrets/Variables 注入，不把凭证写入仓库。
4. 运行完整 Python 测试；若前端未改动，仍运行现有网页测试与 lint 作为回归验证。
5. 推送隔离分支后，在用户配置两个 Cloudflare Secrets 的前提下执行一次不发送飞书的真实模型验证；只有结构化响应可解析且完整测试通过后才建议合并到 `main`。

## 非目标

- 本次不修改新闻来源、评分、去重、分类、飞书卡片设计或定时器。
- 本次不删除用户现有的 `OPENAI_API_KEY` Secret。
- 本次不承诺第三方免费额度永久不变。
