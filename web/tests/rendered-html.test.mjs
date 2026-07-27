import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { readFile } from "node:fs/promises";
import { createServer } from "vite";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

function item(board, id, overrides = {}) {
  return {
    candidate_id: id,
    board,
    original_title: `${id} release`,
    title_en: `${id} release`,
    summary_en: `${id} changes a concrete API limit.`,
    title_zh: `${id} 发布`,
    summary_zh: `${id} 带来可核查的 API 变化。`,
    concrete_change: `${id} API 上限从 10 提升到 20。`,
    affected_audience: ["API 开发者"],
    affected_area: ["调用配额"],
    recommended_action: [`本周验证 ${id} API 配额`],
    evidence_url: `https://example.com/${id}`,
    verification_status: "verified",
    event_fingerprint: `example|${id}|api-limit|20|2026-07-20`,
    update_of: null,
    primary_entity: "Example",
    product_or_model: id,
    event_entities: ["Example", id],
    change_signature: "api-limit",
    version_or_metric: "20",
    effective_date: "2026-07-20",
    resource_available: true,
    scientific_verified: false,
    source: "Example",
    published_at: "2026-07-20T00:30:00Z",
    category: "new_models",
    extra_categories: [],
    score: {
      relevance: 25,
      actionability: 20,
      specificity: 15,
      information_gain: 15,
      evidence_quality: 15,
      time_sensitivity: 10,
      penalties: 0,
      total: 100,
    },
    ...overrides,
  };
}

const MUST_READ_ITEM = item("must_read", "Model-X");
const TRY_NOW_ITEM = item("try_now", "Tool-Y", {
  category: "ai_coding",
  score: {
    relevance: 20,
    actionability: 20,
    specificity: 15,
    information_gain: 12,
    evidence_quality: 15,
    time_sensitivity: 8,
    penalties: 0,
    total: 90,
  },
});
const WATCH_ITEM = item("watch", "Policy-Z", {
  category: "industry_business",
  verification_status: "unavailable",
  resource_available: false,
  score: {
    relevance: 18,
    actionability: 12,
    specificity: 10,
    information_gain: 10,
    evidence_quality: 5,
    time_sensitivity: 8,
    penalties: -5,
    total: 58,
  },
});

const PUBLISHED_DIGEST = {
  schema_version: 3,
  run_status: "published",
  generated_at: "2026-07-20T01:05:00Z",
  candidate_count: 8,
  source_count: 3,
  latest_published_at: "2026-07-20T00:30:00Z",
  fresh_count_24h: 3,
  lookback_hours: 36,
  fallback_used: false,
  boards: {
    must_read: [MUST_READ_ITEM],
    try_now: [TRY_NOW_ITEM],
    watch: [WATCH_ITEM],
  },
  items: [MUST_READ_ITEM, TRY_NOW_ITEM, WATCH_ITEM],
  pipeline_stats: {
    candidate_count: 8,
    shortlist_count: 3,
    source_verified_count: 2,
    rejected_count: 0,
    top_rejection_reasons: {},
  },
};

const EMPTY_DIGEST = {
  schema_version: 3,
  run_status: "no_qualifying_items",
  generated_at: "2026-07-20T01:05:00Z",
  candidate_count: 8,
  source_count: 3,
  latest_published_at: null,
  fresh_count_24h: 0,
  lookback_hours: 36,
  fallback_used: false,
  boards: { must_read: [], try_now: [], watch: [] },
  items: [],
  pipeline_stats: {
    candidate_count: 8,
    shortlist_count: 3,
    source_verified_count: 2,
    rejected_count: 3,
    top_rejection_reasons: { missing_action: 3 },
  },
};

const LEGACY_V2_ITEM = {
  original_title: "Legacy release",
  title_en: "Legacy release",
  summary_en: "A legacy rendered-test item.",
  title_zh: "旧版发布",
  summary_zh: "用于兼容性测试的旧版条目。",
  url: "https://example.com/legacy",
  source: "Example",
  published_at: "2026-07-20T00:30:00Z",
  category: "new_models",
  extra_categories: [],
  importance: 90,
};

