import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const newsDataPath = new URL("../app/news-data.ts", import.meta.url);

test("digest data contract supports valid schema-v2 empty results", async () => {
  const source = await readFile(newsDataPath, "utf8");

  assert.match(source, /schema_version\??:\s*2/);
  assert.match(source, /run_status\??:\s*"published"\s*\|\s*"no_qualifying_items"/);
  assert.match(source, /candidate\.schema_version\s*===\s*2/);
  assert.match(source, /candidate\.run_status\s*===\s*"no_qualifying_items"/);
});
