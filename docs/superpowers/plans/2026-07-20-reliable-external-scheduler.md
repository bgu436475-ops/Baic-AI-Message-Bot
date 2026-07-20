# Reliable External Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Cloudflare-owned 09:05 trigger for the production AI news workflow while preserving GitHub schedules as fallback and guaranteeing at most one automatic send per Beijing calendar day.

**Architecture:** A Cloudflare Worker Cron Trigger posts a `daily-ai-news` repository dispatch event to the production repository. GitHub Actions accepts that event alongside the existing two UTC schedules, while `daily_guard` treats both event types as automatic retries and leaves `workflow_dispatch` as an explicit manual override. The Worker contains no Feishu or model credentials and keeps its single repository-scoped GitHub token in a Cloudflare Secret.

**Tech Stack:** Python 3.11+, pytest 8, GitHub Actions YAML, JavaScript ES modules, Node.js 20+ built-in test runner, Cloudflare Workers and Wrangler 4.

## Global Constraints

- External primary trigger time is `01:05 UTC`, which is `09:05 Asia/Shanghai`.
- Existing GitHub schedules `5 1 * * *` and `20 1 * * *` remain enabled as fallbacks.
- `schedule` and `repository_dispatch` are automatic events subject to same-day deduplication.
- `workflow_dispatch` remains a manual force-run event.
- The repository dispatch event type is exactly `daily-ai-news`.
- The GitHub token is stored only as the Cloudflare Secret `GITHUB_DISPATCH_TOKEN`.
- The token is limited to `bgu436475-ops/Baic-AI-Message-Bot` with `Contents: Read and write`.
- Worker development and deployment use Node.js 20 or newer.
- No Feishu webhook, signing secret, model key, GitHub token, or Cloudflare credential may be committed or printed.
- Each independently testable feature is committed separately with a short commit message.
- The existing 09:35 health check remains read-only and never clicks Run workflow or sends a replacement digest.

---

## File Structure

- `src/ai_news_bot/daily_guard.py`: classifies automatic versus manual workflow events and prevents same-day automatic duplicates.
- `tests/test_daily_guard.py`: verifies event classification, local-date deduplication, and workflow trigger declarations.
- `.github/workflows/daily-ai-news.yml`: accepts the external repository dispatch while retaining both schedules and the manual trigger.
- `cloudflare/ai-news-scheduler/src/index.js`: builds and sends the authenticated GitHub dispatch request with bounded retries.
- `cloudflare/ai-news-scheduler/test/index.test.js`: validates request construction, success, authentication failures, and retry behavior without network calls.
- `cloudflare/ai-news-scheduler/package.json`: exposes repeatable test, local scheduled-handler, and deploy commands.
- `cloudflare/ai-news-scheduler/wrangler.jsonc`: configures the Worker, required secret, logs, and daily UTC cron.
- `cloudflare/ai-news-scheduler/.gitignore`: excludes local Worker secrets and generated state.
- `cloudflare/ai-news-scheduler/README.md`: provides exact token, secret, deploy, and validation steps.
- `README.md`: describes the production trigger hierarchy and corrected Beijing times.

---

### Task 1: Accept External Automatic Dispatches Without Duplicate Sends

**Files:**
- Modify: `tests/test_daily_guard.py`
- Modify: `src/ai_news_bot/daily_guard.py`
- Modify: `.github/workflows/daily-ai-news.yml`

**Interfaces:**
- Consumes: `should_run_daily_digest(event_name, digest_path, history_path=None, timezone="Asia/Shanghai", now=None) -> bool`.
- Produces: `AUTOMATED_EVENTS = frozenset({"schedule", "repository_dispatch"})` and a workflow trigger for `repository_dispatch.types = [daily-ai-news]`.

- [ ] **Step 1: Add failing guard and workflow tests**

Append these tests to `tests/test_daily_guard.py`:

