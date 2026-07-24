import latestDigest from "../public/data/latest.json";

export type Category =
  | "all"
  | "new_models"
  | "ai_coding"
  | "agents"
  | "image_video"
  | "comfyui"
  | "open_source"
  | "mcp"
  | "skills"
  | "industry_business";

export type BoardName = "must_read" | "try_now" | "watch";

export type ScoreBreakdown = {
  relevance: number;
  actionability: number;
  specificity: number;
  information_gain: number;
  evidence_quality: number;
  time_sensitivity: number;
  penalties: number;
  total: number;
};

export type NewsItem = {
  candidate_id: string;
  board: BoardName;
  original_title: string;
  title_en: string;
  summary_en: string;
  title_zh: string;
  summary_zh: string;
  concrete_change: string;
  affected_audience: string[];
  affected_area: string[];
  recommended_action: string[];
  evidence_url: string;
  verification_status: "verified" | "unavailable" | "blocked" | "insufficient";
  event_fingerprint: string;
  update_of: string | null;
  primary_entity: string;
  product_or_model: string;
  event_entities: string[];
  change_signature: string;
  version_or_metric: string;
  effective_date: string | null;
  resource_available: boolean;
  scientific_verified: boolean;
  source: string;
  published_at: string;
  category: Exclude<Category, "all">;
  extra_categories: Exclude<Category, "all">[];
  score: ScoreBreakdown;
};

export type DigestBoards = {
  must_read: NewsItem[];
  try_now: NewsItem[];
  watch: NewsItem[];
};

export type PipelineStats = {
  candidate_count: number;
  shortlist_count: number;
  source_verified_count: number;
  rejected_count: number;
  top_rejection_reasons: Record<string, number>;
};

export type Digest = {
  schema_version: 3;
  run_status: "published" | "no_qualifying_items";
  generated_at: string;
  candidate_count: number;
  source_count: number;
  latest_published_at: string | null;
  fresh_count_24h: number;
  lookback_hours: number;
  fallback_used: boolean;
  boards: DigestBoards;
  items: NewsItem[];
  pipeline_stats: PipelineStats;
};

type LegacyNewsItemV2 = {
  original_title: string;
  title_en: string;
  summary_en: string;
  title_zh: string;
  summary_zh: string;
  url: string;
  source: string;
  published_at: string;
  category: Exclude<Category, "all">;
  extra_categories: Exclude<Category, "all">[];
  importance: number;
};

export type LegacyDigestV2 = {
  schema_version: 2;
  run_status: "published" | "no_qualifying_items";
  generated_at: string;
  candidate_count: number;
  source_count: number;
  latest_published_at: string | null;
  fresh_count_24h: number;
  lookback_hours: number;
  fallback_used: boolean;
  items: LegacyNewsItemV2[];
};

const ITEM_CATEGORIES = new Set<Exclude<Category, "all">>([
  "new_models",
  "ai_coding",
  "agents",
  "image_video",
  "comfyui",
  "open_source",
  "mcp",
  "skills",
  "industry_business",
]);
const BOARD_NAMES: BoardName[] = ["must_read", "try_now", "watch"];
const VERIFICATION_STATUSES = new Set([
  "verified",
  "unavailable",
  "blocked",
  "insufficient",
]);
const DIGEST_KEYS = new Set([
  "schema_version", "run_status", "generated_at", "candidate_count",
  "source_count", "latest_published_at", "fresh_count_24h",
  "lookback_hours", "fallback_used", "boards", "items", "pipeline_stats",
]);
const BOARD_KEYS = new Set(["must_read", "try_now", "watch"]);
const ITEM_KEYS = new Set([
  "candidate_id", "board", "original_title", "title_en", "summary_en",
  "title_zh", "summary_zh", "concrete_change", "affected_audience",
  "affected_area", "recommended_action", "evidence_url",
  "verification_status", "event_fingerprint", "update_of", "primary_entity",
  "product_or_model", "event_entities", "change_signature", "version_or_metric",
  "effective_date", "resource_available", "scientific_verified", "source",
  "published_at", "category", "extra_categories", "score",
]);
const SCORE_KEYS = new Set([
  "relevance", "actionability", "specificity", "information_gain",
  "evidence_quality", "time_sensitivity", "penalties", "total",
]);
const PIPELINE_KEYS = new Set([
  "candidate_count", "shortlist_count", "source_verified_count",
  "rejected_count", "top_rejection_reasons",
]);
const LEGACY_DIGEST_KEYS = new Set([
  "schema_version", "run_status", "generated_at", "candidate_count",
  "source_count", "latest_published_at", "fresh_count_24h",
  "lookback_hours", "fallback_used", "items",
]);
const LEGACY_ITEM_KEYS = new Set([
  "original_title", "title_en", "summary_en", "title_zh", "summary_zh",
  "url", "source", "published_at", "category", "extra_categories",
  "importance",
]);
const RFC3339_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/;
const DATE_ONLY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: Set<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isBoundedString(
  value: unknown,
  maxLength: number,
  requireContent = false,
): value is string {
  return typeof value === "string"
    && value.length <= maxLength
    && (!requireContent || value.trim().length > 0);
}

