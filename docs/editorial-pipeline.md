# 结构化编辑流水线运维说明

本文描述当前生产代码的筛选、输出、状态和恢复语义。它不包含飞书 webhook、签名密钥、模型密钥或网页发布密钥。

## 两阶段流水线与模块职责

阶段一负责低成本发现和核查：

1. `collectors.py` 从 RSS、网页和 GitHub 收集候选；所有已配置来源都失败属于系统失败，部分来源成功但没有候选可以继续。
2. `cli.py` 先排除 30 天 URL 历史、执行链接/标题硬去重，并把候选硬限制在 80 条以内。只有当前窗口没有候选通过粗筛时，才扩展回看窗口。
3. `shortlist.py` 根据时效、信源层级、具体数字/API/SDK/版本等信号确定性粗筛，最多保留 20 条，不补足最低数量。
4. `source_fetcher.py` 逐条抓取原始页面，限制响应体和正文长度并清理页面；单条失败不终止，全部粗筛来源不可用才使任务失败。
5. `evidence.py` 把候选和已抓取原文作为不可信数据交给模型，只提取 `EvidenceRecord`，不允许模型评分或分榜；解析失败只重试一次，证据引文必须能在原文中逐字核对。

阶段二由程序执行编辑决策：

1. `gatekeeper.py` 执行硬门槛，模型不能绕过。
2. `event_history.py` 生成事件指纹，在过去 7 个北京时间日内区分 `unique`、`material_update`、`minor_update` 和 `duplicate`。
3. `scoring.py` 计算固定分项分数及惩罚项。
4. `boards.py` 按稳定排序创建互斥的 5+3+3 榜单，不用低分内容补位。
5. `pipeline.py` 串联上述阶段，限制模型输出的长度和数量、清理疑似密钥，并写出公开简报与私密审计所需的数据。
6. `feishu.py` 渲染三个榜单或合法空榜卡；`send_ledger.py` 与 `daily_guard.py` 以“飞书已成功交付”为自动重试的唯一跳过依据。
7. `web_export.py` 导出网页读取的 schema v3；网页仍对历史 schema v2 数据保留窄范围只读兼容。

当前生产接线没有 `original_source_resolver`，也不会自动把一篇二手报道与它引用但不可访问的一手来源配对。因此，虽然数据模型和测试支持“可信二手来源 + 已独立确认一手来源为 `blocked`/`unavailable`”进入观察项，当前生产运行会安全地将这类内容标为 `unverified_primary_source` 并淘汰。不得通过让模型自行填写 `original_source_status` 绕过该限制。

## Schema v3

公开简报 `EditorialDigest` 的顶层字段是：

- `schema_version`: 固定为 `3`。
- `run_status`: `published` 或 `no_qualifying_items`。
- `generated_at`: 带时区的生成时间。
- `candidate_count`、`source_count`: 采集候选和来源计数。
- `latest_published_at`: 入选内容的最新原始发布时间，空榜为 `null`。
- `fresh_count_24h`: 入选内容中近 24 小时发布的数量。
- `lookback_hours`、`fallback_used`: 实际回看窗口及是否启用扩展窗口。
- `boards`: `must_read`、`try_now`、`watch` 三个互斥数组，上限分别为 5、3、3。
- `items`: 严格等于按上述顺序展开的 `boards`，最多 11 条。
- `pipeline_stats`: `candidate_count`、`shortlist_count`、`source_verified_count`、`rejected_count` 和 `top_rejection_reasons`。

每个榜单项包含：

- 身份与展示：`candidate_id`、`board`、`original_title`、`title_en`、`summary_en`、`title_zh`、`summary_zh`。
- 决策信息：`concrete_change`、`affected_audience`、`affected_area`、`recommended_action`。
- 证据与去重：`evidence_url`、`verification_status`、`event_fingerprint`、`update_of`。
- 事件结构：`primary_entity`、`event_entities`、`change_signature`、`version_or_metric`、`effective_date`。
- 其他信号：`resource_available`、`scientific_verified`、`source`、`published_at`、`category`、`extra_categories`。
- `score`: `relevance`、`actionability`、`specificity`、`information_gain`、`evidence_quality`、`time_sensitivity`、`penalties` 和计算字段 `total`。

`published` 必须至少有一条内容；`no_qualifying_items` 必须是三个空榜且 `items=[]`。榜单字段、`board` 值、展开后的 `items` 或事件指纹发生冲突时，schema 校验会拒绝数据。

## 硬门槛和淘汰码

当前全部 13 个淘汰码如下：