```python
def test_repository_dispatch_skips_digest_generated_today(tmp_path: Path) -> None:
    digest = tmp_path / "latest.json"
    _write_digest(digest, "2026-07-15T00:59:00Z")

    assert not should_run_daily_digest(
        "repository_dispatch",
        digest,
        now=datetime(2026, 7, 15, 1, 22, tzinfo=UTC),
    )


def test_repository_dispatch_runs_when_today_has_no_digest(tmp_path: Path) -> None:
    digest = tmp_path / "latest.json"
    _write_digest(digest, "2026-07-14T15:59:00Z")

    assert should_run_daily_digest(
        "repository_dispatch",
        digest,
        now=datetime(2026, 7, 15, 1, 5, tzinfo=UTC),
    )


def test_workflow_accepts_external_dispatch_and_preserves_fallbacks() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github/workflows/daily-ai-news.yml"
    ).read_text(encoding="utf-8")

    assert "repository_dispatch:" in workflow
    assert "types: [daily-ai-news]" in workflow
    assert 'cron: "5 1 * * *"' in workflow
    assert 'cron: "20 1 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest tests/test_daily_guard.py -q
```

Expected: the repository-dispatch duplicate test fails because the current guard treats every non-`schedule` event as manual, and the workflow assertion fails because `repository_dispatch` is absent.

- [ ] **Step 3: Implement automatic event classification**

Add this constant after the imports in `src/ai_news_bot/daily_guard.py`:

```python
AUTOMATED_EVENTS = frozenset({"schedule", "repository_dispatch"})
```

Replace the start of `should_run_daily_digest` with:

```python
    """Allow manual runs, but skip automatic retries after today's digest exists."""
    if event_name not in AUTOMATED_EVENTS:
        return True
```

- [ ] **Step 4: Add the repository dispatch workflow trigger**

Change the top of `.github/workflows/daily-ai-news.yml` to:

```yaml
name: Daily AI News

on:
  schedule:
    - cron: "5 1 * * *" # 09:05 Asia/Shanghai (UTC+8)
    - cron: "20 1 * * *" # 09:20 Asia/Shanghai (UTC+8)
  repository_dispatch:
    types: [daily-ai-news]
  workflow_dispatch:
```

Leave the existing concurrency group and all job steps unchanged.

- [ ] **Step 5: Run focused and full Python tests and verify GREEN**

Run:

```bash
pytest tests/test_daily_guard.py -q
pytest -q
```

Expected: all daily guard tests pass, followed by the complete suite with zero failures.

- [ ] **Step 6: Commit the repository-side feature**

Run:

```bash
git add src/ai_news_bot/daily_guard.py tests/test_daily_guard.py .github/workflows/daily-ai-news.yml
git commit -m "Support external scheduled dispatches"
```

Expected: one commit containing only the workflow trigger, deduplication behavior, and their tests.

---

### Task 2: Build the Cloudflare Cron Dispatcher

**Files:**
- Create: `cloudflare/ai-news-scheduler/src/index.js`
- Create: `cloudflare/ai-news-scheduler/test/index.test.js`
- Create: `cloudflare/ai-news-scheduler/package.json`
- Create: `cloudflare/ai-news-scheduler/wrangler.jsonc`
- Create: `cloudflare/ai-news-scheduler/.gitignore`

**Interfaces:**
- Consumes: Cloudflare binding `env.GITHUB_DISPATCH_TOKEN: string` and `controller.scheduledTime: number`.
- Produces: `buildDispatchRequest(token, scheduledTime) -> [string, RequestInit]`, `dispatchDailyNews(env, scheduledTime, fetchImpl=fetch, waitImpl=wait) -> Promise<void>`, and the default Cloudflare `scheduled(controller, env)` handler.

- [ ] **Step 1: Create the package and failing unit tests**

Create `cloudflare/ai-news-scheduler/package.json`:

```json
{
  "name": "ai-news-scheduler",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test",
    "dev": "wrangler dev --test-scheduled",
    "deploy": "wrangler deploy"
  },
  "devDependencies": {
    "wrangler": "^4.0.0"
  }
}
```

