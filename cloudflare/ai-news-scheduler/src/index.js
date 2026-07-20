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
