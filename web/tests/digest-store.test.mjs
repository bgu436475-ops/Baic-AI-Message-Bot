import assert from "node:assert/strict";
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

  assert.equal(normalized.schema_version, 3);
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
