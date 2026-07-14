import { digestUpdateSecret, getLatestDigest, saveLatestDigest } from "../../../db/digest-store";
import { isDigest } from "../../news-data";

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

  const contentLength = Number(request.headers.get("content-length") ?? 0);
  if (contentLength > 250_000) {
    return Response.json({ error: "Digest payload is too large" }, { status: 413 });
  }

  const payload: unknown = await request.json().catch(() => null);
  if (!isDigest(payload)) {
    return Response.json({ error: "Invalid digest payload" }, { status: 400 });
  }

  await saveLatestDigest(payload);
  return Response.json({
    ok: true,
    generated_at: payload.generated_at,
    item_count: payload.items.length,
  });
}
