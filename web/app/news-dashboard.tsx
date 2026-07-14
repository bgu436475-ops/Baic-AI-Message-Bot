"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CATEGORY_LABELS,
  categories,
  type Category,
  type Digest,
  type NewsItem,
} from "./news-data";

type Language = "zh" | "en";

const COPY = {
  zh: {
    brandAria: "AI Signal 首页",
    title: "AI 每日情报",
    update: "持续跟踪 · 每日 09:00 精选",
    headlineA: "让重要的 AI 进展，",
    headlineB: "先于噪音抵达。",
    intro: "实时跟进全球官方发布、开发者社区与开源生态；当天没有可靠新进展时，回看最近 7 天最重要的信息。",
    selected: "本期精选",
    candidates: "候选信息",
    sources: "信源覆盖",
    filterAria: "筛选新闻",
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
    next: "持续监测 · 明日 09:00 再精选",
    langAria: "切换到英文",
  },
  en: {
    brandAria: "AI Signal home",
    title: "DAILY AI INTELLIGENCE",
    update: "Always monitoring · Curated daily at 09:00",
    headlineA: "Important AI progress,",
    headlineB: "ahead of the noise.",
    intro: "Tracking official releases, developer communities, and open-source ecosystems worldwide. When there is no reliable update today, we surface the most important signals from the past seven days.",
    selected: "Selected",
    candidates: "Candidates",
    sources: "Sources",
    filterAria: "Filter news",
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
    next: "Monitoring continuously · Next curation at 09:00",
    langAria: "切换到中文",
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
  const copy = COPY[language];
  const labels = CATEGORY_LABELS[language];

  useEffect(() => {
    const savedLanguage = window.localStorage.getItem("ai-signal-language");
    if (savedLanguage === "zh" || savedLanguage === "en") setLanguage(savedLanguage);
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

  const resetFilters = () => { setActiveCategory("all"); setQuery(""); };
  const toggleLanguage = () => setLanguage((current) => current === "zh" ? "en" : "zh");

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
        <div className="header-status"><span /> {copy.update}</div>
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
    </main>
  );
}
