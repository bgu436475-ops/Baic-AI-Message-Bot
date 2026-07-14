import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const latestDigest = sqliteTable("latest_digest", {
  id: integer("id").primaryKey(),
  payload: text("payload").notNull(),
  updatedAt: text("updated_at").notNull(),
});
