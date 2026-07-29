import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { after, before, test } from "node:test";
import { createServer } from "vite";

const LEGACY_PERSISTED_DIGEST = {
  schema_version: 2,
  run_status: "published",
  generated_at: "2026-07-20T01:05:00Z",
  candidate_count: 1,
  source_count: 1,
  latest_published_at: "2099-01-01T00:00:00Z",
  fresh_count_24h: 999,
  lookback_hours: 36,
  fallback_used: false,
  items: [{
    original_title: "Legacy release",
    title_en: "Legacy release",
    summary_en: "A legacy persisted item.",
    title_zh: "旧版持久化发布",
    summary_zh: "旧版持久化条目包含具体变化。",
    url: "https://example.com/legacy-persisted",
    source: "Example",
    published_at: "2026-07-20T00:30:00Z",
    category: "new_models",
    extra_categories: [],
    importance: 90,
  }],
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

test("persisted schema v2 rows normalize through the production digest-store boundary", async () => {
  const store = await vite.ssrLoadModule("/db/digest-store.ts");
  assert.equal(typeof store.parseStoredDigest, "function");

  const normalized = store.parseStoredDigest(JSON.stringify(LEGACY_PERSISTED_DIGEST));

  assert.equal(normalized.schema_version, 4);
  assert.deepEqual(normalized.global_events, []);
  assert.equal(normalized.latest_published_at, "2026-07-20T00:30:00Z");
  assert.equal(normalized.fresh_count_24h, 1);
  assert.equal(normalized.items[0].evidence_url, "https://example.com/legacy-persisted");
});

test("persisted malformed rows fail closed so the caller can use its static fallback", async () => {
  const store = await vite.ssrLoadModule("/db/digest-store.ts");
  assert.equal(typeof store.parseStoredDigest, "function");
  assert.equal(store.parseStoredDigest("{broken"), null);
  assert.equal(store.parseStoredDigest(JSON.stringify({
    ...LEGACY_PERSISTED_DIGEST,
    unknown: true,
  })), null);
});

test("actual eight-item production schema v2 digest normalizes into board capacities", async () => {
  const store = await vite.ssrLoadModule("/db/digest-store.ts");
  const payload = execFileSync(
    "git",
    ["show", "4128027:web/public/data/latest.json"],
    { cwd: new URL("../..", import.meta.url), encoding: "utf8" },
  );
  const legacy = JSON.parse(payload);

  const normalized = store.parseStoredDigest(payload);

  assert.notEqual(normalized, null);
  assert.equal(normalized.boards.must_read.length, 5);
  assert.equal(normalized.boards.try_now.length, 3);
  assert.equal(normalized.boards.watch.length, 0);
  assert.deepEqual(
    normalized.items.map((item) => item.original_title),
    legacy.items.map((item) => item.original_title),
  );
  assert.deepEqual(
    normalized.items.map((item) => item.evidence_url),
    legacy.items.map((item) => item.url),
  );
  assert.deepEqual(
    normalized.items.map((item) => item.summary_zh),
    legacy.items.map((item) => item.summary_zh),
  );
});

test("legacy compatibility supports at most ten ordered items", async () => {
  const store = await vite.ssrLoadModule("/db/digest-store.ts");
  const items = Array.from(
    { length: 10 },
    (_, index) => ({
      ...LEGACY_PERSISTED_DIGEST.items[0],
      original_title: `Legacy ${index + 1}`,
      title_en: `Legacy ${index + 1}`,
      url: `https://example.com/legacy-${index + 1}`,
      published_at: index === 9
        ? "2026-07-20T01:00:00Z"
        : "2026-07-18T00:30:00Z",
    }),
  );
  const normalized = store.parseStoredDigest(JSON.stringify({
    ...LEGACY_PERSISTED_DIGEST,
    candidate_count: 10,
    items,
  }));

  assert.deepEqual(
    [
      normalized.boards.must_read.length,
      normalized.boards.try_now.length,
      normalized.boards.watch.length,
    ],
    [5, 3, 2],
  );
  assert.deepEqual(
    normalized.items.map((item) => item.original_title),
    items.map((item) => item.original_title),
  );
  assert.equal(normalized.latest_published_at, "2026-07-20T01:00:00Z");
  assert.equal(normalized.fresh_count_24h, 1);
  assert.equal(store.parseStoredDigest(JSON.stringify({
    ...LEGACY_PERSISTED_DIGEST,
    candidate_count: 11,
    items: [...items, {
      ...items[0],
      original_title: "Legacy 11",
      title_en: "Legacy 11",
      url: "https://example.com/legacy-11",
    }],
  })), null);
});