Create `cloudflare/ai-news-scheduler/test/index.test.js`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDispatchRequest,
  dispatchDailyNews,
} from "../src/index.js";

const TOKEN = "test-token-not-a-real-secret";
const SCHEDULED_TIME = Date.UTC(2026, 6, 20, 1, 5, 0);

test("builds the scoped repository dispatch request", () => {
  const [url, options] = buildDispatchRequest(TOKEN, SCHEDULED_TIME);

  assert.equal(
    url,
    "https://api.github.com/repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches",
  );
  assert.equal(options.method, "POST");
  assert.equal(options.headers.Authorization, `Bearer ${TOKEN}`);
  assert.deepEqual(JSON.parse(options.body), {
    event_type: "daily-ai-news",
    client_payload: {
      source: "cloudflare-cron",
      scheduled_at: "2026-07-20T01:05:00.000Z",
    },
  });
});

test("accepts GitHub 204 without retrying", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    return new Response(null, { status: 204 });
  };

  await dispatchDailyNews(
    { GITHUB_DISPATCH_TOKEN: TOKEN },
    SCHEDULED_TIME,
    fetchImpl,
    async () => {},
  );

  assert.equal(calls, 1);
});

test("does not retry authentication failures or reveal the token", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    return new Response("bad credentials", { status: 403 });
  };

  await assert.rejects(
    dispatchDailyNews(
      { GITHUB_DISPATCH_TOKEN: TOKEN },
      SCHEDULED_TIME,
      fetchImpl,
      async () => {},
    ),
    (error) => {
      assert.match(error.message, /403/);
      assert.doesNotMatch(error.message, new RegExp(TOKEN));
      return true;
    },
  );
  assert.equal(calls, 1);
});

test("retries transient GitHub failures up to three attempts", async () => {
  const statuses = [500, 502, 204];
  const waits = [];
  const fetchImpl = async () =>
    new Response(null, { status: statuses.shift() });

  await dispatchDailyNews(
    { GITHUB_DISPATCH_TOKEN: TOKEN },
    SCHEDULED_TIME,
    fetchImpl,
    async (milliseconds) => waits.push(milliseconds),
  );

  assert.deepEqual(statuses, []);
  assert.deepEqual(waits, [1000, 2000]);
});

test("retries network failures up to three attempts", async () => {
  let calls = 0;
  const waits = [];
  const fetchImpl = async () => {
    calls += 1;
    if (calls < 3) {
      throw new TypeError("network unavailable");
    }
    return new Response(null, { status: 204 });
  };

  await dispatchDailyNews(
    { GITHUB_DISPATCH_TOKEN: TOKEN },
    SCHEDULED_TIME,
    fetchImpl,
    async (milliseconds) => waits.push(milliseconds),
  );

  assert.equal(calls, 3);
  assert.deepEqual(waits, [1000, 2000]);
});

test("rejects a missing Cloudflare secret before making a request", async () => {
  let calls = 0;
  await assert.rejects(
    dispatchDailyNews(
      {},
      SCHEDULED_TIME,
      async () => {
        calls += 1;
        return new Response(null, { status: 204 });
      },
      async () => {},
    ),
    /GITHUB_DISPATCH_TOKEN is not configured/,
  );
  assert.equal(calls, 0);
});
```

- [ ] **Step 2: Run the Worker tests and verify RED**

Run:

```bash
cd cloudflare/ai-news-scheduler
npm test
```

Expected: the test command fails because `src/index.js` does not exist.

- [ ] **Step 3: Implement request construction and bounded retries**

Create `cloudflare/ai-news-scheduler/src/index.js`:

```javascript
const DISPATCH_URL =
  "https://api.github.com/repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches";
const MAX_ATTEMPTS = 3;

const wait = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

