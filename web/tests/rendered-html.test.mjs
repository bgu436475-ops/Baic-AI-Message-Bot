import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer } from "vite";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const PUBLISHED_DIGEST = {
  schema_version: 2,
  run_status: "published",
  generated_at: "2026-07-20T01:05:00Z",
  candidate_count: 1,
  source_count: 1,
  latest_published_at: "2026-07-20T00:30:00Z",
  fresh_count_24h: 1,
  lookback_hours: 36,
  fallback_used: false,
  items: [{
    original_title: "Example release",
    title_en: "Example release",
    summary_en: "A deterministic rendered-test item.",
    title_zh: "示例发布",
    summary_zh: "用于稳定渲染测试的确定性条目。",
    url: "https://example.com/news",
    source: "Example",
    published_at: "2026-07-20T00:30:00Z",
    category: "new_models",
    extra_categories: [],
    importance: 90,
  }],
};

const EMPTY_DIGEST = {
  schema_version: 2,
  run_status: "no_qualifying_items",
  generated_at: "2026-07-20T01:05:00Z",
  candidate_count: 0,
  source_count: 0,
  latest_published_at: null,
  fresh_count_24h: 0,
  lookback_hours: 36,
  fallback_used: false,
  items: [],
};

let vite;

before(async () => {
  vite = await createServer({
    configFile: false,
    server: { middlewareMode: true, ws: false },
  });
});

after(async () => {
  await vite?.close();
});

async function renderDashboard(digest) {
  const { NewsDashboard } = await vite.ssrLoadModule("/app/news-dashboard.tsx");
  return renderToStaticMarkup(createElement(NewsDashboard, { initialDigest: digest }));
}

async function request(path = "/", accept = "text/html", init = {}) {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(new URL(path, "http://localhost/"), {
      ...init,
      headers: { accept, ...(init.headers ?? {}) },
    }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the AI news dashboard", async () => {
  const response = await request();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>AI SIGNAL｜AI 每日情报<\/title>/i);
  assert.match(html, /让重要的 AI 进展/);
  assert.match(html, /今日值得关注/);
  assert.match(html, /三层去重/);
  assert.match(html, /<section class="feed" aria-live="polite">/);
  assert.match(html, /每天约 10 条/);
  assert.match(html, /切换到英文/);
  assert.match(html, /中/);
  assert.match(html, /EN/);
  assert.match(html, /最后检查/);
  assert.match(html, /近 24 小时/);
  assert.match(html, /一键总结/);
});

test("NewsDashboard renders published and empty v2 results deterministically", async () => {
  const { isDigest } = await vite.ssrLoadModule("/app/news-data.ts");

  assert.equal(isDigest(PUBLISHED_DIGEST), true);
  assert.equal(isDigest(EMPTY_DIGEST), true);
  assert.equal(isDigest({ ...PUBLISHED_DIGEST, items: [] }), false);
  assert.equal(isDigest({ ...EMPTY_DIGEST, items: PUBLISHED_DIGEST.items }), false);

  const publishedHtml = await renderDashboard(PUBLISHED_DIGEST);
  assert.match(publishedHtml, /<div class="story-list">/);
  assert.match(publishedHtml, /<article class="story-card">[\s\S]*?<h2>示例发布<\/h2>/);
  assert.match(publishedHtml, /aria-label="阅读原文: 示例发布"/);

  const emptyHtml = await renderDashboard(EMPTY_DIGEST);
  assert.match(emptyHtml, /<div class="empty-state">/);
  assert.match(emptyHtml, /没有找到匹配的新闻/);
  assert.doesNotMatch(emptyHtml, /class="story-card"/);
});

test("summary API exposes a Feishu-ready daily and weekly payload", async () => {
  const dailyResponse = await request("/api/summary?period=daily&lang=zh", "application/json");
  assert.equal(dailyResponse.status, 200);
  assert.match(dailyResponse.headers.get("content-type") ?? "", /^application\/json\b/i);
  const daily = await dailyResponse.json();
  assert.equal(daily.period, "daily");
  assert.equal(daily.channel.format, "ai-signal.summary.v1");
  assert.equal(daily.channel.feishu_ready, true);
  assert.ok(daily.narratives.length <= 3);
  assert.ok(daily.narratives.every((item) => item.url.startsWith("https://")));

  const weeklyResponse = await request("/api/summary?period=weekly&lang=en", "application/json");
  assert.equal(weeklyResponse.status, 200);
  const weekly = await weeklyResponse.json();
  assert.equal(weekly.period, "weekly");
  assert.equal(weekly.language, "en");
  assert.ok(weekly.narratives.length <= 5);
});

test("digest API serves a fallback and protects updates", async () => {
  const getResponse = await request("/api/digest", "application/json");
  assert.equal(getResponse.status, 200);
  assert.equal(getResponse.headers.get("cache-control"), "no-store");
  const digest = await getResponse.json();
  if (digest.schema_version === 2) {
    assert.ok(["published", "no_qualifying_items"].includes(digest.run_status));
    assert.equal(digest.run_status === "published", digest.items.length > 0);
  } else {
    assert.equal(digest.schema_version, undefined);
    assert.ok(digest.items.length > 0);
  }
  assert.ok(digest.items.every((item) => item.url.startsWith("https://")));

  const postResponse = await request("/api/digest", "application/json", {
    method: "POST",
    body: JSON.stringify(digest),
  });
  assert.equal(postResponse.status, 401);
});
