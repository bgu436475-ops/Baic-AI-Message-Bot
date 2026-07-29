import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { after, before, test } from "node:test";
import { createServer } from "vite";

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

async function parser() {
  const route = await vite.ssrLoadModule("/app/api/digest/route.ts");
  return route.parseDigestRequestBody;
}

test("raw digest parser accepts a valid body without relying on content-length", async () => {
  const parseDigestRequestBody = await parser();
  const payload = await readFile(
    new URL("./fixtures/python-empty-event-entities-v3.json", import.meta.url),
    "utf8",
  );

  const result = await parseDigestRequestBody(new Request("https://example.com/api/digest", {
    method: "POST",
    body: payload,
  }));

  assert.equal(result.response, undefined);
  assert.equal(result.payload.schema_version, 4);
  assert.deepEqual(result.payload.global_events, []);
});

test("raw digest parser rejects actual UTF-8 bodies above 250 KB with no header", async () => {
  const parseDigestRequestBody = await parser();
  const body = JSON.stringify({ value: "中".repeat(90_000) });
  const request = new Request("https://example.com/api/digest", {
    method: "POST",
    body,
  });
  request.headers.delete("content-length");

  const result = await parseDigestRequestBody(request);

  assert.equal(result.response.status, 413);
});

test("raw digest parser returns 400 for invalid JSON", async () => {
  const parseDigestRequestBody = await parser();

  const result = await parseDigestRequestBody(new Request("https://example.com/api/digest", {
    method: "POST",
    body: "{broken",
  }));

  assert.equal(result.response.status, 400);
});

test("digest route source cannot regress to request.json", async () => {
  const source = await readFile(
    new URL("../app/api/digest/route.ts", import.meta.url),
    "utf8",
  );

  assert.match(source, /await request\.arrayBuffer\(\)/);
  assert.match(source, /TextDecoder/);
  assert.match(source, /JSON\.parse/);
  assert.doesNotMatch(source, /request\.json\(/);
  assert.ok(
    source.indexOf("Unauthorized")
      < source.indexOf("parseDigestRequestBody(request)"),
  );
});
