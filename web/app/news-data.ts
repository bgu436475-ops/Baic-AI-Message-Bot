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
  items: NewsItem[];
};

export const CATEGORY_LABELS: Record<"zh" | "en", Record<Category, string>> = {
  zh: {
    all: "全部",
    new_models: "新模型",
    ai_coding: "AI 编程",
    agents: "Agent",
    image_video: "图片 / 视频",
    comfyui: "ComfyUI",
    open_source: "开源项目",
    mcp: "MCP",
    skills: "Skill",
    industry_business: "行业 / 商业",
  },
  en: {
    all: "All",
    new_models: "New Models",
    ai_coding: "AI Coding",
    agents: "Agents",
    image_video: "Image / Video",
    comfyui: "ComfyUI",
    open_source: "Open Source",
    mcp: "MCP",
    skills: "Skills",
    industry_business: "Industry / Business",
  },
};

export const categories = Object.keys(CATEGORY_LABELS.zh) as Category[];

export const digest: Digest = {
  generated_at: "2026-07-14T08:45:00+08:00",
  candidate_count: 62,
  source_count: 7,
  items: [
    {
      original_title: "mereyabdenbekuly-ctrl/clodex-ide",
      title_zh: "Clodex IDE：面向自治开发的本地优先 Agent IDE",
      summary_zh: "一个强调零信任和可验证性的开源 Agent IDE，把规划、编码与执行记录保留在本地，近期在 GitHub 获得较高关注。",
      url: "https://github.com/mereyabdenbekuly-ctrl/clodex-ide",
      source: "GitHub · MCP 新项目",
      published_at: "2026-07-12T10:35:44Z",
      category: "mcp",
      extra_categories: ["open_source", "ai_coding"],
      importance: 92,
    },
    {
      original_title: "William-Lu-stack/LuxyAI",
      title_zh: "LuxyAI：用 Agent 管理 Kubernetes 与云基础设施",
      summary_zh: "这套开源 AgenticOps 工具尝试让 AI Agent 参与云资源诊断与运维，适合关注基础设施自动化的团队继续观察。",
      url: "https://github.com/William-Lu-stack/LuxyAI",
      source: "GitHub · MCP 新项目",
      published_at: "2026-07-10T05:57:02Z",
      category: "mcp",
      extra_categories: ["agents", "open_source"],
      importance: 80,
    },
    {
      original_title: "OthmanAdi/plandeck",
      title_zh: "Plandeck：把长时间运行的 AI Agent 计划变成看板",
      summary_zh: "项目用可视化看板呈现 Agent 的依赖、就绪任务与关键路径，让复杂执行计划比 Markdown 更容易追踪。",
      url: "https://github.com/OthmanAdi/plandeck",
      source: "GitHub · AI Skill 新项目",
      published_at: "2026-07-12T12:10:05Z",
      category: "skills",
      extra_categories: ["agents", "open_source"],
      importance: 76,
    },
    {
      original_title: "Alisa0808/vox-director",
      title_zh: "Vox Director：一个主题自动生成纸片拼贴风解说视频",
      summary_zh: "该 Agent Skill 串联 Atlas Cloud 与 FFmpeg，从单一主题完成脚本、画面和成片，展示视频生产流水线的自动化思路。",
      url: "https://github.com/Alisa0808/vox-director",
      source: "GitHub · 生成式 AI 新项目",
      published_at: "2026-07-10T15:32:05Z",
      category: "image_video",
      extra_categories: ["skills", "open_source"],
      importance: 74,
    },
    {
      original_title: "LiteRT.js, Google's high performance Web AI Inference",
      title_zh: "Google 发布 LiteRT.js，让模型直接在浏览器中运行",
      summary_zh: "LiteRT 家族新增 JavaScript 运行时，主打高性能浏览器端机器学习推理，为隐私敏感和低延迟 Web AI 场景提供新选择。",
      url: "https://developers.googleblog.com/litertjs-googles-high-performance-web-ai-inference",
      source: "Google Developers Blog",
      published_at: "2026-07-13T08:48:45Z",
      category: "new_models",
      extra_categories: ["ai_coding"],
      importance: 72,
    },
    {
      original_title: "Build agentic full-stack apps with Genkit",
      title_zh: "Genkit 推出 Agents API，简化全栈 Agent 应用开发",
      summary_zh: "新的 Agents API 把消息历史、工具调用循环和流式响应封装为统一接口，减少构建对话式 Agent 时的样板代码。",
      url: "https://developers.googleblog.com/build-agentic-full-stack-apps-with-genkit",
      source: "Google Developers Blog",
      published_at: "2026-07-13T08:48:45Z",
      category: "agents",
      extra_categories: ["ai_coding", "open_source"],
      importance: 72,
    },
    {
      original_title: "Driving the Agent Quality Flywheel from Your Coding Agent",
      title_zh: "Google 用开发者 Skill 打通 Agent 质量评估闭环",
      summary_zh: "这套方法让编码 Agent 在修改提示词后同步运行评估，帮助团队判断局部修复是否引入更广泛的回归。",
      url: "https://developers.googleblog.com/driving-the-agent-quality-flywheel-from-your-coding-agent",
      source: "Google Developers Blog",
      published_at: "2026-07-13T08:48:45Z",
      category: "skills",
      extra_categories: ["agents", "ai_coding"],
      importance: 71,
    },
    {
      original_title: "Build reliable multi-agent applications with ADK Go 2.0",
      title_zh: "ADK Go 2.0 增加图工作流与人工确认能力",
      summary_zh: "新版 Agent Development Kit 提供图结构工作流、Human-in-the-loop 和动态编排，让 Go 开发者更容易构建可靠的多 Agent 应用。",
      url: "https://developers.googleblog.com/announcing-adk-go-20",
      source: "Google Developers Blog",
      published_at: "2026-07-13T08:48:45Z",
      category: "agents",
      extra_categories: ["ai_coding"],
      importance: 71,
    },
    {
      original_title: "Introduction to elastic training with MaxText",
      title_zh: "MaxText 弹性训练可在 TPU 中断后数秒恢复",
      summary_zh: "Google 展示了 JAX 训练任务在单个 TPU 故障后的快速恢复能力，目标是降低大规模分布式训练因节点故障导致的整体重启成本。",
      url: "https://developers.googleblog.com/we-terminated-a-tpu-mid-training-and-it-recovered-in-seconds-introduction-to-elastic-training-with-maxtext",
      source: "Google Developers Blog",
      published_at: "2026-07-13T08:48:45Z",
      category: "industry_business",
      extra_categories: ["new_models"],
      importance: 70,
    },
    {
      original_title: "AI Race Coach built with Antigravity and Gemini",
      title_zh: "Gemini AI Race Coach 展示跨领域知识落地方式",
      summary_zh: "Google 开发者专家用 Gemini 构建赛车教练，把专业领域知识、实时数据与生成式建议结合，提供了垂直 AI 产品的实践样本。",
      url: "https://developers.googleblog.com/bridging-the-domain-gap-ai-race-coach-built-with-antigravity-and-gemini",
      source: "Google Developers Blog",
      published_at: "2026-07-13T08:48:45Z",
      category: "industry_business",
      extra_categories: ["agents"],
      importance: 69,
    },
  ],
};