export function buildDispatchRequest(token, scheduledTime) {
  return [
    DISPATCH_URL,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "baic-ai-news-scheduler",
        "X-GitHub-Api-Version": "2026-03-10",
      },
      body: JSON.stringify({
        event_type: "daily-ai-news",
        client_payload: {
          source: "cloudflare-cron",
          scheduled_at: new Date(scheduledTime).toISOString(),
        },
      }),
    },
  ];
}

export async function dispatchDailyNews(
  env,
  scheduledTime,
  fetchImpl = fetch,
  waitImpl = wait,
) {
  const token = env.GITHUB_DISPATCH_TOKEN;
  if (!token) {
    throw new Error("GITHUB_DISPATCH_TOKEN is not configured");
  }

  const [url, options] = buildDispatchRequest(token, scheduledTime);
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    let response;
    try {
      response = await fetchImpl(url, options);
    } catch {
      if (attempt === MAX_ATTEMPTS) {
        throw new Error(
          "GitHub repository dispatch failed after 3 network attempts",
        );
      }
      await waitImpl(attempt * 1000);
      continue;
    }
    if (response.status === 204) {
      return;
    }

    const responseSummary = (await response.text()).slice(0, 300);
    const retryable = response.status === 429 || response.status >= 500;
    if (!retryable || attempt === MAX_ATTEMPTS) {
      throw new Error(
        `GitHub repository dispatch failed with ${response.status}: ${responseSummary}`,
      );
    }
    await waitImpl(attempt * 1000);
  }
}

export default {
  async scheduled(controller, env) {
    await dispatchDailyNews(env, controller.scheduledTime);
  },
};
```

- [ ] **Step 4: Add Cloudflare deployment configuration and secret exclusions**

Create `cloudflare/ai-news-scheduler/wrangler.jsonc`:

```jsonc
{
  "$schema": "./node_modules/wrangler/config-schema.json",
  "name": "baic-ai-news-scheduler",
  "main": "src/index.js",
  "compatibility_date": "2026-07-20",
  "triggers": {
    "crons": ["5 1 * * *"]
  },
  "observability": {
    "enabled": true
  },
  "secrets": {
    "required": ["GITHUB_DISPATCH_TOKEN"]
  }
}
```

Create `cloudflare/ai-news-scheduler/.gitignore`:

```gitignore
.dev.vars
.env
.wrangler/
node_modules/
```

- [ ] **Step 5: Run Worker tests and verify GREEN**

Run:

```bash
cd cloudflare/ai-news-scheduler
npm test
```

Expected: six tests pass with zero failures and no credential values in output.

- [ ] **Step 6: Install Wrangler and validate its configuration**

Run:

```bash
cd cloudflare/ai-news-scheduler
npm install
npx wrangler deploy --dry-run
```

Expected: npm creates `package-lock.json`, tests remain green, and Wrangler validates the Worker bundle without deploying it.

- [ ] **Step 7: Commit the Worker feature**

Run:

```bash
git add cloudflare/ai-news-scheduler
git commit -m "Add Cloudflare news scheduler"
```

Expected: one commit containing Worker source, tests, configuration, lockfile, and secret exclusions.

---

### Task 3: Document Secure Deployment and Production Timing

**Files:**
- Create: `cloudflare/ai-news-scheduler/README.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Worker commands `npm test`, `npx wrangler login`, `npx wrangler secret put GITHUB_DISPATCH_TOKEN`, and `npm run deploy`.
- Produces: an operator procedure that never stores the token in a file or GitHub secret output.

- [ ] **Step 1: Add a failing documentation contract test**

Append this test to `tests/test_daily_guard.py`:

```python
def test_readme_documents_external_primary_and_github_fallback() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "Cloudflare Worker" in readme
    assert "09:05" in readme
    assert "09:20" in readme
    assert "GITHUB_DISPATCH_TOKEN" in readme
    assert 'cron: "7 9 * * *"' not in readme
    assert 'cron: "22 9 * * *"' not in readme
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest tests/test_daily_guard.py::test_readme_documents_external_primary_and_github_fallback -q
```

