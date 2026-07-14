import { CATEGORY_LABELS, type Digest, type NewsItem } from "./news-data";

export type SummaryLanguage = "zh" | "en";
export type SummaryPeriod = "daily" | "weekly";

export type SummaryNarrative = {
  title: string;
  summary: string;
  category: string;
  source: string;
  url: string;
  published_at: string;
};

export type SummaryReport = {
  period: SummaryPeriod;
  language: SummaryLanguage;
  generated_at: string;
  window_hours: number;
  fresh_item_count: number;
  fallback_used: boolean;
  headline: string;
  overview: string;
  narratives: SummaryNarrative[];
  channel: {
    format: "ai-signal.summary.v1";
    feishu_ready: true;
  };
};

function itemTitle(item: NewsItem, language: SummaryLanguage) {
  return language === "zh"
    ? item.title_zh || item.title_en || item.original_title
    : item.title_en || item.original_title;
}

function itemSummary(item: NewsItem, language: SummaryLanguage) {
  return language === "zh"
    ? item.summary_zh || item.summary_en || "—"
    : item.summary_en || item.summary_zh || "—";
}

function overviewFor(items: NewsItem[], language: SummaryLanguage, fallback: boolean, period: SummaryPeriod) {
  const categories = [...new Set(items.map((item) => CATEGORY_LABELS[language][item.category]))];
  if (language === "zh") {
    if (period === "daily" && fallback) {
      return `过去 24 小时没有足够可靠的重大更新。以下回看最近 7 天最值得注意的 ${items.length} 条信息，主要涉及${categories.join("、")}。`;
    }
    return `${period === "daily" ? "过去 24 小时" : "最近 7 天"}的核心叙事集中在${categories.join("、")}，共归纳 ${items.length} 条高价值信号。`;
  }
  if (period === "daily" && fallback) {
    return `No sufficiently reliable major update was found in the past 24 hours. These ${items.length} signals are the most relevant developments from the past seven days, spanning ${categories.join(", ")}.`;
  }
  return `The leading narratives from the ${period === "daily" ? "past 24 hours" : "past seven days"} span ${categories.join(", ")}, distilled into ${items.length} high-value signals.`;
}

export function buildSummary(
  digest: Digest,
  period: SummaryPeriod,
  language: SummaryLanguage,
): SummaryReport {
  const generatedAt = new Date(digest.generated_at).getTime();
  const windowHours = period === "daily" ? 24 : 168;
  const sorted = [...digest.items].sort((a, b) => b.importance - a.importance);
  const inWindow = sorted.filter((item) => {
    const age = generatedAt - new Date(item.published_at).getTime();
    return age >= 0 && age <= windowHours * 60 * 60 * 1000;
  });
  const fallbackUsed = period === "daily" && inWindow.length === 0;
  const selected = (fallbackUsed ? sorted : inWindow).slice(0, period === "daily" ? 3 : 5);

  return {
    period,
    language,
    generated_at: digest.generated_at,
    window_hours: windowHours,
    fresh_item_count: inWindow.length,
    fallback_used: fallbackUsed,
    headline: language === "zh"
      ? period === "daily" ? "每日 AI 叙事速览" : "每周 AI 叙事总结"
      : period === "daily" ? "Daily AI Narrative Brief" : "Weekly AI Narrative Brief",
    overview: overviewFor(selected, language, fallbackUsed, period),
    narratives: selected.map((item) => ({
      title: itemTitle(item, language),
      summary: itemSummary(item, language),
      category: CATEGORY_LABELS[language][item.category],
      source: item.source.split(" · ")[0],
      url: item.url,
      published_at: item.published_at,
    })),
    channel: { format: "ai-signal.summary.v1", feishu_ready: true },
  };
}
