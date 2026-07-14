import { digest as staticDigest, isDigest, type Digest } from "../app/news-data";

type RuntimeEnv = {
  DB?: D1Database;
  DIGEST_UPDATE_SECRET?: string;
};

const CREATE_TABLE_SQL = `
  CREATE TABLE IF NOT EXISTS latest_digest (
    id INTEGER PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )
`;

async function runtimeEnv(): Promise<RuntimeEnv> {
  try {
    const runtime = await import("cloudflare:workers");
    return runtime.env as unknown as RuntimeEnv;
  } catch {
    return {};
  }
}

async function database() {
  const db = (await runtimeEnv()).DB;
  if (!db) return null;
  await db.prepare(CREATE_TABLE_SQL).run();
  return db;
}

export async function digestUpdateSecret() {
  return (await runtimeEnv()).DIGEST_UPDATE_SECRET?.trim() ?? "";
}

export async function getLatestDigest(): Promise<Digest> {
  try {
    const db = await database();
    if (!db) return staticDigest;
    const row = await db
      .prepare("SELECT payload FROM latest_digest WHERE id = ?")
      .bind(1)
      .first<{ payload: string }>();
    if (!row) return staticDigest;
    const parsed: unknown = JSON.parse(row.payload);
    return isDigest(parsed) ? parsed : staticDigest;
  } catch {
    return staticDigest;
  }
}

export async function saveLatestDigest(digest: Digest) {
  const db = await database();
  if (!db) throw new Error("Digest database is unavailable");
  await db
    .prepare(
      `INSERT INTO latest_digest (id, payload, updated_at)
       VALUES (?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at`,
    )
    .bind(1, JSON.stringify(digest), new Date().toISOString())
    .run();
}