| 淘汰码 | 条件 |
| --- | --- |
| `funding_only` | 只有融资，没有客户、收入、产品或技术事实 |
| `opinion_without_evidence` | 只有观点，没有事实证据 |
| `policy_without_terms_or_date` | 政策没有非空具体条款，或没有有效 ISO 生效日期 |
| `vague_claim_without_evidence` | 模糊判断没有对应证据 |
| `title_body_conflict` | 标题和正文的数字或实体冲突 |
| `scientific_claim_unverified` | 科学结论没有原始论文或独立验证 |
| `duplicate_without_material_update` | 过去 7 天内重复或只有轻微更新 |
| `missing_concrete_change` | 没有具体变化 |
| `missing_action` | 没有建议行动 |
| `missing_affected_audience` | 没有受影响对象 |
| `missing_affected_area` | 没有受影响内容 |
| `invalid_evidence_anchor` | 没有能在已抓取原文中核对的证据引文 |
| `unverified_primary_source` | 不是已验证的一手来源 |

主榜和试用榜必须没有任何淘汰码。观察项也不能绕过内容、证据、行动或重复门槛；只有经过程序独立确认的一手来源不可用/被阻止时，已验证的可信二手来源才可把 `unverified_primary_source` 作为唯一例外。

## 分数、惩罚和分榜

总分是六个正向分项与惩罚项之和，最低截断为 0：

| 分项 | 权重和规则 |
| --- | --- |
| 用户相关性 | `direct=25`、`adjacent=15`、`low=5` |
| 可行动性 | 资源可用且行动期不超过 7 天为 20；有建议行动为 14；否则 0 |
| 具体性 | 每项具体变化 7 分，存在版本/指标加 4，有效 ISO 生效日期加 4，最高 15 |
| 信息增量 | `unique=15`、`material_update=10`、`minor_update=3`、`duplicate=0` |
| 证据质量 | 官方公告/论文/模型卡/法律法规/财报为 15，代码仓库 14，官方 Demo 12，可信二手来源 8 |
| 时间敏感度 | 发布不超过 24 小时为 10，不超过 72 小时为 7，更早为 2 |

惩罚项可以叠加：

- `minor_update`: -20。
- 证据没有覆盖完整结论: -15。
- 营销夸张: -10。
- 超过 72 小时且没有有效生效日期: -10。

确定性排序依次比较总分、信息增量、证据质量、发布时间、事件指纹、候选 ID、证据 URL、中文标题、来源和完整规范化记录。分榜条件是：

- 今日必看 `must_read`: 主榜合格，总分至少 75，证据质量至少 12，信息增量至少 10，最多 5 条。
- 值得试用 `try_now`: 主榜合格，总分至少 62，可行动性至少 14，资源已可用，行动期不超过 7 天，最多 3 条。
- 观察项 `watch`: 观察项合格且总分至少 50，最多 3 条。

系统依次分配今日必看、值得试用、观察项，同一事件只能出现一次；今日必看和值得试用合计同一规范化主体最多两条。没有达到条件的内容不会用于补位。

## 状态文件与准确写入时机

默认状态目录是 `.state/`，GitHub Actions 会整体恢复和保存该目录：

| 文件 | 内容 | 写入时机 |
| --- | --- | --- |
| `.state/latest_digest.json` | 最近一次生成的完整 schema v3 简报 | 生成成功后，与网页输出同时写入；不代表已发送 |
| `.state/latest_audit.json` | 最近一次私密筛选审计 | 生成成功后写入；不发布到网页 |
| `.state/daily_sends.json` | 按简报 `generated_at` 的北京时间日期和目标记录成功交付，包含 `published` 和合法空榜 | 飞书返回成功之后立即原子写入 |
| `.state/history.json` | 30 天已发证据 URL | 非空榜飞书成功且账本写入成功后，尽力写入 |
| `.state/events.json` | 过去 7 个北京时间日的已发事件快照 | 非空榜飞书成功且账本写入成功后，尽力原子写入 |
| `web/public/data/latest.json` | 网页读取的公开 schema v3 简报 | 本地生成时写入；生产中仅在飞书成功后提交并发布 |

发送顺序固定为：读取并校验持久化 schema v3 → 飞书发送成功 → 原子写每日账本 → 非空榜尽力写 URL 历史 → 非空榜尽力写事件历史。URL 或事件历史写入失败会告警，但不能撤销已完成的飞书交付；账本写入失败则任务失败，避免把无法去重的交付误报为完整成功。

GitHub 工作流在飞书成功后才提交公开简报，然后调用私有网页发布接口。即使后续网页发布失败，`Save delivery state` 步骤仍以 `always()` 保存已成功写入的 `.state/daily_sends.json`，自动备用运行不会重复发送。

## 合法空榜与系统失败

`no_qualifying_items` 是正常成功，不是降级错误。它表示采集和核查链路成功，但没有内容同时满足硬门槛与分榜阈值。系统会发送一张“今日无内容通过硬门槛”卡，附候选、粗筛、来源核查和主要淘汰原因；飞书成功后只写每日账本，不写 URL 或事件历史。后续自动备用运行会跳过。

