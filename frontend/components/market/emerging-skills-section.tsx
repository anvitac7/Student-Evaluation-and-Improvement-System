"use client";

import { useMemo, useState } from "react";
import { Sparkles } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  buildEmergingCandidates,
  FAST_GROWTH_THRESHOLD_PCT,
  formatSignedGrowth,
  rankEmergingCandidates,
  summarizeEmerging,
  type EmergingCandidate,
  type EmergingClass,
  type EmergingRanking,
} from "@/lib/market-insights";
import type {
  EmergingSkill,
  HistoricalSkillTrend,
  MarketMeta,
  TrendingSkill,
} from "@/types/market-analytics";

const CLASSIFICATION_CONFIG: Record<
  EmergingClass,
  { label: string; variant: "default" | "success" | "secondary" | "outline" }
> = {
  "newly-emerging": { label: "Newly emerging", variant: "default" },
  "fast-growing": { label: "Fast growing", variant: "success" },
  "consistently-growing": { label: "Consistently growing", variant: "success" },
  "recently-accelerating": { label: "Recently accelerating", variant: "secondary" },
  rising: { label: "Rising", variant: "default" },
  stable: { label: "Stable", variant: "secondary" },
  "insufficient-data": { label: "Not enough comparable data", variant: "outline" },
};

function ClassificationBadge({ classification }: { classification: EmergingClass }) {
  const config = CLASSIFICATION_CONFIG[classification];
  return (
    <Badge variant={config.variant} className={config.variant === "outline" ? "text-muted-foreground" : undefined}>
      {config.label}
    </Badge>
  );
}

function MiniStat({
  label,
  value,
  title,
}: {
  label: string;
  value: string;
  title?: string;
}) {
  return (
    <div className="rounded-md border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate text-lg font-semibold" title={title}>
        {value}
      </p>
    </div>
  );
}

function HistoryTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{
    payload: { year: number; demandPct: number; yoyGrowthPct: number | null };
  }>;
}) {
  const entry = payload?.[0];
  if (!active || !entry) return null;
  const point = entry.payload;
  return (
    <div className="rounded-md border border-border bg-popover p-3 text-sm shadow-md">
      <p className="font-semibold">{point.year}</p>
      <p className="text-muted-foreground">
        {point.demandPct}% of that year&apos;s postings
      </p>
      <p className="text-xs text-muted-foreground">
        {point.yoyGrowthPct == null
          ? "No comparable previous period"
          : `${formatSignedGrowth(point.yoyGrowthPct)} vs the previous comparable window`}
      </p>
    </div>
  );
}

