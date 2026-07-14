import { digest } from "../../news-data";
import { buildSummary, type SummaryLanguage, type SummaryPeriod } from "../../summary";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const period: SummaryPeriod = url.searchParams.get("period") === "weekly" ? "weekly" : "daily";
  const language: SummaryLanguage = url.searchParams.get("lang") === "en" ? "en" : "zh";
  return Response.json(buildSummary(digest, period, language), {
    headers: { "Cache-Control": "public, max-age=300" },
  });
}
