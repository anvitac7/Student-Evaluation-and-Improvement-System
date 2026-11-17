"use client";

import { TrendingUp as TrendingUpIcon } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { TrendBadge } from "@/components/market/trend-badge";
import { TrendInsights } from "@/components/market/trend-insights";
import { formatSignedGrowth, trendExplanation } from "@/lib/market-insights";
import type {
  CompanyMarketAnalytics,
  HistoricalSkillTrend,
  JobFamilyMarketAnalytics,
  MarketMeta,
  TrendingSkill,
} from "@/types/market-analytics";

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: TrendingSkill }>;
}) {
  const entry = payload?.[0];
  if (!active || !entry) return null;
  const skill = entry.payload;
  return (
    <div className="rounded-md border border-border bg-popover p-3 text-sm shadow-md">
      <p className="font-semibold">{skill.name}</p>
      <p className="text-muted-foreground">
        {skill.posting_count} posting{skill.posting_count === 1 ? "" : "s"} ·{" "}
        {skill.demand_pct}% of filtered postings
      </p>
    </div>
  );
}

export function TrendingSkillsSection({
  skills,
  historical,
  families,
  companies,
  meta,
  isLoading,
}: {
  skills: TrendingSkill[] | undefined;
  historical: HistoricalSkillTrend[];
  families: JobFamilyMarketAnalytics[];
  companies: CompanyMarketAnalytics[];
  meta: MarketMeta | undefined;
  isLoading: boolean;
}) {
  const periodLabel = meta?.current_period?.label;
  const previousLabel = meta?.previous_period?.label;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top trending skills</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {isLoading || !skills ? (
          <Skeleton className="h-72 w-full" />
        ) : skills.length === 0 ? (
          <EmptyState
            icon={TrendingUpIcon}
            title="No skills match the current filters"
            description="Try widening the year range or clearing the skill-scope filters."
          />
        ) : (
          <>
            <div className="overflow-hidden">
              <ResponsiveContainer width="100%" height={Math.max(220, skills.length * 34 + 40)}>
                <BarChart
                  data={skills}
                  layout="vertical"
                  margin={{ top: 4, right: 24, left: 4, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis
                    type="number"
                    allowDecimals={false}
                    tick={{ fontSize: 12 }}
                    label={{
                      value: "Postings requiring the skill",
                      position: "insideBottom",
                      offset: -2,
                      style: { fontSize: 11, fill: "#64748b" },
                    }}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={140}
                    tick={{ fontSize: 12 }}
                    tickFormatter={(value: string) =>
                      value.length > 18 ? `${value.slice(0, 17)}…` : value
                    }
                  />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(59,130,246,0.06)" }} />
                  <Bar dataKey="posting_count" fill="#3b82f6" radius={[0, 4, 4, 0]} barSize={16} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Supporting table — hidden heading keeps it accessible without
                duplicating the card title visually. Trend badges carry a
                native tooltip explaining the classification. */}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <caption className="sr-only">Trending skills detail</caption>
                <thead>
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th scope="col" className="py-2 pr-3 font-medium">Skill</th>
                    <th scope="col" className="py-2 pr-3 font-medium">Category</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Postings</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Demand</th>
                    <th
                      scope="col"
                      className="py-2 pr-3 text-right font-medium"
                      title={periodLabel ? `Postings in ${periodLabel}` : undefined}
                    >
                      Current
                    </th>
                    <th
                      scope="col"
                      className="py-2 pr-3 text-right font-medium"
                      title={previousLabel ? `Postings in ${previousLabel}` : undefined}
                    >
                      Previous
                    </th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">YoY growth</th>
                    <th scope="col" className="py-2 pr-3 font-medium">Trend</th>
                    <th
                      scope="col"
                      className="py-2 font-medium"
                      title="Backend trend score: weighted mean of the skill's year-wise demand shares."
                    >
                      Score
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {skills.map((skill) => (
                    <tr key={skill.slug} className="align-middle">
                      <td className="py-2.5 pr-3 font-medium">{skill.name}</td>
                      <td className="py-2.5 pr-3 text-muted-foreground">
                        {skill.category ?? "—"}
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums">{skill.posting_count}</td>
                      <td className="py-2.5 pr-3 text-right tabular-nums">{skill.demand_pct}%</td>
                      <td
                        className="py-2.5 pr-3 text-right tabular-nums"
                        title={periodLabel ? `Postings in ${periodLabel}` : undefined}
                      >
                        {skill.current_period_count}
                      </td>
                      <td
                        className="py-2.5 pr-3 text-right tabular-nums"
                        title={previousLabel ? `Postings in ${previousLabel}` : undefined}
                      >
                        {skill.previous_period_count}
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums">
                        {skill.yoy_growth_pct == null ? (
                          <span className="text-muted-foreground">N/A</span>
                        ) : (
                          formatSignedGrowth(skill.yoy_growth_pct)
                        )}
                      </td>
                      <td className="py-2.5 pr-3">
                        <span
                          title={trendExplanation(skill)}
                          className="inline-flex cursor-help"
                          aria-label={trendExplanation(skill)}
                        >
                          <TrendBadge trend={skill.trend} />
                        </span>
                      </td>
                      <td className="py-2.5 tabular-nums text-muted-foreground">
                        {skill.trend_score}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <TrendInsights
              skills={skills}
              historical={historical}
              families={families}
              companies={companies}
              meta={meta}
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}
