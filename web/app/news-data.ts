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

export type NewsItem = {
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

export type Digest = {
  generated_at: string;
  candidate_count: number;
  source_count: number;
  latest_published_at?: string | null;
  fresh_count_24h?: number;
  lookback_hours?: number;
  fallback_used?: boolean;
  items: NewsItem[];
};

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
export const digest = latestDigest as Digest;
