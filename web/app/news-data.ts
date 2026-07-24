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
  title_en?: string;
  summary_en?: string;
  title_zh: string;
  summary_zh: string;
  concrete_change: string;
  affected_audience: string[];
  affected_area: string[];
  recommended_action: string[];
  evidence_url: string;
  verification_status: "verified" | "unavailable" | "blocked" | "insufficient";
  event_fingerprint: string;
  update_of?: string | null;
  primary_entity: string;
  event_entities: string[];
  change_signature: string;
  version_or_metric: string;
  effective_date?: string | null;
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
  title_en?: string;
  summary_en?: string;
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
  latest_published_at?: string | null;
  fresh_count_24h?: number;
  lookback_hours?: number;
  fallback_used?: boolean;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isStringArray(value: unknown, maxLength: number, allowEmpty = true): value is string[] {
  return Array.isArray(value)
    && value.length <= maxLength
    && (allowEmpty || value.length > 0)
    && value.every(isNonEmptyString);
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isIsoDate(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "" && Number.isFinite(Date.parse(value));
}

function isHttpsUrl(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && Boolean(url.hostname);
  } catch {
    return false;
  }
}

function isCategory(value: unknown): value is Exclude<Category, "all"> {
  return ITEM_CATEGORIES.has(value as Exclude<Category, "all">);
}

function isScore(value: unknown): value is ScoreBreakdown {
  if (!isRecord(value)) return false;
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
  if (!isRecord(value)) return false;
  if (!BOARD_NAMES.includes(value.board as BoardName)) return false;
  if (expectedBoard && value.board !== expectedBoard) return false;
  if (
    !isNonEmptyString(value.candidate_id)
    || !isNonEmptyString(value.original_title)
    || !isString(value.title_zh)
    || !isString(value.summary_zh)
    || !isNonEmptyString(value.concrete_change)
    || !isStringArray(value.affected_audience, 5, false)
    || !isStringArray(value.affected_area, 5, false)
    || !isStringArray(value.recommended_action, 5, false)
    || !isHttpsUrl(value.evidence_url)
    || !VERIFICATION_STATUSES.has(value.verification_status as string)
    || !isNonEmptyString(value.event_fingerprint)
    || !isNonEmptyString(value.primary_entity)
    || !isStringArray(value.event_entities, 10, false)
    || !isNonEmptyString(value.change_signature)
    || !isString(value.version_or_metric)
    || typeof value.resource_available !== "boolean"
    || typeof value.scientific_verified !== "boolean"
    || !isNonEmptyString(value.source)
    || !isIsoDate(value.published_at)
    || !isCategory(value.category)
    || !Array.isArray(value.extra_categories)
    || value.extra_categories.length > 3
    || !value.extra_categories.every(isCategory)
    || !isScore(value.score)
  ) {
    return false;
  }
  if (value.title_en !== undefined && !isString(value.title_en)) return false;
  if (value.summary_en !== undefined && !isString(value.summary_en)) return false;
  if (value.update_of !== undefined && value.update_of !== null && !isString(value.update_of)) return false;
  if (value.effective_date !== undefined && value.effective_date !== null && !isIsoDate(value.effective_date)) return false;
  return true;
}

function isPipelineStats(
  value: unknown,
  candidateCount: number,
): value is PipelineStats {
  if (!isRecord(value) || !isRecord(value.top_rejection_reasons)) return false;
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
    ([reason, count]) => reason.trim() !== "" && isNonNegativeInteger(count),
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
  if (!isRecord(value)) return false;
  const candidate = value;
  if (!(candidate.schema_version === 3)) return false;
  if (
    (candidate.run_status !== "published" && candidate.run_status !== "no_qualifying_items")
    || !isIsoDate(candidate.generated_at)
    || !isNonNegativeInteger(candidate.candidate_count)
    || !isNonNegativeInteger(candidate.source_count)
    || candidate.source_count > candidate.candidate_count
    || (candidate.latest_published_at !== null && !isIsoDate(candidate.latest_published_at))
    || !isNonNegativeInteger(candidate.fresh_count_24h)
    || !isNonNegativeInteger(candidate.lookback_hours)
    || typeof candidate.fallback_used !== "boolean"
    || !isRecord(candidate.boards)
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
  if (!isRecord(value)) return false;
  return (
    isNonEmptyString(value.original_title)
    && isString(value.title_zh)
    && isString(value.summary_zh)
    && (value.title_en === undefined || isString(value.title_en))
    && (value.summary_en === undefined || isString(value.summary_en))
    && isHttpsUrl(value.url)
    && isNonEmptyString(value.source)
    && isIsoDate(value.published_at)
    && isCategory(value.category)
    && Array.isArray(value.extra_categories)
    && value.extra_categories.length <= 3
    && value.extra_categories.every(isCategory)
    && Number.isFinite(value.importance)
    && Number(value.importance) >= 0
    && Number(value.importance) <= 100
  );
}

export function isLegacyDigestV2(value: unknown): value is LegacyDigestV2 {
  if (!isRecord(value)) return false;
  const candidate = value;
  if (!(candidate.schema_version === 2)) return false;
  if (
    (candidate.run_status !== "published" && candidate.run_status !== "no_qualifying_items")
    || !isIsoDate(candidate.generated_at)
    || !isNonNegativeInteger(candidate.candidate_count)
    || !isNonNegativeInteger(candidate.source_count)
    || candidate.source_count > candidate.candidate_count
    || !Array.isArray(candidate.items)
    || candidate.items.length > candidate.candidate_count
    || !candidate.items.every(isLegacyItemV2)
  ) {
    return false;
  }
  if (candidate.latest_published_at !== undefined && candidate.latest_published_at !== null && !isIsoDate(candidate.latest_published_at)) return false;
  if (candidate.fresh_count_24h !== undefined && !isNonNegativeInteger(candidate.fresh_count_24h)) return false;
  if (candidate.lookback_hours !== undefined && !isNonNegativeInteger(candidate.lookback_hours)) return false;
  if (candidate.fallback_used !== undefined && typeof candidate.fallback_used !== "boolean") return false;
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

function normalizeLegacyItem(item: LegacyNewsItemV2, index: number): NewsItem {
  const candidateId = `legacy-v2-${index + 1}`;
  return {
    candidate_id: candidateId,
    board: "must_read",
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
  const mustRead = value.items.map(normalizeLegacyItem);
  return {
    schema_version: 3,
    run_status: value.run_status,
    generated_at: value.generated_at,
    candidate_count: value.candidate_count,
    source_count: value.source_count,
    latest_published_at: value.latest_published_at
      ?? (mustRead.length ? mustRead.reduce((latest, item) =>
        Date.parse(item.published_at) > Date.parse(latest) ? item.published_at : latest,
      mustRead[0].published_at) : null),
    fresh_count_24h: Math.min(value.fresh_count_24h ?? 0, mustRead.length),
    lookback_hours: value.lookback_hours ?? 36,
    fallback_used: value.fallback_used ?? false,
    boards: { must_read: mustRead, try_now: [], watch: [] },
    items: mustRead,
    pipeline_stats: {
      candidate_count: value.candidate_count,
      shortlist_count: mustRead.length,
      source_verified_count: 0,
      rejected_count: 0,
      top_rejection_reasons: {},
    },
  };
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
