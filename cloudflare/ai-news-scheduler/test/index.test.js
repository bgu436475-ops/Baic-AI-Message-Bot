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