Expected: failure because the production README still documents the obsolete 09:07 and 09:22 schedule.

- [ ] **Step 3: Create the Worker deployment guide**

Create `cloudflare/ai-news-scheduler/README.md` with these exact operational sections:

```markdown
# AI News Scheduler

This Worker triggers `bgu436475-ops/Baic-AI-Message-Bot` every day at 01:05 UTC / 09:05 Asia/Shanghai. GitHub Actions retains its native schedules as fallbacks.

## 1. Create the GitHub token

Create a fine-grained personal access token for only `bgu436475-ops/Baic-AI-Message-Bot`. Grant `Contents: Read and write`; do not grant organization or account permissions.

## 2. Test locally

```bash
npm install
npm test
npx wrangler deploy --dry-run
```

## 3. Sign in and save the secret

```bash
npx wrangler login
npx wrangler secret put GITHUB_DISPATCH_TOKEN
```

Paste the token only into Wrangler's protected prompt. Do not create `.env`, `.dev.vars`, screenshots, or chat messages containing the token.

## 4. Deploy

```bash
npm run deploy
```

After deployment, confirm that the Cron Trigger is `5 1 * * *` and observability is enabled.

## 5. Validate without sending a second digest

Use Wrangler's local scheduled route only before the day's digest, or rely on the next real 09:05 run. In GitHub Actions, the external run must show event `repository_dispatch`; a later `schedule` run must be skipped by the daily guard after the day's digest exists.
```

- [ ] **Step 4: Replace the obsolete root README schedule section**

Replace the section beginning `## 每天 9:00 自动发送` through the paragraph before `## 调整筛选` with:

```markdown
## 每天 09:05 自动发送

生产环境采用双通道触发：

1. Cloudflare Worker 在每天北京时间 09:05 调用 GitHub `repository_dispatch`，作为准点主触发。
2. GitHub Actions 保留北京时间 09:05 和 09:20 两个原生 `schedule`，作为平台级备用。
3. `schedule` 与 `repository_dispatch` 共用每日去重；当天成功生成或发送后，后续自动运行直接跳过。
4. 手动 `Run workflow` 使用 `workflow_dispatch`，仍可显式补发。

Cloudflare 只保存仓库专用的 `GITHUB_DISPATCH_TOKEN`，不保存飞书、模型或网页密钥。Worker 的部署和验证步骤见 `cloudflare/ai-news-scheduler/README.md`。
```

- [ ] **Step 5: Verify documentation and the complete Python suite**

Run:

```bash
pytest tests/test_daily_guard.py -q
pytest -q
rg -n "7 9 \* \* \*|22 9 \* \* \*|09:07|09:22" README.md cloudflare/ai-news-scheduler/README.md
```

Expected: both pytest commands pass; the final search returns no obsolete schedule references.

- [ ] **Step 6: Commit the documentation feature**

Run:

```bash
git add README.md tests/test_daily_guard.py cloudflare/ai-news-scheduler/README.md
git commit -m "Document reliable scheduler deployment"
```

Expected: one commit containing the deployment guide, corrected production timing, and its documentation contract test.

---

### Task 4: Verify, Publish, Deploy, and Update Monitoring

**Files:**
- Verify: `.github/workflows/daily-ai-news.yml`
- Verify: `src/ai_news_bot/daily_guard.py`
- Verify: `cloudflare/ai-news-scheduler/src/index.js`
- Verify: `README.md`
- External update: Codex automation `ai`

**Interfaces:**
- Consumes: the three feature commits from Tasks 1–3, Cloudflare authentication, and a fine-grained GitHub token supplied only through Wrangler's protected prompt.
- Produces: production `main` with external dispatch support, a deployed `baic-ai-news-scheduler` Worker, and a 09:35 monitor that accepts `repository_dispatch` as the primary event.

- [ ] **Step 1: Run the complete verification suite from a clean tree**

