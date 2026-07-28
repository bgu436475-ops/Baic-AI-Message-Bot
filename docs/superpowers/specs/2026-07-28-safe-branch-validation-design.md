# 安全分支生产链路验证设计

日期：2026-07-28
状态：待执行
目标仓库：`bgu436475-ops/Baic-AI-Message-Bot`
验证分支：`codex/validate-grounded-action-editor`

## 目标

在不影响 `main`、飞书群、线上网页和正式简报文件的前提下，使用
GitHub Actions 真实验证新闻采集、证据提取、行动编辑、硬门槛筛选及
schema v3 导出链路。

## 方案

仅在验证分支修改现有 `Daily AI News` 工作流：

1. 手动触发验证分支时，跳过每日发送防重状态的约束并执行
   `ai-news-bot --dry-run`。
2. 禁止执行 `ai-news-bot --send-existing`。
3. 禁止提交或推送 `web/public/data/latest.json`。
4. 禁止调用线上网页更新接口。
5. 上传本次生成的简报与审计文件为 GitHub Actions artifact，供只读核查。
6. 正式定时事件仍只在 GitHub 默认分支 `main` 上生效。

## 安全条件

- 验证运行必须由 `workflow_dispatch` 触发。
- 验证运行的 ref 必须是 `codex/validate-grounded-action-editor`。
- 任何非验证分支或非手动事件都不得进入验证路径。
- 飞书密钥可以保留在仓库配置中，但验证步骤不得读取或使用这些密钥。
- 验证分支不合并到 `main`。

## 成功标准

- GitHub Actions 验证运行成功结束。
- 日志显示完成真实候选采集和编辑流水线。
- artifact 中包含 schema v3 的 `latest.json` 与审计结果。
- `run_status` 为 `published` 或 `no_qualifying_items`，且字段与条目数量一致。
- 若为 `published`，入选条目的 `recommended_action` 包含证据依据。
- 运行中没有飞书发送、Git 提交、Git 推送或线上网页发布步骤。

## 明日正式运行

验证分支不会改变正式任务。默认分支 `main` 继续按北京时间 09:05
执行主定时任务，并在 09:20 保留 GitHub 备用定时任务；Cloudflare
外部触发配置保持不变。
