import assert from "node:assert/strict";
import test from "node:test";

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
  assert.match(html, /Clodex IDE/);
  assert.match(html, /每天约 10 条/);
  assert.match(html, /切换到英文/);
  assert.match(html, /中/);
  assert.match(html, /EN/);
  assert.match(html, /最后检查/);
  assert.match(html, /近 24 小时/);
  assert.match(html, /一键总结/);
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
  assert.ok(digest.items.length > 0);
  assert.ok(digest.items.every((item) => item.url.startsWith("https://")));

  const postResponse = await request("/api/digest", "application/json", {
    method: "POST",
    body: JSON.stringify(digest),
  });
  assert.equal(postResponse.status, 401);
});
