"use client";

import { useMemo } from "react";
import { Lightbulb } from "lucide-react";

import { buildTrendObservations } from "@/lib/market-insights";
import type {
  CompanyMarketAnalytics,
  HistoricalSkillTrend,
  JobFamilyMarketAnalytics,
  MarketMeta,
  TrendingSkill,
} from "@/types/market-analytics";

/**
 * Deterministic trend observations for the trending-skills section,
 * generated from the actual API response by the documented formulas in
 * `lib/market-insights.ts` (no random statements, no hardcoded conclusions).
 */
export function TrendInsights({
  skills,
  historical,
  families,
  companies,
  meta,
}: {
  skills: TrendingSkill[];
  historical: HistoricalSkillTrend[];
  families: JobFamilyMarketAnalytics[];
  companies: CompanyMarketAnalytics[];
  meta: MarketMeta | undefined;
}) {
  const observations = useMemo(
    () => buildTrendObservations({ skills, historical, families, companies, meta }),
    [skills, historical, families, companies, meta]
  );
  if (observations.length === 0) return null;

  return (
    <div className="rounded-md border border-border bg-muted/40 p-4">
      <h4 className="flex items-center gap-2 text-sm font-semibold">
        <Lightbulb className="h-4 w-4" /> Trend insights
      </h4>
      <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
        {observations.map((observation, index) => (
          <li key={index}>{observation}</li>
        ))}
      </ul>
    </div>
  );
}
