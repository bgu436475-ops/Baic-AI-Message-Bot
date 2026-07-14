# AI 新闻 Bot 交付说明

## 已完成

- 自动采集三层信息源：官方发布、开发者/开源生态、行业媒体。
- 覆盖新模型、AI 编程、Agent、图片/视频生成、ComfyUI、GitHub 开源项目、MCP、Skill、行业/商业动态九类内容。
- 规范化链接、标题指纹、相似标题、模型语义合并和 30 天历史记录五层去重。
- 使用 OpenAI 结构化输出完成中文标题、1–2 句摘要、主/辅助分类、重要性排序和约 10 条精选。
- 生成飞书 V2 消息卡片，每条保留原始链接、来源和重要性。
- GitHub Actions 已配置为 `Asia/Shanghai` 每天 09:00 自动执行。
- 已加入外部内容提示注入防护、单源失败隔离、飞书签名校验和 20 KB 请求大小保护。

## 实测结果

- 单元测试：8 项全部通过。
- 真实公开源预览：采集 63 条，硬去重后 62 条候选。
- 本次有更新的有效来源：7 个；无失效源告警。
- 预览过程没有调用 OpenAI，也没有向飞书发送消息。

## 启用前只需配置

在 GitHub 仓库的 Actions Secrets 中添加：

1. `OPENAI_API_KEY`
2. `FEISHU_WEBHOOK_URL`：在“AI 增长内部群”中创建 V2 自定义机器人后获得
3. `FEISHU_SIGNING_SECRET`：仅在机器人启用签名校验时需要

随后手动运行一次 `Daily AI News` 工作流验证。成功后会按北京时间每天 09:00 自动发送。

请勿把 webhook、签名密钥或 API Key 提交到代码仓库，也不要粘贴到聊天中。

## 主要文件

- `README.md`：完整使用与维护说明
- `config/sources.yaml`：信息源、权重、分类提示和 GitHub 查询
- `src/ai_news_bot/`：采集、去重、AI 筛选、飞书卡片和命令入口
- `.github/workflows/daily-ai-news.yml`：每天 09:00 定时任务
- `tests/`：自动测试
