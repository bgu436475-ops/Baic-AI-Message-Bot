import type { Metadata } from "next";
import { NewsDashboard } from "./news-dashboard";
import { digest } from "./news-data";

export const metadata: Metadata = {
  title: "AI SIGNAL｜AI 每日情报",
  description: "每天筛选约 10 条值得关注的 AI 新闻，覆盖模型、编程、Agent、生成式 AI、开源项目与行业动态。",
};

export default function Home() {
  return <NewsDashboard initialDigest={digest} />;
}
