import type { Metadata } from "next";
import { getLatestDigest } from "../db/digest-store";
import { NewsDashboard } from "./news-dashboard";

export const metadata: Metadata = {
  title: "AI SIGNAL｜AI 每日情报",
  description: "每天严格核查高决策价值 AI 信息，宁缺毋滥。",
};

export default async function Home() {
  return <NewsDashboard initialDigest={await getLatestDigest()} />;
}