function isStringArray(
  value: unknown,
  maxLength: number,
  itemMaxLength: number,
  allowEmpty = true,
  requireItemContent = true,
): value is string[] {
  return Array.isArray(value)
    && value.length <= maxLength
    && (allowEmpty || value.length > 0)
    && value.every((item) =>
      isBoundedString(item, itemMaxLength, requireItemContent));
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function calendarPartsAreReal(year: number, month: number, day: number): boolean {
  if (month < 1 || month > 12 || day < 1 || day > 31) return false;
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(0, 0, 0, 0);
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function isDateOnly(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = DATE_ONLY_PATTERN.exec(value);
  if (!match) return false;
  return calendarPartsAreReal(Number(match[1]), Number(match[2]), Number(match[3]));
}

function isRfc3339DateTime(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = RFC3339_PATTERN.exec(value);
  if (!match) return false;
  const [
    , yearText, monthText, dayText, hourText, minuteText, secondText,
    fraction = "", zone,
  ] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (
    !calendarPartsAreReal(year, month, day)
    || hour > 23
    || minute > 59
    || second > 59
  ) {
    return false;
  }
  let offsetMinutes = 0;
  if (zone !== "Z") {
    const offsetHour = Number(zone.slice(1, 3));
    const offsetMinute = Number(zone.slice(4, 6));
    if (offsetHour > 23 || offsetMinute > 59) return false;
    offsetMinutes = (offsetHour * 60 + offsetMinute) * (zone[0] === "+" ? 1 : -1);
  }
  const local = new Date(0);
  local.setUTCFullYear(year, month - 1, day);
  local.setUTCHours(
    hour,
    minute,
    second,
    Number((fraction + "000").slice(0, 3)),
  );
  const expected = local.getTime() - offsetMinutes * 60_000;
  return Number.isFinite(expected) && Date.parse(value) === expected;
}

function isHttpsUrl(value: unknown): value is string {
  if (
    !isBoundedString(value, 1000, true)
    || value !== value.trim()
    || new TextEncoder().encode(value).byteLength > 256
    || [...value].some((character) => {
      const code = character.codePointAt(0) ?? 0;
      return code < 32 || code === 127;
    })
  ) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && Boolean(url.hostname)
      && !url.username
      && !url.password;
  } catch {
    return false;
  }
}

function isCategory(value: unknown): value is Exclude<Category, "all"> {
  return ITEM_CATEGORIES.has(value as Exclude<Category, "all">);
}

function isScore(value: unknown): value is ScoreBreakdown {
  if (!isRecord(value) || !hasExactKeys(value, SCORE_KEYS)) return false;
  const caps = {
    relevance: 25,
    actionability: 20,
    specificity: 15,
    information_gain: 15,
    evidence_quality: 15,
    time_sensitivity: 10,
  } as const;
  for (const [field, cap] of Object.entries(caps)) {
    const score = value[field];
    if (!isNonNegativeInteger(score) || score > cap) return false;
  }
  if (!Number.isInteger(value.penalties) || Number(value.penalties) > 0) return false;
  if (!isNonNegativeInteger(value.total) || value.total > 100) return false;
  const calculated = Math.max(
    0,
    Object.keys(caps).reduce((total, field) => total + Number(value[field]), 0)
      + Number(value.penalties),
  );
  return value.total === calculated;
}

function isNewsItem(value: unknown, expectedBoard?: BoardName): value is NewsItem {
  if (!isRecord(value) || !hasExactKeys(value, ITEM_KEYS)) return false;
  if (!BOARD_NAMES.includes(value.board as BoardName)) return false;
  if (expectedBoard && value.board !== expectedBoard) return false;
  if (
    !isBoundedString(value.candidate_id, 160, true)
    || !isBoundedString(value.original_title, 120, true)
    || !isBoundedString(value.title_en, 120)
    || !isBoundedString(value.summary_en, 320)
    || !isBoundedString(value.title_zh, 80)
    || !isBoundedString(value.summary_zh, 220)
    || !isBoundedString(value.concrete_change, 1200, true)
    || !isStringArray(value.affected_audience, 5, 160, false)
    || !isStringArray(value.affected_area, 5, 160, false)
    || !isStringArray(value.recommended_action, 5, 300, false)
    || !isHttpsUrl(value.evidence_url)
    || !VERIFICATION_STATUSES.has(value.verification_status as string)
    || !isBoundedString(value.event_fingerprint, 1000, true)
    || !isBoundedString(value.primary_entity, 160, true)
    || !isBoundedString(value.product_or_model, 160)
    || !isStringArray(value.event_entities, 10, 160, true, false)
    || !isBoundedString(value.change_signature, 160, true)
    || !isBoundedString(value.version_or_metric, 120)
    || typeof value.resource_available !== "boolean"
    || typeof value.scientific_verified !== "boolean"
    || !isBoundedString(value.source, 120, true)
    || !isRfc3339DateTime(value.published_at)
    || !isCategory(value.category)
    || !Array.isArray(value.extra_categories)
    || value.extra_categories.length > 3
    || !value.extra_categories.every(isCategory)
    || !isScore(value.score)
  ) {
    return false;
  }
  if (value.update_of !== null && !isBoundedString(value.update_of, 500)) return false;
  if (value.effective_date !== null && !isDateOnly(value.effective_date)) return false;
  return true;
}

function isPipelineStats(
  value: unknown,
  candidateCount: number,
): value is PipelineStats {
  if (
    !isRecord(value)
    || !hasExactKeys(value, PIPELINE_KEYS)
    || !isRecord(value.top_rejection_reasons)
  ) return false;
  const { shortlist_count, source_verified_count, rejected_count } = value;
  if (
    value.candidate_count !== candidateCount
    || !isNonNegativeInteger(shortlist_count)
    || !isNonNegativeInteger(source_verified_count)
    || !isNonNegativeInteger(rejected_count)
    || shortlist_count > candidateCount
    || source_verified_count > shortlist_count
    || rejected_count > shortlist_count
  ) {
    return false;
  }
  return Object.entries(value.top_rejection_reasons).every(
    ([reason, count]) => isBoundedString(reason, 160, true) && isNonNegativeInteger(count),
  );
}

function deepEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) && Array.isArray(right)) {
    return left.length === right.length
      && left.every((value, index) => deepEqual(value, right[index]));
  }
  if (isRecord(left) && isRecord(right)) {
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return deepEqual(leftKeys, rightKeys)
      && leftKeys.every((key) => deepEqual(left[key], right[key]));
  }
  return false;
}

