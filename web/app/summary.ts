import {
  CATEGORY_LABELS,
  type Digest,
  type GlobalEvent,
  type NewsItem,
} from "./news-data";

export type SummaryLanguage = "zh" | "en";
export type SummaryPeriod = "daily" | "weekly";

export type SummaryNarrative = {
  title: string;
  summary: string;
  category: string;
  source: string;
  url: string;
  published_at: string;
  score: number;
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
  const audience = item.affected_audience.join(language === "zh" ? "、" : ", ");
  const area = item.affected_area.join(language === "zh" ? "、" : ", ");
  const action = item.recommended_action.join(language === "zh" ? "；" : "; ");
  if (language === "zh") {
    return `${item.concrete_change} 影响：${audience}（${area}）。行动：${action}`;
  }
  return `${item.concrete_change} Affects: ${audience} (${area}). Action: ${action}`;
}

function overviewFor(
  items: SummaryNarrative[],
  language: SummaryLanguage,
  fallback: boolean,
  period: SummaryPeriod,
) {
  const categories = [...new Set(items.map((item) => item.category))];
  if (language === "zh") {
    if (period === "daily" && fallback) {
      return `过去 24 小时没有内容通过硬门槛；回看窗口内有 ${items.length} 条已核查记录，涉及${categories.join("、")}。`;
    }
    return `${period === "daily" ? "过去 24 小时" : "最近 7 天"}共有 ${items.length} 条记录通过硬门槛，涉及${categories.join("、")}。`;
  }
  if (period === "daily" && fallback) {
    return `No item passed the hard gates in the past 24 hours; ${items.length} verified records remain in the lookback window across ${categories.join(", ")}.`;
  }
  return `${items.length} records passed the hard gates in the ${period === "daily" ? "past 24 hours" : "past seven days"}, across ${categories.join(", ")}.`;
}

const GLOBAL_CATEGORY_LABELS = {
  zh: {
    models_products: "模型与产品",
    companies_business: "公司与商业",
    policy_regulation: "政策与监管",
    research_breakthroughs: "科研突破",
    adoption_society: "大众应用与社会影响",
  },
  en: {
    models_products: "Models & products",
    companies_business: "Companies & business",
    policy_regulation: "Policy & regulation",
    research_breakthroughs: "Research breakthroughs",
    adoption_society: "Adoption & society",
  },
} as const;

function globalNarrative(
  event: GlobalEvent,
  language: SummaryLanguage,
): SummaryNarrative {
  return {
    title: event.title_zh,
    summary: `${event.what_happened_zh} ${event.why_it_matters_zh}`,
    category: GLOBAL_CATEGORY_LABELS[language][event.category],
    source: event.source_name,
    url: event.source_url,
    published_at: event.published_at,
    score: event.score.total,
  };
}

function technicalNarrative(
  item: NewsItem,
  language: SummaryLanguage,
): SummaryNarrative {
  return {
    title: itemTitle(item, language),
    summary: itemSummary(item, language),
    category: CATEGORY_LABELS[language][item.category],
    source: item.source.split(" · ")[0],
    url: item.evidence_url,
    published_at: item.published_at,
    score: item.score.total,
  };
}

function uniqueByUrl(items: SummaryNarrative[]): SummaryNarrative[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.url)) return false;
    seen.add(item.url);
    return true;
  });
}

export function buildSummary(
  digest: Digest,
  period: SummaryPeriod,
  language: SummaryLanguage,
): SummaryReport {
  const generatedAt = new Date(digest.generated_at).getTime();
  const windowHours = period === "daily" ? 24 : 168;
  const globalItems = digest.global_events
    .map((event) => globalNarrative(event, language))
    .sort((a, b) => b.score - a.score);
  const technicalItems = digest.items
    .map((item) => technicalNarrative(item, language))
    .sort((a, b) => b.score - a.score);
  const allItems = uniqueByUrl([...globalItems, ...technicalItems]);
  const inWindow = allItems.filter((item) => {
    const age = generatedAt - new Date(item.published_at).getTime();
    return age >= 0 && age <= windowHours * 60 * 60 * 1000;
  });
  const fallbackUsed = period === "daily" && inWindow.length === 0;
  const pool = fallbackUsed ? allItems : inWindow;
  const selected = pool.slice(0, period === "daily" ? 3 : 5);

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
    narratives: selected,
    channel: { format: "ai-signal.summary.v1", feishu_ready: true },
  };
}
