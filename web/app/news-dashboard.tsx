"use client";

import { useMemo, useState } from "react";
import {
  CATEGORY_LABELS,
  categories,
  type Category,
  type Digest,
  type NewsItem,
} from "./news-data";

function formatDate(value: string, long = false) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    ...(long ? { year: "numeric", weekday: "long" } : {}),
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

function sourceName(source: string) {
  return source.split(" · ")[0];
}

function StoryCard({ item, index }: { item: NewsItem; index: number }) {
  return (
    <article className="story-card">
      <div className="story-index">{String(index + 1).padStart(2, "0")}</div>
      <div className="story-body">
        <div className="story-meta">
          <span className={`category-dot category-${item.category}`} />
          <span>{CATEGORY_LABELS[item.category]}</span>
          <span className="meta-separator">/</span>
          <span>{sourceName(item.source)}</span>
          <span className="meta-separator">/</span>
          <time>{formatDate(item.published_at)}</time>
        </div>
        <h2>{item.title_zh}</h2>
        <p>{item.summary_zh}</p>
        <div className="story-footer">
          <div className="tag-row">
            {item.extra_categories.slice(0, 2).map((category) => (
              <span className="mini-tag" key={category}>
                {CATEGORY_LABELS[category]}
              </span>
            ))}
          </div>
          <a href={item.url} target="_blank" rel="noreferrer" aria-label={`阅读原文：${item.title_zh}`}>
            阅读原文 <span aria-hidden="true">↗</span>
          </a>
        </div>
      </div>
    </article>
  );
}

export function NewsDashboard({ initialDigest }: { initialDigest: Digest }) {
  const [activeCategory, setActiveCategory] = useState<Category>("all");
  const [query, setQuery] = useState("");
  const [methodOpen, setMethodOpen] = useState(false);

  const items = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return initialDigest.items.filter((item) => {
      const matchesCategory =
        activeCategory === "all" ||
        item.category === activeCategory ||
        item.extra_categories.includes(activeCategory);
      const matchesQuery =
        !keyword ||
        `${item.title_zh} ${item.summary_zh} ${item.source}`.toLowerCase().includes(keyword);
      return matchesCategory && matchesQuery;
    });
  }, [activeCategory, initialDigest.items, query]);

  const categoryCounts = useMemo(() => {
    const counts: Partial<Record<Category, number>> = {};
    for (const item of initialDigest.items) {
      counts[item.category] = (counts[item.category] ?? 0) + 1;
    }
    return counts;
  }, [initialDigest.items]);

  const resetFilters = () => {
    setActiveCategory("all");
    setQuery("");
  };

  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="AI Signal 首页">
          <span className="brand-mark">A/</span>
          <span>AI SIGNAL</span>
        </a>
        <div className="header-center">AI 每日情报</div>
        <div className="header-status"><span /> 每日 09:00 更新</div>
      </header>

      <section className="hero" id="top">
        <div className="hero-kicker">DAILY BRIEFING · {formatDate(initialDigest.generated_at, true)}</div>
        <h1>让重要的 AI 进展，<br /><em>先于噪音抵达。</em></h1>
        <div className="hero-bottom">
          <p>从官方发布、开发者社区和开源项目中筛出真正值得关注的信息。每天约 10 条，中文摘要直达原始信源。</p>
          <div className="hero-stats" aria-label="今日简报统计">
            <div><strong>{initialDigest.items.length}</strong><span>今日精选</span></div>
            <div><strong>{initialDigest.candidate_count}</strong><span>候选信息</span></div>
            <div><strong>{initialDigest.source_count}</strong><span>信源覆盖</span></div>
          </div>
        </div>
      </section>

      <section className="toolbar" aria-label="筛选新闻">
        <div className="category-scroll">
          {categories.map((category) => (
            <button
              className={activeCategory === category ? "category-button active" : "category-button"}
              key={category}
              onClick={() => setActiveCategory(category)}
              type="button"
            >
              {CATEGORY_LABELS[category]}
            </button>
          ))}
        </div>
        <label className="search-box">
          <span aria-hidden="true">⌕</span>
          <span className="sr-only">搜索新闻</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题、摘要或来源" />
        </label>
      </section>

      <div className="content-grid">
        <section className="feed" aria-live="polite">
          <div className="section-heading">
            <div><span className="eyebrow">TODAY&apos;S SIGNALS</span><h2>今日值得关注</h2></div>
            <span className="result-count">{items.length} 条结果</span>
          </div>
          {items.length ? (
            <div className="story-list">
              {items.map((item) => (
                <StoryCard item={item} index={initialDigest.items.indexOf(item)} key={item.url} />
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <span>NO SIGNAL</span>
              <h2>没有找到匹配的新闻</h2>
              <p>换一个关键词或查看全部分类。</p>
              <button type="button" onClick={resetFilters}>清除筛选</button>
            </div>
          )}
        </section>

        <aside className="sidebar">
          <section className="side-panel distribution">
            <div className="panel-label">今日分布</div>
            {Object.entries(categoryCounts)
              .sort(([, a], [, b]) => (b ?? 0) - (a ?? 0))
              .map(([category, count]) => (
                <button type="button" key={category} onClick={() => setActiveCategory(category as Category)}>
                  <span>{CATEGORY_LABELS[category as Category]}</span>
                  <span className="distribution-bar"><i style={{ width: `${(count! / initialDigest.items.length) * 100}%` }} /></span>
                  <strong>{count}</strong>
                </button>
              ))}
          </section>

          <section className="side-panel sources-panel">
            <div className="panel-label">信源优先级</div>
            <ol>
              <li><span>01</span><div><strong>官方与一手信源</strong><p>研究机构、产品官方博客、公司公告</p></div></li>
              <li><span>02</span><div><strong>开发者与开源社区</strong><p>GitHub Trending、Hugging Face、MCP 生态</p></div></li>
              <li><span>03</span><div><strong>行业与商业媒体</strong><p>仅保留有实质影响的重要动态</p></div></li>
            </ol>
          </section>

          <section className="method-card">
            <div className="method-number">3×</div>
            <h3>三层去重</h3>
            <p>链接归一化、标题相似度与语义聚类，避免同一事件重复出现。</p>
            <button type="button" onClick={() => setMethodOpen(!methodOpen)} aria-expanded={methodOpen}>
              {methodOpen ? "收起方法" : "查看筛选方法"} <span>{methodOpen ? "−" : "+"}</span>
            </button>
            {methodOpen && (
              <div className="method-detail">
                <p><b>收集：</b>限定时间窗口，优先官方源。</p>
                <p><b>合并：</b>URL、标题和语义三级去重。</p>
                <p><b>排序：</b>按新鲜度、影响力、实用性与信源质量综合评分。</p>
              </div>
            )}
          </section>
        </aside>
      </div>

      <footer>
        <div><span className="brand-mark">A/</span><strong>AI SIGNAL</strong></div>
        <p>信息应该帮助判断，而不是制造焦虑。</p>
        <span>下一期 · 明日 09:00</span>
      </footer>
    </main>
  );
}