export function isDigest(value: unknown): value is Digest {
  if (!isRecord(value) || !hasExactKeys(value, DIGEST_KEYS)) return false;
  const candidate = value;
  if (!(candidate.schema_version === 3)) return false;
  if (
    (candidate.run_status !== "published" && candidate.run_status !== "no_qualifying_items")
    || !isRfc3339DateTime(candidate.generated_at)
    || !isNonNegativeInteger(candidate.candidate_count)
    || !isNonNegativeInteger(candidate.source_count)
    || candidate.source_count > candidate.candidate_count
    || (candidate.latest_published_at !== null && !isRfc3339DateTime(candidate.latest_published_at))
    || !isNonNegativeInteger(candidate.fresh_count_24h)
    || !isNonNegativeInteger(candidate.lookback_hours)
    || typeof candidate.fallback_used !== "boolean"
    || !isRecord(candidate.boards)
    || !hasExactKeys(candidate.boards, BOARD_KEYS)
    || !Array.isArray(candidate.items)
    || !isPipelineStats(candidate.pipeline_stats, candidate.candidate_count)
  ) {
    return false;
  }

  const boards = candidate.boards;
  if (
    !Array.isArray(boards.must_read)
    || boards.must_read.length > 5
    || !boards.must_read.every((item) => isNewsItem(item, "must_read"))
    || !Array.isArray(boards.try_now)
    || boards.try_now.length > 3
    || !boards.try_now.every((item) => isNewsItem(item, "try_now"))
    || !Array.isArray(boards.watch)
    || boards.watch.length > 3
    || !boards.watch.every((item) => isNewsItem(item, "watch"))
  ) {
    return false;
  }

  const flattened = [...boards.must_read, ...boards.try_now, ...boards.watch];
  if (!(candidate.items.length === flattened.length)) return false;
  if (
    candidate.items.length > candidate.candidate_count
    || candidate.fresh_count_24h > candidate.items.length
    || candidate.pipeline_stats.shortlist_count
      !== flattened.length + candidate.pipeline_stats.rejected_count
    || !candidate.items.every((item) => isNewsItem(item))
    || !candidate.items.every((item, index) => deepEqual(item, flattened[index]))
  ) {
    return false;
  }
  const candidateIds = flattened.map((item) => item.candidate_id);
  const fingerprints = flattened.map((item) => item.event_fingerprint);
  if (
    new Set(candidateIds).size !== candidateIds.length
    || new Set(fingerprints).size !== fingerprints.length
  ) {
    return false;
  }
  if (candidate.run_status === "published") {
    if (candidate.latest_published_at === null) return false;
    const newestItem = Math.max(...flattened.map((item) => Date.parse(item.published_at)));
    if (Date.parse(candidate.latest_published_at) !== newestItem) return false;
  } else if (candidate.latest_published_at !== null || candidate.fresh_count_24h !== 0) {
    return false;
  }
  return (
    (candidate.run_status === "published" && flattened.length > 0)
    || (candidate.run_status === "no_qualifying_items" && flattened.length === 0)
  );
}

