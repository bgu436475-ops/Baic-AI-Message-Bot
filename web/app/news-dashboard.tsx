"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CATEGORY_LABELS,
  categories,
  type Category,
  type Digest,
  type NewsItem,
} from "./news-data";
import { buildSummary, type SummaryPeriod } from "./summary";

type Language = "zh" | "en";

const COPY = {
  zh: {
    brandAria: "AI Signal 首页",
    title: "AI 每日情报",
    update: "每日重查全球信源 · 09:00 精选",
    headlineA: "让重要的 AI 进展，",
    headlineB: "先于噪音抵达。",
    intro: "实时跟进全球官方发布、开发者社区与开源生态；当天没有可靠新进展时，回看最近 7 天最重要的信息。",
    selected: "本期精选",
    candidates: "候选信息",
    sources: "信源覆盖",
    filterAria: "筛选新闻",
    freshnessLabel: "信息时效",
    checkedAt: "最后检查",
    currentSignal: "近 24 小时有可靠新进展",
    archiveSignal: "今日暂无新的可靠发布，展示最近 7 天重要信息",
    freshItems: "条近 24 小时内容",
    latestAt: "最新一条发布于",
    searchAria: "搜索新闻",
    searchPlaceholder: "搜索标题、摘要或来源",
    signals: "今日值得关注",
    result: "条结果",
    original: "阅读原文",
    noSignal: "没有找到匹配的新闻",
    noSignalHelp: "换一个关键词或查看全部分类。",
    clear: "清除筛选",
    distribution: "内容分布",
    sourcePriority: "信源优先级",
    source1Title: "官方与一手信源",
    source1Text: "研究机构、产品官方博客、公司公告",
    source2Title: "开发者与开源社区",
    source2Text: "GitHub、Hugging Face、ComfyUI 与 MCP 生态",
    source3Title: "行业与商业媒体",
    source3Text: "仅保留有实质影响的重要动态",
    dedupeTitle: "三层去重",
    dedupeText: "链接归一化、标题相似度与语义聚类，避免同一事件重复出现。",
    showMethod: "查看筛选方法",
    hideMethod: "收起方法",
    collect: "收集",
    collectText: "优先最近 24 小时；不足时回看最近 7 天。",
    merge: "合并",
    mergeText: "URL、标题和语义三级去重。",
    rank: "排序",
    rankText: "按新鲜度、影响力、实用性与信源质量综合评分。",
    footer: "信息应该帮助判断，而不是制造焦虑。",
    next: "下一次自动检查 · 明日 09:00",
    langAria: "切换到英文",
    summaryButton: "一键总结",
    summaryAria: "打开 AI 新闻一键总结",
    daily: "每日",
    weekly: "每周",
    closeSummary: "关闭总结",
    fallback: "近 24 小时暂无可靠重大更新，以下为近期重要信号",
    narrative: "重大叙事",
    sourceLink: "查看原始信息",
    shortcutHint: "桌面快捷方式与键盘快捷键：⌥ D 每日 · ⌥ W 每周",
    feishuReady: "已预留飞书摘要通道",
  },
  en: {
    brandAria: "AI Signal home",
    title: "DAILY AI INTELLIGENCE",
    update: "Global sources rechecked daily · Curated at 09:00",
    headlineA: "Important AI progress,",
    headlineB: "ahead of the noise.",
    intro: "Tracking official releases, developer communities, and open-source ecosystems worldwide. When there is no reliable update today, we surface the most important signals from the past seven days.",
    selected: "Selected",
    candidates: "Candidates",
    sources: "Sources",
    filterAria: "Filter news",
    freshnessLabel: "FRESHNESS",
    checkedAt: "Last checked",
    currentSignal: "Reliable new signals found in the past 24 hours",
    archiveSignal: "No reliable release today; showing important signals from the past 7 days",
    freshItems: "items from the past 24 hours",
    latestAt: "Latest item published",
    searchAria: "Search news",
    searchPlaceholder: "Search title, summary, or source",
    signals: "Signals worth your attention",
    result: "results",
    original: "Original source",
    noSignal: "No matching signal",
    noSignalHelp: "Try another keyword or view all categories.",
    clear: "Clear filters",
    distribution: "Distribution",
    sourcePriority: "Source priority",
    source1Title: "Official & primary",
    source1Text: "Research labs, official product blogs, and company releases",
    source2Title: "Developer & open source",
    source2Text: "GitHub, Hugging Face, ComfyUI, and the MCP ecosystem",
    source3Title: "Industry & business",
    source3Text: "Only developments with material impact",
    dedupeTitle: "Three-layer dedupe",
    dedupeText: "URL normalization, title similarity, and semantic clustering prevent repeat stories.",
    showMethod: "View selection method",
    hideMethod: "Hide selection method",
    collect: "Collect",
    collectText: "Prioritize the last 24 hours, then look back seven days if needed.",
    merge: "Merge",
    mergeText: "Deduplicate by URL, title, and meaning.",
    rank: "Rank",
    rankText: "Score freshness, impact, utility, and source quality.",
    footer: "Information should improve judgment, not create anxiety.",
    next: "Next automatic check · Tomorrow at 09:00",
    langAria: "切换到中文",
    summaryButton: "QUICK BRIEF",
    summaryAria: "Open the AI news quick brief",
    daily: "Daily",
    weekly: "Weekly",
    closeSummary: "Close summary",
    fallback: "No reliable major update in the past 24 hours; showing recent important signals",
    narrative: "KEY NARRATIVES",
    sourceLink: "Original source",
    shortcutHint: "Desktop and keyboard shortcuts: ⌥ D daily · ⌥ W weekly",
    feishuReady: "Feishu summary channel reserved",
  },
};

