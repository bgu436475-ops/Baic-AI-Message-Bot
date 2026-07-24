import { digestUpdateSecret, getLatestDigest, saveLatestDigest } from "../../../db/digest-store";
import { isDigest } from "../../news-data";

const MAX_DIGEST_BODY_BYTES = 250_000;

type ParsedDigestRequest =
  | { payload: Parameters<typeof saveLatestDigest>[0]; response?: never }
  | { payload?: never; response: Response };

export async function parseDigestRequestBody(
  request: Request,
): Promise<ParsedDigestRequest> {
  const contentLength = Number(request.headers.get("content-length") ?? 0);
  if (Number.isFinite(contentLength) && contentLength > MAX_DIGEST_BODY_BYTES) {
    return {
      response: Response.json(
        { error: "Digest payload is too large" },
        { status: 413 },
      ),
    };
  }
  const rawBody = await request.arrayBuffer();
  if (rawBody.byteLength > MAX_DIGEST_BODY_BYTES) {
    return {
      response: Response.json(
        { error: "Digest payload is too large" },
        { status: 413 },
      ),
    };
  }
  let payload: unknown;
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(rawBody);
    payload = JSON.parse(text) as unknown;
  } catch {
    return {
      response: Response.json(
        { error: "Invalid digest payload" },
        { status: 400 },
      ),
    };
  }
  if (!isDigest(payload)) {
    return {
      response: Response.json(
        { error: "Invalid digest payload" },
        { status: 400 },
      ),
    };
  }
  return { payload };
}

export async function GET() {
  return Response.json(await getLatestDigest(), {
    headers: { "Cache-Control": "no-store" },
  });
}

export async function POST(request: Request) {
  const expectedSecret = await digestUpdateSecret();
  const suppliedSecret = request.headers.get("authorization");
  if (!expectedSecret || suppliedSecret !== `Bearer ${expectedSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const parsed = await parseDigestRequestBody(request);
  if (parsed.response) return parsed.response;
  const payload = parsed.payload;

  await saveLatestDigest(payload);
  return Response.json({
    ok: true,
    generated_at: payload.generated_at,
    item_count: payload.items.length,
  });
}