function TrajectoryChart({ candidate, meta }: { candidate: EmergingCandidate; meta: MarketMeta | undefined }) {
  const chartData = candidate.series.map((point) => ({
    year: point.year,
    demandPct: point.demandPct,
    yoyGrowthPct: point.yoyGrowthPct,
  }));
  if (chartData.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No historical demand series is available for this skill under the current filters.
      </p>
    );
  }
  const showPartialNote =
    meta?.is_partial_year &&
    meta?.current_period != null &&
    candidate.series.some((point) => point.year === meta.current_period!.year);
  return (
    <div className="space-y-2 pt-2">
      <div className="overflow-hidden">
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={chartData} margin={{ top: 8, right: 16, left: -8, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="year" tick={{ fontSize: 12 }} allowDecimals={false} />
            <YAxis
              domain={[0, 100]}
              tickFormatter={(value: number) => `${value}%`}
              tick={{ fontSize: 12 }}
            />
            <Tooltip content={<HistoryTooltip />} />
            <Line
              type="monotone"
              dataKey="demandPct"
              name={candidate.name}
              stroke="#f97316"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {showPartialNote && (
        <Badge variant="warning">{meta!.comparison_period} only</Badge>
      )}
    </div>
  );
}

/**
 * Phase 5 emerging & rising skills: the backend's `emerging_skills` plus
 * every trending skill with positive comparable growth, classified with the
 * documented rules in `lib/market-insights.ts` (newly emerging / fast
 * growing / consistently growing / recently accelerating). Classifications
 * never come from missing data: a null growth renders "Not enough
 * comparable data", never zero.
 */
export function EmergingSkillsSection({
  emerging,
  trending,
  historical,
  meta,
  isLoading,
}: {
  emerging: EmergingSkill[] | undefined;
  trending: TrendingSkill[] | undefined;
  historical: HistoricalSkillTrend[] | undefined;
  meta: MarketMeta | undefined;
  isLoading: boolean;
}) {
  const [ranking, setRanking] = useState<EmergingRanking>("demand");
  const [historySlug, setHistorySlug] = useState<string | null>(null);

  const candidates = useMemo(
    () =>
      emerging && trending && historical
        ? buildEmergingCandidates(trending, emerging, historical)
        : [],
    [emerging, trending, historical]
  );
  const summary = useMemo(
    () => summarizeEmerging(emerging ?? [], candidates),
    [emerging, candidates]
  );
  const sorted = useMemo(
    () => rankEmergingCandidates(candidates, ranking),
    [candidates, ranking]
  );
  const historyCandidate = historySlug
    ? candidates.find((candidate) => candidate.slug === historySlug)
    : undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4" /> Emerging &amp; rising skills
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading || !emerging || !trending ? (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} className="h-16 w-full" />
              ))}
            </div>
            <Skeleton className="h-40 w-full" />
          </div>
        ) : candidates.length === 0 ? (
          <EmptyState
            icon={Sparkles}
            title="No rising or emerging skills for the current filters"
            description="No skill shows positive comparable growth right now. When the filters leave no comparable previous period, growth values are unavailable rather than zero."
          />
        ) : (
          <>
            {/* Compact summary — every figure from the actual API response. */}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MiniStat
                label="Emerging skills"
                value={String(summary.emergingCount)}
                title="Skills with no demand in the previous comparable window but demand in the current one (backend list)."
              />
              <MiniStat
                label="Fast-growing skills"
                value={String(summary.fastGrowingCount)}
                title={`Latest comparable growth of at least +${FAST_GROWTH_THRESHOLD_PCT}% (backend growth values).`}
              />
              <MiniStat
                label="Top emerging demand"
                value={
                  summary.highestEmergingDemandPct == null
                    ? "—"
                    : `${summary.highestEmergingDemandPct}%`
                }
                title="Highest current-window demand percentage among the backend's emerging skills."
              />
              <MiniStat
                label="Strongest comparable growth"
                value={
                  summary.strongestGrowthPct == null
                    ? "N/A"
                    : `${formatSignedGrowth(summary.strongestGrowthPct)}${summary.strongestGrowthName ? ` · ${summary.strongestGrowthName}` : ""}`
                }
                title={
                  summary.strongestGrowthPct == null
                    ? "No comparable growth data under the current filters."
                    : "Largest latest comparable YoY growth among rising and emerging skills."
                }
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-muted-foreground">
                {candidates.length} skill{candidates.length === 1 ? "" : "s"} with positive
                comparable growth.
              </p>
              <div className="w-48">
                <Select
                  value={ranking}
                  onValueChange={(value) => setRanking(value as EmergingRanking)}
                >
                  <SelectTrigger aria-label="Rank emerging skills by">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="demand">Rank by current demand</SelectItem>
                    <SelectItem value="growth">Rank by growth</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <ul className="divide-y divide-border rounded-md border border-border">
              {sorted.map((candidate) => (
                <li key={candidate.slug} className="p-3">
                  <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap sm:gap-4">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{candidate.name}</p>
                      {candidate.category && (
                        <p className="truncate text-xs text-muted-foreground">
                          {candidate.category}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-4 text-right text-xs text-muted-foreground sm:text-sm">
                      <span>
                        <span className="block font-semibold text-foreground">
                          {candidate.currentCount}
                        </span>
                        current posting{candidate.currentCount === 1 ? "" : "s"}
                        {candidate.currentWindowDemandPct != null
                          ? ` (${candidate.currentWindowDemandPct}% of the window)`
                          : ""}
                      </span>
                      <span>
                        <span className="block font-semibold text-foreground">
                          {candidate.growthPct == null
                            ? "N/A"
                            : formatSignedGrowth(candidate.growthPct)}
                        </span>
                        latest comparable growth
                      </span>
                    </div>
                    <ClassificationBadge classification={candidate.classification} />
                    <Button
                      variant="outline"
                      size="sm"
                      aria-expanded={historySlug === candidate.slug}
                      onClick={() =>
                        setHistorySlug(historySlug === candidate.slug ? null : candidate.slug)
                      }
                    >
                      {historySlug === candidate.slug ? "Hide history" : "History"}
                    </Button>
                  </div>
                  {historySlug === candidate.slug && historyCandidate && (
                    <TrajectoryChart candidate={historyCandidate} meta={meta} />
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