Run:

```bash
pytest -q
cd cloudflare/ai-news-scheduler
npm test
npx wrangler deploy --dry-run
cd ../..
git diff --check
git status --short
```

Expected: all Python and Worker tests pass, Wrangler validates the bundle, `git diff --check` is silent, and `git status --short` is empty.

- [ ] **Step 2: Scan tracked files for credential patterns**

Run:

```bash
git grep -nE "(github_pat_|ghp_|hooks\.larksuite\.com/open-apis/bot|hooks\.feishu\.cn/open-apis/bot)" -- . ':!docs/superpowers/plans/2026-07-20-reliable-external-scheduler.md'
```

Expected: no matches.

- [ ] **Step 3: Push the reviewed branch**

Run:

```bash
git push -u origin codex/reliable-external-scheduler
```

Expected: the branch appears in `bgu436475-ops/Baic-AI-Message-Bot` with the design, repository trigger, Worker, and documentation commits.

- [ ] **Step 4: Publish the verified commits to production main**

After confirming `origin/main` has not advanced unexpectedly, run:

```bash
git fetch origin main
git rebase origin/main
git push origin HEAD:main
```

Expected: production `main` advances to the verified scheduler commit without a force push.

- [ ] **Step 5: Create and save the least-privilege GitHub token**

In GitHub, create a fine-grained personal access token with:

```text
Owner: bgu436475-ops
Repository access: Only select repositories → Baic-AI-Message-Bot
Repository permissions: Contents → Read and write
Expiration: 90 days
```

Then run from `cloudflare/ai-news-scheduler`:

```bash
npx wrangler login
npx wrangler secret put GITHUB_DISPATCH_TOKEN
```

Expected: Cloudflare confirms the secret without echoing its value.

- [ ] **Step 6: Deploy the Worker**

Run:

```bash
cd cloudflare/ai-news-scheduler
npm run deploy
```

Expected: Cloudflare reports Worker `baic-ai-news-scheduler`, Cron Trigger `5 1 * * *`, and a successful deployment version.

- [ ] **Step 7: Update the existing 09:35 read-only monitor**

Update automation `ai` so its primary-success rule accepts a successful `repository_dispatch` event named `daily-ai-news` around 09:05 with a valid same-day remote digest. Retain the current 09:20 `schedule` fallback test, the remote-main-only digest validation, and the prohibitions against Run workflow, automatic resend, repository changes, secret changes, or Feishu changes.

Expected: viewing automation `ai` shows the new repository-dispatch rule and the existing safety prohibitions.

- [ ] **Step 8: Perform a non-sending production inspection**

Open the production workflow page and verify:

```text
repository_dispatch type: daily-ai-news
schedule 1: 5 1 * * *
schedule 2: 20 1 * * *
manual trigger: workflow_dispatch
concurrency group: daily-ai-news
```

Do not invoke the Worker scheduled handler after a digest has already been sent. Use the next natural 09:05 window for the first production send verification.

- [ ] **Step 9: Observe the first real cycle**

At the next Beijing 09:05 window, verify a `repository_dispatch` run appears within five minutes, succeeds, updates the remote digest for that Beijing date, and sends only one Feishu message. At 09:20, verify any fallback run is skipped when the day's digest already exists. At 09:35, verify the monitor records normal status or produces the defined Chinese alert.

Expected: one automatic digest, a valid same-day remote JSON file, and no duplicate Feishu card.

---

## Plan Self-Review Result

- Spec coverage: repository trigger, daily deduplication, manual override, Worker retry behavior, least-privilege secret storage, deployment, monitoring, and next-day verification are each assigned to a task.
- Placeholder scan: no deferred implementation markers or unspecified error handling remain.
- Type consistency: `repository_dispatch`, `daily-ai-news`, `GITHUB_DISPATCH_TOKEN`, `buildDispatchRequest`, and `dispatchDailyNews` use identical names across tests, implementation, configuration, and deployment steps.
