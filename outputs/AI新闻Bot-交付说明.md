# AI 新闻 Bot 交付说明

## 已完成

- 自动采集三层信息源：官方发布、开发者/开源生态、行业媒体。
- 覆盖新模型、AI 编程、Agent、图片/视频生成、ComfyUI、GitHub 开源项目、MCP、Skill、行业/商业动态九类内容。
- 规范化链接、标题指纹、相似标题、模型语义合并和 30 天历史记录五层去重。
- 默认使用 Cloudflare Workers AI 结构化输出完成中文标题、1–2 句摘要、主/辅助分类、重要性排序和约 10 条精选；OpenAI 仅作为显式配置的付费备用后端。
- 生成飞书 V2 消息卡片，每条保留原始链接、来源和重要性。
- GitHub Actions 已配置为 `Asia/Shanghai` 每天 09:05 自动执行，并在 09:20 进行后备触发。
- 已加入外部内容提示注入防护、单源失败隔离、飞书签名校验和 20 KB 请求大小保护。

## 实测结果

- 单元测试：8 项全部通过。
- 真实公开源预览：采集 63 条，硬去重后 62 条候选。
- 本次有更新的有效来源：7 个；无失效源告警。
- 预览过程没有调用 OpenAI，也没有向飞书发送消息。

## 启用前只需配置

1. 在 Cloudflare Dashboard 的 **Workers AI** 页面选择 **Use REST API**，创建 Workers AI API Token 并复制 Account ID。使用 Workers AI API Token 模板，避免 Global API Key；若手动创建 Token，只给目标 Account 的 Workers AI `Read` 与 `Edit` 权限。
2. 在 GitHub 仓库的 `Settings → Secrets and variables → Actions → Secrets` 中添加：

   - `CLOUDFLARE_ACCOUNT_ID`
   - `CLOUDFLARE_AI_API_TOKEN`
   - `FEISHU_WEBHOOK_URL`：在“AI 增长内部群”中创建 V2 自定义机器人后获得
   - `FEISHU_SIGNING_SECRET`：仅在机器人启用签名校验时需要
   - `OPENAI_API_KEY`：可选付费备用；仅在 Cloudflare 两项凭证都未配置时使用

3. 如需换模型，可在同一页面的 `Variables` 中创建可选的 Repository Variable `CLOUDFLARE_AI_MODEL`；未创建时使用支持 JSON Mode 的 `@cf/meta/llama-3.1-8b-instruct-fast`。
4. 先在功能分支手动运行一次 `Daily AI News`，确认 `Validate AI backend without sending` 成功。该分支路径会运行验证与预览，但不会采集日报、发送飞书或写入网页；合并到 `main` 后才会按北京时间 09:05 触发，并在 09:20 进行后备触发。

Cloudflare Workers AI 是默认后端，只有两个 Cloudflare Repository Secrets 同时存在时才会使用；两项都未设置时才回退到显式配置的 OpenAI API Key。ChatGPT 或 GitHub Copilot 订阅不提供 OpenAI API 额度，且没有供应商可以承诺永久免费配额。请勿把 webhook、签名密钥或 API Token 提交到代码仓库，也不要粘贴到聊天中。

## 主要文件

- `README.md`：完整使用与维护说明
- `config/sources.yaml`：信息源、权重、分类提示和 GitHub 查询
- `src/ai_news_bot/`：采集、去重、AI 筛选、飞书卡片和命令入口
- `.github/workflows/daily-ai-news.yml`：每天 09:05 定时任务与 09:20 后备触发
- `tests/`：自动测试