function formatDate(value: string, language: Language, long = false) {
  return new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en-GB", {
    month: "short",
    day: "numeric",
    ...(long ? { year: "numeric", weekday: "long" } : {}),
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

function sourceName(source: string) {
  return source.split(" · ")[0];
}

function localizedTitle(item: NewsItem, language: Language) {
  if (language === "en") return item.title_en || item.original_title;
  return item.title_zh || item.title_en || item.original_title;
}

function localizedSummary(item: NewsItem, language: Language) {
  if (language === "en") return item.summary_en || item.summary_zh;
  return item.summary_zh || item.summary_en || "—";
}

function formatTime(value: string, language: Language) {
  return new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en-GB", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

function StoryCard({ item, index, language }: { item: NewsItem; index: number; language: Language }) {
  const copy = COPY[language];
  const labels = CATEGORY_LABELS[language];
  const title = localizedTitle(item, language);
  return (
    <article className="story-card">
      <div className="story-index">{String(index + 1).padStart(2, "0")}</div>
      <div className="story-body">
        <div className="story-meta">
          <span className={`category-dot category-${item.category}`} />
          <span>{labels[item.category]}</span>
          <span className="meta-separator">/</span>
          <span>{sourceName(item.source)}</span>
          <span className="meta-separator">/</span>
          <time>{formatDate(item.published_at, language)}</time>
        </div>
        <h2>{title}</h2>
        <p>{localizedSummary(item, language)}</p>
        <div className="story-footer">
          <div className="tag-row">
            {item.extra_categories.slice(0, 2).map((category) => (
              <span className="mini-tag" key={category}>{labels[category]}</span>
            ))}
          </div>
          <a href={item.url} target="_blank" rel="noreferrer" aria-label={`${copy.original}: ${title}`}>
            {copy.original} <span aria-hidden="true">↗</span>
          </a>
        </div>
      </div>
    </article>
  );
}

export function NewsDashboard({ initialDigest }: { initialDigest: Digest }) {
  const [currentDigest, setCurrentDigest] = useState(initialDigest);
  const [language, setLanguage] = useState<Language>("zh");
  const [activeCategory, setActiveCategory] = useState<Category>("all");
  const [query, setQuery] = useState("");
  const [methodOpen, setMethodOpen] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summaryPeriod, setSummaryPeriod] = useState<SummaryPeriod>("daily");
  const copy = COPY[language];
  const labels = CATEGORY_LABELS[language];

  useEffect(() => {
    const controller = new AbortController();
    fetch("/data/latest.json", { signal: controller.signal, cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("Latest digest is unavailable");
        return response.json() as Promise<Digest>;
      })
      .then((latest) => {
        if (Array.isArray(latest.items) && latest.items.length) setCurrentDigest(latest);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    window.localStorage.setItem("ai-signal-language", language);
  }, [language]);

  useEffect(() => {
    const requestedPeriod = new URLSearchParams(window.location.search).get("summary");
    if (requestedPeriod === "daily" || requestedPeriod === "weekly") {
      window.requestAnimationFrame(() => {
        setSummaryPeriod(requestedPeriod);
        setSummaryOpen(true);
      });
    }

    const handleShortcut = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSummaryOpen(false);
      if (!event.altKey) return;
      const key = event.key.toLowerCase();
      if (key !== "d" && key !== "w") return;
      event.preventDefault();
      setSummaryPeriod(key === "d" ? "daily" : "weekly");
      setSummaryOpen(true);
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  const items = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return currentDigest.items.filter((item) => {
      const matchesCategory = activeCategory === "all" || item.category === activeCategory || item.extra_categories.includes(activeCategory);
      const matchesQuery = !keyword || `${item.title_zh} ${item.summary_zh} ${item.title_en ?? ""} ${item.summary_en ?? ""} ${item.source}`.toLowerCase().includes(keyword);
      return matchesCategory && matchesQuery;
    });
  }, [activeCategory, currentDigest.items, query]);

  const categoryCounts = useMemo(() => {
    const counts: Partial<Record<Category, number>> = {};
    for (const item of currentDigest.items) counts[item.category] = (counts[item.category] ?? 0) + 1;
    return counts;
  }, [currentDigest.items]);

  const freshness = useMemo(() => {
    const now = new Date(currentDigest.generated_at).getTime();
    const latest = currentDigest.latest_published_at
      ? new Date(currentDigest.latest_published_at).getTime()
      : Math.max(...currentDigest.items.map((item) => new Date(item.published_at).getTime()));
    const calculatedFresh = currentDigest.items.filter((item) => {
      const age = now - new Date(item.published_at).getTime();
      return age >= 0 && age <= 24 * 60 * 60 * 1000;
    }).length;
    return {
      latest: Number.isFinite(latest) ? new Date(latest).toISOString() : currentDigest.generated_at,
      freshCount: currentDigest.fresh_count_24h ?? calculatedFresh,
    };
  }, [currentDigest]);

  const summary = useMemo(
    () => buildSummary(currentDigest, summaryPeriod, language),
    [currentDigest, language, summaryPeriod],
  );

  const resetFilters = () => { setActiveCategory("all"); setQuery(""); };
  const toggleLanguage = () => setLanguage((current) => current === "zh" ? "en" : "zh");
  const openSummary = (period: SummaryPeriod = summaryPeriod) => {
    setSummaryPeriod(period);
    setSummaryOpen(true);
    const url = new URL(window.location.href);
    url.searchParams.set("summary", period);
    window.history.replaceState({}, "", url);
  };
  const closeSummary = () => {
    setSummaryOpen(false);
    const url = new URL(window.location.href);
    url.searchParams.delete("summary");
    window.history.replaceState({}, "", url);
  };

  return (
    <main>
      <header className="site-header">
        <div className="header-left">
          <a className="brand" href="#top" aria-label={copy.brandAria}>
            <span className="brand-mark">A/</span><span>AI SIGNAL</span>
          </a>
          <button className="language-toggle" type="button" onClick={toggleLanguage} aria-label={copy.langAria}>
            <span className={language === "zh" ? "active" : ""}>中</span><i>/</i><span className={language === "en" ? "active" : ""}>EN</span>
          </button>
        </div>
        <div className="header-center">{copy.title}</div>
        <div className="header-actions">
          <div className="header-status"><span /> {copy.update}</div>
          <button className="summary-trigger" type="button" onClick={() => openSummary()} aria-label={copy.summaryAria}>
            <span aria-hidden="true">✦</span>{copy.summaryButton}
          </button>
        </div>
      </header>

      <section className="hero" id="top">
        <div className="hero-kicker">DAILY BRIEFING · {formatDate(currentDigest.generated_at, language, true)}</div>
        <h1>{copy.headlineA}<br /><em>{copy.headlineB}</em></h1>
        <div className="hero-bottom">
          <p>{copy.intro}</p>
          <div className="hero-stats" aria-label={language === "zh" ? "本期简报统计" : "Briefing statistics"}>
            <div><strong>{currentDigest.items.length}</strong><span>{copy.selected}</span></div>
            <div><strong>{currentDigest.candidate_count}</strong><span>{copy.candidates}</span></div>
            <div><strong>{currentDigest.source_count}</strong><span>{copy.sources}</span></div>
          </div>
        </div>
      </section>

      <section className="toolbar" aria-label={copy.filterAria}>
        <div className="category-scroll">
          {categories.map((category) => (
            <button className={activeCategory === category ? "category-button active" : "category-button"} key={category} onClick={() => setActiveCategory(category)} type="button">
              {labels[category]}
            </button>
          ))}
        </div>
        <label className="search-box">
          <span aria-hidden="true">⌕</span><span className="sr-only">{copy.searchAria}</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={copy.searchPlaceholder} />
        </label>
      </section>

      <section className={freshness.freshCount > 0 ? "freshness-strip is-current" : "freshness-strip is-archive"} aria-label={copy.freshnessLabel}>
        <div className="freshness-main">
          <span className="freshness-pulse" />
          <strong>{freshness.freshCount > 0 ? copy.currentSignal : copy.archiveSignal}</strong>
        </div>
        <div className="freshness-meta">
          <span>{copy.checkedAt} · {formatTime(currentDigest.generated_at, language)}</span>
          <span>{freshness.freshCount} {copy.freshItems}</span>
          <span>{copy.latestAt} · {formatTime(freshness.latest, language)}</span>
        </div>
      </section>

      <div className="content-grid">
        <section className="feed" aria-live="polite">
          <div className="section-heading">
            <div><span className="eyebrow">TODAY&apos;S SIGNALS</span><h2>{copy.signals}</h2></div>
            <span className="result-count">{items.length} {copy.result}</span>
          </div>
          {items.length ? (
            <div className="story-list">
              {items.map((item) => <StoryCard item={item} index={currentDigest.items.indexOf(item)} language={language} key={item.url} />)}
            </div>
          ) : (
            <div className="empty-state">
              <span>NO SIGNAL</span><h2>{copy.noSignal}</h2><p>{copy.noSignalHelp}</p>
              <button type="button" onClick={resetFilters}>{copy.clear}</button>
            </div>
          )}
        </section>

        <aside className="sidebar">
          <section className="side-panel distribution">
            <div className="panel-label">{copy.distribution}</div>
            {Object.entries(categoryCounts).sort(([, a], [, b]) => (b ?? 0) - (a ?? 0)).map(([category, count]) => (
              <button type="button" key={category} onClick={() => setActiveCategory(category as Category)}>
                <span>{labels[category as Category]}</span>
                <span className="distribution-bar"><i style={{ width: `${(count! / currentDigest.items.length) * 100}%` }} /></span><strong>{count}</strong>
              </button>
            ))}
          </section>

          <section className="side-panel sources-panel">
            <div className="panel-label">{copy.sourcePriority}</div>
            <ol>
              <li><span>01</span><div><strong>{copy.source1Title}</strong><p>{copy.source1Text}</p></div></li>
              <li><span>02</span><div><strong>{copy.source2Title}</strong><p>{copy.source2Text}</p></div></li>
              <li><span>03</span><div><strong>{copy.source3Title}</strong><p>{copy.source3Text}</p></div></li>
            </ol>
          </section>

          <section className="method-card">
            <div className="method-number">3×</div><h3>{copy.dedupeTitle}</h3><p>{copy.dedupeText}</p>
            <button type="button" onClick={() => setMethodOpen(!methodOpen)} aria-expanded={methodOpen}>
              {methodOpen ? copy.hideMethod : copy.showMethod} <span>{methodOpen ? "−" : "+"}</span>
            </button>
            {methodOpen && <div className="method-detail">
              <p><b>{copy.collect}：</b>{copy.collectText}</p><p><b>{copy.merge}：</b>{copy.mergeText}</p><p><b>{copy.rank}：</b>{copy.rankText}</p>
            </div>}
          </section>
        </aside>
      </div>

      <footer>
        <div><span className="brand-mark">A/</span><strong>AI SIGNAL</strong></div><p>{copy.footer}</p><span>{copy.next}</span>
      </footer>

      {summaryOpen && <>
        <button className="summary-backdrop" type="button" onClick={closeSummary} aria-label={copy.closeSummary} />
        <aside className="summary-drawer" role="dialog" aria-modal="true" aria-labelledby="summary-title">
          <div className="summary-head">
            <div>
              <span className="summary-kicker">AI SIGNAL · {summary.period.toUpperCase()}</span>
              <h2 id="summary-title">{summary.headline}</h2>
            </div>
            <button className="summary-close" type="button" onClick={closeSummary} aria-label={copy.closeSummary}>×</button>
          </div>

          <div className="summary-tabs" aria-label={language === "zh" ? "选择总结周期" : "Choose summary period"}>
            {(["daily", "weekly"] as SummaryPeriod[]).map((period) => (
              <button
                type="button"
                className={summaryPeriod === period ? "active" : ""}
                aria-pressed={summaryPeriod === period}
                onClick={() => openSummary(period)}
                key={period}
              >
                {period === "daily" ? copy.daily : copy.weekly}
              </button>
            ))}
          </div>

          {summary.fallback_used && <div className="summary-fallback"><span />{copy.fallback}</div>}
          <p className="summary-overview">{summary.overview}</p>
          <div className="summary-section-label">{copy.narrative} · {summary.narratives.length}</div>
          <ol className="summary-narratives">
            {summary.narratives.map((narrative, index) => (
              <li key={narrative.url}>
                <span className="summary-number">{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <div className="summary-meta"><span>{narrative.category}</span> / {narrative.source} / {formatDate(narrative.published_at, language)}</div>
                  <h3>{narrative.title}</h3>
                  <p>{narrative.summary}</p>
                  <a href={narrative.url} target="_blank" rel="noreferrer">{copy.sourceLink} ↗</a>
                </div>
              </li>
            ))}
          </ol>
          <div className="summary-channel">
            <span>{copy.feishuReady}</span>
            <small>{copy.shortcutHint}</small>
          </div>
        </aside>
      </>}
    </main>
  );
}
