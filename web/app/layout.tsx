import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI SIGNAL｜AI 每日情报",
  description: "每天约 10 条值得关注的 AI 新闻，附中文摘要和原始链接。",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