function isLegacyItemV2(value: unknown): value is LegacyNewsItemV2 {
  if (!isRecord(value) || !hasExactKeys(value, LEGACY_ITEM_KEYS)) return false;
  return (
    isBoundedString(value.original_title, 120, true)
    && isBoundedString(value.title_zh, 80)
    && isBoundedString(value.summary_zh, 220)
    && isBoundedString(value.title_en, 120)
    && isBoundedString(value.summary_en, 320)
    && isHttpsUrl(value.url)
    && isBoundedString(value.source, 120, true)
    && isRfc3339DateTime(value.published_at)
    && isCategory(value.category)
    && Array.isArray(value.extra_categories)
    && value.extra_categories.length <= 3
    && value.extra_categories.every(isCategory)
    && Number.isInteger(value.importance)
    && Number(value.importance) >= 1
    && Number(value.importance) <= 100
  );
}

export function isLegacyDigestV2(value: unknown): value is LegacyDigestV2 {
  if (!isRecord(value) || !hasExactKeys(value, LEGACY_DIGEST_KEYS)) return false;
  const candidate = value;
  if (!(candidate.schema_version === 2)) return false;
  if (
    (candidate.run_status !== "published" && candidate.run_status !== "no_qualifying_items")
    || !isRfc3339DateTime(candidate.generated_at)
    || !isNonNegativeInteger(candidate.candidate_count)
    || !isNonNegativeInteger(candidate.source_count)
    || candidate.source_count > candidate.candidate_count
    || !Array.isArray(candidate.items)
    || candidate.items.length > 10
    || candidate.items.length > candidate.candidate_count
    || !candidate.items.every(isLegacyItemV2)
  ) {
    return false;
  }
  if (candidate.latest_published_at !== null && !isRfc3339DateTime(candidate.latest_published_at)) return false;
  if (!isNonNegativeInteger(candidate.fresh_count_24h)) return false;
  if (!isNonNegativeInteger(candidate.lookback_hours)) return false;
  if (typeof candidate.fallback_used !== "boolean") return false;
  return (
    (candidate.run_status === "published" && candidate.items.length > 0)
    || (candidate.run_status === "no_qualifying_items" && candidate.items.length === 0)
  );
}

