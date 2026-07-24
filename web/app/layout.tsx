import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI SIGNAL｜AI 每日情报",
  description: "每天严格核查高决策价值 AI 信息，宁缺毋滥。",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
  openGraph: {
    title: "AI SIGNAL｜AI 每日情报",
    description: "让重要的 AI 进展，先于噪音抵达。",
    locale: "zh_CN",
    type: "website",
    images: [{ url: "/og.png", width: 1730, height: 909, alt: "AI SIGNAL 每日情报" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "AI SIGNAL｜AI 每日情报",
    description: "每天严格核查高决策价值 AI 信息，宁缺毋滥。",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