const PUBLISHED_V2_DIGEST = {
  schema_version: 2,
  run_status: "published",
  generated_at: "2026-07-20T01:05:00Z",
  candidate_count: 1,
  source_count: 1,
  latest_published_at: "2099-01-01T00:00:00Z",
  fresh_count_24h: 999,
  lookback_hours: 36,
  fallback_used: false,
  items: [LEGACY_V2_ITEM],
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
  assert.match(html, /每天严格核查高决策价值 AI 信息，宁缺毋滥/);
  assert.doesNotMatch(html, /每天约 10 条/);
  assert.match(html, /切换到英文/);
  assert.match(html, /中/);
  assert.match(html, /EN/);
  assert.match(html, /最后检查/);
  assert.match(html, /近 24 小时/);
  assert.match(html, /一键总结/);
  assert.doesNotMatch(html, /class="story-index">00</);
});

test("schedule and dedupe copy states operational semantics accurately", async () => {
  const source = await readFile(
    new URL("../app/news-dashboard.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /09:05/);
  assert.match(source, /trigger|触发/i);
  assert.match(source, /title similarity|标题相似度/i);
  assert.match(source, /structured-event|结构化事件/i);
  assert.doesNotMatch(source, /09:00/);
  assert.doesNotMatch(source, /semantic clustering|语义聚类/i);
});

test("NewsDashboard renders schema v3 boards, evidence and legal empty results", async () => {
  const { isDigest, normalizeDigest } = await vite.ssrLoadModule("/app/news-data.ts");

  assert.equal(isDigest(PUBLISHED_DIGEST), true);
  assert.equal(isDigest(EMPTY_DIGEST), true);
  assert.equal(isDigest({ ...PUBLISHED_DIGEST, items: [] }), false);
  assert.equal(isDigest({ ...EMPTY_DIGEST, items: PUBLISHED_DIGEST.items }), false);

  const publishedHtml = await renderDashboard(PUBLISHED_DIGEST);
  assert.match(publishedHtml, /今日必看/);
  assert.match(publishedHtml, /值得试用/);
  assert.match(publishedHtml, /观察项/);
  assert.match(publishedHtml, /具体变化/);
  assert.match(publishedHtml, /建议行动/);
  assert.match(publishedHtml, /https:\/\/example\.com\/Model-X/);
  assert.match(publishedHtml, /已核验证据/);
  assert.match(publishedHtml, /证据暂未完整核验/);
  assert.match(publishedHtml, /总分 100/);

  const emptyHtml = await renderDashboard(EMPTY_DIGEST);
  assert.match(emptyHtml, /<div class="empty-state">/);
  assert.match(emptyHtml, /今日无内容通过硬门槛/);
  assert.match(emptyHtml, /候选 8/);
  assert.match(emptyHtml, /粗筛 3/);
  assert.match(emptyHtml, /已核查 2/);
  assert.match(emptyHtml, /淘汰 3/);
  assert.doesNotMatch(emptyHtml, /class="story-card"/);

  assert.equal(isDigest(PUBLISHED_V2_DIGEST), false);
  const normalized = normalizeDigest(PUBLISHED_V2_DIGEST);
  assert.equal(normalized.schema_version, 3);
  assert.equal(normalized.boards.must_read.length, 1);
  assert.equal(normalized.boards.must_read[0].evidence_url, "https://example.com/legacy");
  assert.equal(normalized.latest_published_at, LEGACY_V2_ITEM.published_at);
  assert.equal(normalized.fresh_count_24h, 1);
  assert.equal(isDigest(normalized), true);
});

test("schema v3 validator rejects caps, identity conflicts, unsafe evidence and impossible counts", async () => {
  const { isDigest } = await vite.ssrLoadModule("/app/news-data.ts");
  const clone = () => structuredClone(PUBLISHED_DIGEST);

  const tooMany = clone();
  tooMany.boards.must_read = Array.from({ length: 6 }, (_, index) =>
    item("must_read", `cap-${index}`));
  tooMany.items = [...tooMany.boards.must_read, ...tooMany.boards.try_now, ...tooMany.boards.watch];
  assert.equal(isDigest(tooMany), false);

  const wrongBoard = clone();
  wrongBoard.boards.must_read[0].board = "try_now";
  assert.equal(isDigest(wrongBoard), false);

  const duplicateCandidate = clone();
  duplicateCandidate.boards.try_now[0].candidate_id = duplicateCandidate.boards.must_read[0].candidate_id;
  duplicateCandidate.items = [
    ...duplicateCandidate.boards.must_read,
    ...duplicateCandidate.boards.try_now,
    ...duplicateCandidate.boards.watch,
  ];
  assert.equal(isDigest(duplicateCandidate), false);

  const duplicateFingerprint = clone();
  duplicateFingerprint.boards.try_now[0].event_fingerprint =
    duplicateFingerprint.boards.must_read[0].event_fingerprint;
  duplicateFingerprint.items = [
    ...duplicateFingerprint.boards.must_read,
    ...duplicateFingerprint.boards.try_now,
    ...duplicateFingerprint.boards.watch,
  ];
  assert.equal(isDigest(duplicateFingerprint), false);

  const reordered = clone();
  reordered.items = [...reordered.items].reverse();
  assert.equal(isDigest(reordered), false);

  const unsafeEvidence = clone();
  unsafeEvidence.boards.must_read[0].evidence_url = "http://example.com/Model-X";
  unsafeEvidence.items[0].evidence_url = "http://example.com/Model-X";
  assert.equal(isDigest(unsafeEvidence), false);

  const negativeCount = clone();
  negativeCount.pipeline_stats.rejected_count = -1;
  assert.equal(isDigest(negativeCount), false);

  const impossibleCount = clone();
  impossibleCount.pipeline_stats.source_verified_count = 4;
  assert.equal(isDigest(impossibleCount), false);

  const impossibleAccounting = clone();
  impossibleAccounting.pipeline_stats.rejected_count = 1;
  assert.equal(isDigest(impossibleAccounting), false);

  const missingLatest = clone();
  missingLatest.latest_published_at = null;
  assert.equal(isDigest(missingLatest), false);

  assert.equal(isDigest({ ...EMPTY_DIGEST, latest_published_at: PUBLISHED_DIGEST.generated_at }), false);
});

test("schema v3 accepts the full 5 plus 3 plus 3 board capacity", async () => {
  const { isDigest } = await vite.ssrLoadModule("/app/news-data.ts");
  const mustRead = Array.from(
    { length: 5 },
    (_, index) => item("must_read", `must-${index}`),
  );
  const tryNow = Array.from(
    { length: 3 },
    (_, index) => item("try_now", `try-${index}`),
  );
  const watch = Array.from(
    { length: 3 },
    (_, index) => item("watch", `watch-${index}`),
  );
  const items = [...mustRead, ...tryNow, ...watch];
  const digest = {
    ...structuredClone(PUBLISHED_DIGEST),
    candidate_count: 11,
    fresh_count_24h: 11,
    boards: { must_read: mustRead, try_now: tryNow, watch },
    items,
    pipeline_stats: {
      candidate_count: 11,
      shortlist_count: 11,
      source_verified_count: 11,
      rejected_count: 0,
      top_rejection_reasons: {},
    },
  };

  assert.equal(isDigest(digest), true);
});

test("schema v2 compatibility is narrow and rejects malformed legacy data", async () => {
  const { isLegacyDigestV2, normalizeDigest } = await vite.ssrLoadModule("/app/news-data.ts");

  assert.equal(isLegacyDigestV2(PUBLISHED_V2_DIGEST), true);
  assert.throws(() => normalizeDigest({ ...PUBLISHED_V2_DIGEST, schema_version: undefined }));
  assert.throws(() => normalizeDigest({ ...PUBLISHED_V2_DIGEST, items: [] }));
  assert.throws(() => normalizeDigest({
    ...PUBLISHED_V2_DIGEST,
    items: [{ ...LEGACY_V2_ITEM, url: "http://example.com/legacy" }],
  }));
  assert.throws(() => normalizeDigest({ ...PUBLISHED_V2_DIGEST, unknown: true }));
  const missingField = structuredClone(PUBLISHED_V2_DIGEST);
  delete missingField.fallback_used;
  assert.throws(() => normalizeDigest(missingField));
});

test("schema validator requires real RFC3339 datetimes and calendar dates", async () => {
  const { isDigest } = await vite.ssrLoadModule("/app/news-data.ts");
  const updateStory = (digest, field, value) => {
    digest.boards.must_read[0][field] = value;
    digest.items.find((story) => story.candidate_id === MUST_READ_ITEM.candidate_id)[field] = value;
  };

  for (const invalid of [
    "1",
    "2026-02-30T01:05:00Z",
    "2026-07-20T01:05:00",
    "2026-07-20T25:00:00Z",
    "2026-07-20T01:05:00+24:00",
  ]) {
    assert.equal(isDigest({ ...structuredClone(PUBLISHED_DIGEST), generated_at: invalid }), false);
    const invalidPublished = structuredClone(PUBLISHED_DIGEST);
    updateStory(invalidPublished, "published_at", invalid);
    assert.equal(isDigest(invalidPublished), false);
  }

  for (const invalid of ["1", "2026-02-30", "2026-07-20T00:00:00Z"]) {
    const invalidEffective = structuredClone(PUBLISHED_DIGEST);
    updateStory(invalidEffective, "effective_date", invalid);
    assert.equal(isDigest(invalidEffective), false);
  }

  const precisePythonDatetime = structuredClone(PUBLISHED_DIGEST);
  precisePythonDatetime.generated_at = "2026-07-20T01:05:00.366572+00:00";
  assert.equal(isDigest(precisePythonDatetime), true);

  const leapDate = structuredClone(PUBLISHED_DIGEST);
  updateStory(leapDate, "effective_date", "2024-02-29");
  assert.equal(isDigest(leapDate), true);

  for (const invalid of [
    "http://127.0.0.1/evidence",
    "http://example.com/evidence",
    "https://user:password@example.com/evidence",
    `https://example.com/${"x".repeat(240)}`,
  ]) {
    const invalidUrl = structuredClone(PUBLISHED_DIGEST);
    updateStory(invalidUrl, "evidence_url", invalid);
    assert.equal(isDigest(invalidUrl), false);
  }
  const validContract = structuredClone(PUBLISHED_DIGEST);
  updateStory(validContract, "evidence_url", "https://example.com/evidence");
  updateStory(validContract, "effective_date", "2024-02-29");
  assert.equal(isDigest(validContract), true);
});

test("web accepts the exact schema v3 fixture generated and validated by Python", async () => {
  const { isDigest, normalizeDigest } = await vite.ssrLoadModule("/app/news-data.ts");
  const fixture = JSON.parse(await readFile(
    new URL("./fixtures/python-empty-event-entities-v3.json", import.meta.url),
    "utf8",
  ));

  assert.deepEqual(fixture.items[0].event_entities, []);
  assert.deepEqual(fixture.items[1].event_entities, [""]);
  assert.equal(isDigest(fixture), true);
  assert.equal(normalizeDigest(fixture), fixture);

  const tooManyEntities = structuredClone(fixture);
  const elevenEntities = Array.from({ length: 11 }, (_, index) => `entity-${index}`);
  tooManyEntities.boards.must_read[0].event_entities = elevenEntities;
  tooManyEntities.items[0].event_entities = elevenEntities;
  assert.equal(isDigest(tooManyEntities), false);

  const overlongEntity = structuredClone(fixture);
  overlongEntity.boards.must_read[0].event_entities = ["x".repeat(161)];
  overlongEntity.items[0].event_entities = ["x".repeat(161)];
  assert.equal(isDigest(overlongEntity), false);
});

test("schema validators reject unknown, missing and over-cap nested fields", async () => {
  const { isDigest } = await vite.ssrLoadModule("/app/news-data.ts");
  const updateStory = (digest, mutate) => {
    const boardStory = digest.boards.must_read[0];
    const flatStory = digest.items.find(
      (story) => story.candidate_id === MUST_READ_ITEM.candidate_id,
    );
    mutate(boardStory);
    mutate(flatStory);
  };

  assert.equal(isDigest({ ...structuredClone(PUBLISHED_DIGEST), unknown: true }), false);

  const unknownBoard = structuredClone(PUBLISHED_DIGEST);
  unknownBoard.boards.unknown = [];
  assert.equal(isDigest(unknownBoard), false);

  const unknownItem = structuredClone(PUBLISHED_DIGEST);
  updateStory(unknownItem, (story) => { story.unknown = true; });
  assert.equal(isDigest(unknownItem), false);

  const unknownScore = structuredClone(PUBLISHED_DIGEST);
  updateStory(unknownScore, (story) => { story.score.unknown = 1; });
  assert.equal(isDigest(unknownScore), false);

  const unknownStats = structuredClone(PUBLISHED_DIGEST);
  unknownStats.pipeline_stats.unknown = 1;
  assert.equal(isDigest(unknownStats), false);

  const missingItemField = structuredClone(PUBLISHED_DIGEST);
  updateStory(missingItemField, (story) => { delete story.title_en; });
  assert.equal(isDigest(missingItemField), false);

  const overlongCandidateId = structuredClone(PUBLISHED_DIGEST);
  updateStory(overlongCandidateId, (story) => { story.candidate_id = "x".repeat(161); });
  assert.equal(isDigest(overlongCandidateId), false);

  const tooManyActions = structuredClone(PUBLISHED_DIGEST);
  updateStory(tooManyActions, (story) => {
    story.recommended_action = Array.from({ length: 6 }, () => "Test");
  });
  assert.equal(isDigest(tooManyActions), false);

  const overlongAction = structuredClone(PUBLISHED_DIGEST);
  updateStory(overlongAction, (story) => {
    story.recommended_action = ["x".repeat(301)];
  });
  assert.equal(isDigest(overlongAction), false);
});

test("unverified evidence uses a neutral label for every warning status", async () => {
  const { evidenceLabel } = await vite.ssrLoadModule("/app/news-dashboard.tsx");
  const watchItems = ["unavailable", "blocked", "insufficient"].map((status, index) =>
    item("watch", `Watch-${index}`, {
      verification_status: status,
      resource_available: false,
      score: {
        relevance: 18,
        actionability: 12,
        specificity: 10,
        information_gain: 10,
        evidence_quality: 5,
        time_sensitivity: 8,
        penalties: -5,
        total: 58,
      },
    }));
  const digest = {
    ...structuredClone(PUBLISHED_DIGEST),
    candidate_count: 3,
    source_count: 1,
    boards: { must_read: [], try_now: [], watch: watchItems },
    items: watchItems,
    pipeline_stats: {
      candidate_count: 3,
      shortlist_count: 3,
      source_verified_count: 0,
      rejected_count: 0,
      top_rejection_reasons: {},
    },
  };

  const html = await renderDashboard(digest);
  assert.equal((html.match(/证据暂未完整核验/g) ?? []).length, 3);
  assert.equal((html.match(/>证据来源 /g) ?? []).length, 3);
  assert.doesNotMatch(html, /已核验证据/);
  assert.equal(evidenceLabel("verified", "en"), "Verified evidence");
  assert.equal(evidenceLabel("unavailable", "en"), "Evidence source");
  assert.equal(evidenceLabel("blocked", "en"), "Evidence source");
  assert.equal(evidenceLabel("insufficient", "en"), "Evidence source");
});

test("summary ranks immutably and uses change, impact and action without vague filler", async () => {
  const { buildSummary } = await vite.ssrLoadModule("/app/summary.ts");
  const digest = structuredClone(PUBLISHED_DIGEST);
  digest.items.reverse();
  const originalOrder = digest.items.map((story) => story.candidate_id);

  const report = buildSummary(digest, "weekly", "zh");

  assert.deepEqual(digest.items.map((story) => story.candidate_id), originalOrder);
  assert.deepEqual(report.narratives.map((story) => story.score), [100, 90, 58]);
  assert.match(report.narratives[0].summary, new RegExp(MUST_READ_ITEM.concrete_change));
  assert.match(report.narratives[0].summary, /API 开发者/);
  assert.match(report.narratives[0].summary, /本周验证 Model-X API 配额/);
  for (const prohibited of [
    "这对行业具有重要意义",
    "这展示了 AI 的巨大潜力",
    "这预示着未来的发展方向",
    "这可能推动相关应用",
    "值得持续关注",
  ]) {
    assert.doesNotMatch(JSON.stringify(report), new RegExp(prohibited));
  }
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
  assert.equal(digest.schema_version, 3);
  assert.ok(["published", "no_qualifying_items"].includes(digest.run_status));
  assert.equal(digest.run_status === "published", digest.items.length > 0);
  assert.ok(digest.items.every((item) => item.evidence_url.startsWith("https://")));

  const postResponse = await request("/api/digest", "application/json", {
    method: "POST",
    body: JSON.stringify(digest),
  });
  assert.equal(postResponse.status, 401);
});