function compatibilityScore(importance: number): ScoreBreakdown {
  let remaining = Math.round(Math.min(100, Math.max(0, importance)));
  const take = (cap: number) => {
    const value = Math.min(cap, remaining);
    remaining -= value;
    return value;
  };
  const relevance = take(25);
  const actionability = take(20);
  const specificity = take(15);
  const information_gain = take(15);
  const evidence_quality = take(15);
  const time_sensitivity = take(10);
  return {
    relevance,
    actionability,
    specificity,
    information_gain,
    evidence_quality,
    time_sensitivity,
    penalties: 0,
    total: relevance + actionability + specificity + information_gain
      + evidence_quality + time_sensitivity,
  };
}

function normalizeLegacyItem(
  item: LegacyNewsItemV2,
  index: number,
  board: BoardName,
): NewsItem {
  const candidateId = `legacy-v2-${index + 1}`;
  return {
    candidate_id: candidateId,
    board,
    original_title: item.original_title,
    title_en: item.title_en,
    summary_en: item.summary_en,
    title_zh: item.title_zh,
    summary_zh: item.summary_zh,
    concrete_change: item.summary_zh || item.summary_en || item.original_title,
    affected_audience: ["旧版简报读者"],
    affected_area: [CATEGORY_LABELS.zh[item.category]],
    recommended_action: ["打开原始来源，核查具体变化后再决定是否行动"],
    evidence_url: item.url,
    verification_status: "insufficient",
    event_fingerprint: `legacy-v2|${index + 1}|${item.url}`,
    update_of: null,
    primary_entity: item.source,
    product_or_model: "",
    event_entities: [item.source],
    change_signature: "legacy-v2-import",
    version_or_metric: "",
    effective_date: null,
    resource_available: false,
    scientific_verified: false,
    source: item.source,
    published_at: item.published_at,
    category: item.category,
    extra_categories: item.extra_categories,
    score: compatibilityScore(item.importance),
  };
}

export function normalizeDigest(value: unknown): Digest {
  if (isDigest(value)) return value;
  if (!isLegacyDigestV2(value)) {
    throw new TypeError("Invalid AI news digest");
  }
  const normalizedItems = value.items.map((item, index) => normalizeLegacyItem(
    item,
    index,
    index < 5 ? "must_read" : index < 8 ? "try_now" : "watch",
  ));
  const mustRead = normalizedItems.slice(0, 5);
  const tryNow = normalizedItems.slice(5, 8);
  const watch = normalizedItems.slice(8, 11);
  const generatedAt = Date.parse(value.generated_at);
  const latestPublishedAt = normalizedItems.length
    ? normalizedItems.reduce((latest, item) =>
      Date.parse(item.published_at) > Date.parse(latest) ? item.published_at : latest,
    normalizedItems[0].published_at)
    : null;
  const freshCount24h = normalizedItems.filter((item) => {
    const age = generatedAt - Date.parse(item.published_at);
    return age >= 0 && age <= 24 * 60 * 60 * 1000;
  }).length;
  const normalized: Digest = {
    schema_version: 3,
    run_status: value.run_status,
    generated_at: value.generated_at,
    candidate_count: value.candidate_count,
    source_count: value.source_count,
    latest_published_at: latestPublishedAt,
    fresh_count_24h: freshCount24h,
    lookback_hours: value.lookback_hours,
    fallback_used: value.fallback_used,
    boards: { must_read: mustRead, try_now: tryNow, watch },
    items: normalizedItems,
    pipeline_stats: {
      candidate_count: value.candidate_count,
      shortlist_count: normalizedItems.length,
      source_verified_count: 0,
      rejected_count: 0,
      top_rejection_reasons: {},
    },
  };
  if (!isDigest(normalized)) {
    throw new TypeError("Legacy digest cannot be normalized safely");
  }
  return normalized;
}

export const CATEGORY_LABELS: Record<"zh" | "en", Record<Category, string>> = {
  zh: {
    all: "全部", new_models: "新模型", ai_coding: "AI 编程", agents: "Agent",
    image_video: "图片 / 视频", comfyui: "ComfyUI", open_source: "开源项目",
    mcp: "MCP", skills: "Skill", industry_business: "行业 / 商业",
  },
  en: {
    all: "All", new_models: "New Models", ai_coding: "AI Coding", agents: "Agents",
    image_video: "Image / Video", comfyui: "ComfyUI", open_source: "Open Source",
    mcp: "MCP", skills: "Skills", industry_business: "Industry / Business",
  },
};

export const categories = Object.keys(CATEGORY_LABELS.zh) as Category[];
export const digest = normalizeDigest(latestDigest);
