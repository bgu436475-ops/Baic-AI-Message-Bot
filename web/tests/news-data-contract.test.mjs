import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const newsDataPath = new URL("../app/news-data.ts", import.meta.url);

test("digest data contract declares schema v4 with narrow v3 and v2 compatibility", async () => {
  const source = await readFile(newsDataPath, "utf8");

  assert.match(source, /schema_version:\s*4/);
  assert.match(source, /schema_version:\s*3/);
  assert.match(source, /global_events:\s*GlobalEvent\[\]/);
  assert.match(source, /boards:\s*DigestBoards/);
  assert.match(source, /must_read:\s*NewsItem\[\]/);
  assert.match(source, /candidate\.schema_version\s*===\s*3/);
  assert.match(source, /candidate\.items\.length\s*===\s*flattened\.length/);
  assert.match(source, /candidate\.schema_version\s*===\s*2/);
  assert.match(source, /normalizeDigest\(latestDigest\)/);
  assert.doesNotMatch(source, /latestDigest\s+as\s+Digest/);
});