以下情况属于系统失败，不能伪装为空榜，也不会写成功账本：

- 所有已配置采集来源/查询均失败。
- 有粗筛候选但全部原始来源抓取失败或不可核查。
- 模型结构化解析连续两次失败。
- 数据违反 schema v3、榜单互斥或身份约束。
- 飞书调用失败。
- 飞书成功后每日账本无法原子写入。

单个采集源或单个原始页面失败不是系统失败；只要其他来源可继续，相关候选会按证据门槛处理。

## 本地预览和持久化发送

在仓库根目录、虚拟环境和所需模型环境变量已配置的前提下：

```bash
# 完整采集、核查、生成；不发送、不写成功发送历史
ai-news-bot --dry-run

# 校验并发送刚才持久化在默认网页输出中的 schema v3
ai-news-bot --send-existing
```

使用自定义文件时，两个命令必须给出同一路径：

```bash
ai-news-bot --dry-run --web-output /tmp/ai-news-latest.json
ai-news-bot --send-existing --web-output /tmp/ai-news-latest.json
```

`--send-existing` 会真实发送飞书，运行前必须人工确认目标文件日期、`run_status`、榜单内容和当前 webhook 指向的测试群或生产群。不要使用已移除的 `--target-count`；`--skip-ai` 也不适用于证据核查流水线。

## 私密审计检查

`.state/latest_audit.json` 只用于本地或受控的 Actions 调试。它包含候选 ID、已清理的来源 URL、抓取状态、证据定位符、硬门槛原因、去重状态、分数和最终榜单；不包含完整原文或证据引文。流水线还会限制列表/字符串长度并清理常见 API key、GitHub token、JWT、Bearer token 和键值形式的密钥。

检查前先确认文件没有被 Git 跟踪：

```bash
git check-ignore -v .state/latest_audit.json
if git ls-files --error-unmatch .state/latest_audit.json 2>/dev/null; then
  echo "错误：审计文件已被 Git 跟踪"
else
  echo "审计文件未被 Git 跟踪"
fi
```

只在本机终端查看摘要，不要复制到群聊、工单、网页目录或提交记录：

```bash
python -m json.tool .state/latest_audit.json
```

若怀疑上游文本包含未覆盖的新型凭据，停止发布，先删除本地审计副本并扩展清理规则；不能把“已内置清理”视作发布私密审计的许可。

## 飞书和 URL 约束

- 飞书自定义机器人请求体必须严格小于 20,000 字节；编辑正文预算为 18,000 字节，给卡片 JSON、签名和元数据预留空间。超过预算会拒绝发送，不会截断成不完整的编辑简报。
- 每个证据 URL 在飞书卡片中最多 256 UTF-8 字节，必须是无用户名/密码的有效 HTTP(S) URL。过长或不安全的地址会使发送失败，而不是破坏原始链接后继续发送。
- 飞书 webhook 只接受 `https://open.feishu.cn` 或 `https://open.larksuite.com`。
- 公共 schema 对 `evidence_url` 的存储上限是 1,000 个字符；这不改变飞书的 256 字节发送上限。

## 自动触发的当前事实

Cloudflare Worker 是准点主触发：每天北京时间 09:05 发送类型为 `daily-ai-news` 的 `repository_dispatch`。GitHub Actions 同时保留北京时间 09:05 和 09:20 两个 `schedule` 作为平台级备用；三者共用 `.state/daily_sends.json`，成功发送后备用运行跳过。`workflow_dispatch` 是人工补发入口，不受自动去重守卫阻止。

本次流水线优化不修改任何触发时间。Cloudflare 只持有仓库专用 `GITHUB_DISPATCH_TOKEN`；飞书、模型和网页发布密钥仍只放在 GitHub Actions Secrets。

## 安全回滚

不要使用 `git reset --hard`、强推或直接覆盖 `main`。先从远端主分支创建回滚分支，并把回滚作为可审查的新提交：

```bash
git fetch origin
git log --oneline origin/main
git switch -c codex/rollback-editorial-YYYYMMDD origin/main
git revert --no-commit <最后稳定提交>..HEAD

# 运行本文要求的完整 Python、Worker 和网页验证
git status --short
git commit -m "Revert editorial pipeline to <最后稳定提交短 SHA>"
git push -u origin codex/rollback-editorial-YYYYMMDD
```

随后通过 Pull Request 审查并合并，不要在验证前改动生产密钥、Cloudflare Worker 或 `.state/`。如果范围中包含合并提交，先停止并人工确认需要回滚的父分支，再使用 `git revert -m`；不要猜测主线父编号。
