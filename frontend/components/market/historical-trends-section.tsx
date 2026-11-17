"use client";

import { useState } from "react";
import { LineChart as LineChartIcon, X } from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { formatSignedGrowth } from "@/lib/market-insights";
import type { HistoricalSkillTrend, MarketMeta } from "@/types/market-analytics";

/** How many skills can be compared at once (bounded chart readability). */
const MAX_COMPARED_SKILLS = 4;

const LINE_COLORS = ["#3b82f6", "#8b5cf6", "#22c55e", "#f97316"];

interface ComparisonRow {
  year: number;
  /** demand % keyed by skill name (backend yearly values). */
  [skillName: string]: number | string | null;
}

function ComparisonTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{
    name?: string | number;
    value?: number | string;
    payload: ComparisonRow;
  }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const year = payload[0]?.payload.year;
  return (
    <div className="rounded-md border border-border bg-popover p-3 text-sm shadow-md">
      <p className="font-semibold">{year}</p>
      <ul className="mt-1 space-y-1">
        {payload.map((entry, index) => {
          if (typeof entry.name !== "string") return null;
          const growth = entry.payload[`${entry.name}__growth`];
          return (
            <li key={index} className="flex items-start gap-2">
              <span
                aria-hidden
                className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: LINE_COLORS[index % LINE_COLORS.length] }}
              />
              <span>
                <span className="font-medium">{entry.name}</span>{" "}
                <span className="text-muted-foreground">
                  {typeof entry.value === "number" ? `${entry.value}%` : entry.value}
                </span>
                <span className="block text-xs text-muted-foreground">
                  {typeof growth === "number"
                    ? `${formatSignedGrowth(growth)} vs the previous comparable window`
                    : "No comparable previous period"}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * Phase 5: compare up to 4 skills' year-wise demand in one chart. All series
 * values (demand percentages AND per-year growth) come from the backend's
 * `historical_trends`. Growth is only ever shown between comparable windows
 * (Jan-Oct pair for the dataset's partial latest year); the partial-year
 * note keeps that visible.
 */
export function HistoricalTrendsSection({
  trends,
  meta,
  isLoading,
}: {
  trends: HistoricalSkillTrend[] | undefined;
  meta: MarketMeta | undefined;
  isLoading: boolean;
}) {
  const [selectedSlugs, setSelectedSlugs] = useState<string[]>([]);

  if (isLoading || !trends) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Skill demand over time</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-72 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (trends.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Skill demand over time</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={LineChartIcon}
            title="No historical data for the current filters"
            description="Try widening the year range or clearing the skill-scope filters."
          />
        </CardContent>
      </Card>
    );
  }

  // Default to the first skill until the user builds a selection.
  const selected =
    selectedSlugs.length > 0
      ? selectedSlugs
          .map((slug) => trends.find((trend) => trend.slug === slug))
          .filter((trend): trend is HistoricalSkillTrend => trend != null)
      : trends[0]
        ? [trends[0]]
        : [];
  if (selected.length === 0) return null;

  const years = selected[0]!.years.map((year) => year.year);
  const chartData: ComparisonRow[] = years.map((year, yearIndex) => {
    const row: ComparisonRow = { year };
    for (const trend of selected) {
      const point = trend.years[yearIndex];
      if (point && point.year === year) {
        row[trend.name] = point.demand_pct;
        row[`${trend.name}__growth`] = point.yoy_growth_pct;
      }
    }
    return row;
  });

  const addable = trends.filter(
    (trend) =>
      !selected.some((selectedTrend) => selectedTrend.slug === trend.slug)
  );
  const canAddMore = selected.length < MAX_COMPARED_SKILLS;

  return (
    <Card>
      <CardHeader className="gap-2 sm:flex-row sm:items-start sm:justify-between sm:space-y-0">
        <CardTitle className="text-base">Skill demand over time</CardTitle>
        <div className="w-full sm:w-64">
          <Select
            value=""
            disabled={!canAddMore || addable.length === 0}
            onValueChange={(value) => {
              if (selected.length < MAX_COMPARED_SKILLS) {
                setSelectedSlugs((previous) =>
                  previous.includes(value) ? previous : [...previous, value]
                );
              }
            }}
          >
            <SelectTrigger aria-label="Add a skill to compare">
              <SelectValue
                placeholder={canAddMore ? "Add a skill to compare…" : "Maximum skills selected"}
              />
            </SelectTrigger>
            <SelectContent>
              {addable.map((trend) => (
                <SelectItem key={trend.slug} value={trend.slug}>
                  {trend.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Selected-skill chips: remove back down to the first skill. */}
        <div className="flex flex-wrap items-center gap-2">
          {selected.map((trend, index) => (
            <Badge key={trend.slug} variant="secondary" className="gap-1 font-normal">
              <span
                aria-hidden
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: LINE_COLORS[index % LINE_COLORS.length] }}
              />
              {trend.name}
              {selected.length > 1 && (
                <button
                  type="button"
                  aria-label={`Remove ${trend.name} from the comparison`}
                  className="ml-0.5 rounded-full p-0.5 hover:bg-background/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() =>
                    setSelectedSlugs((previous) =>
                      previous.filter((slug) => slug !== trend.slug)
                    )
                  }
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </Badge>
          ))}
          {selectedSlugs.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedSlugs([])}
              className="h-7 px-2 text-xs"
            >
              Reset selection
            </Button>
          )}
        </div>

        <div className="overflow-hidden">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, left: -8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="year" tick={{ fontSize: 12 }} allowDecimals={false} />
              <YAxis
                domain={[0, 100]}
                tickFormatter={(value: number) => `${value}%`}
                tick={{ fontSize: 12 }}
              />
              <Tooltip content={<ComparisonTooltip />} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {selected.map((trend, index) => (
                <Line
                  key={trend.slug}
                  type="monotone"
                  dataKey={trend.name}
                  name={trend.name}
                  stroke={LINE_COLORS[index % LINE_COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {meta?.is_partial_year &&
          meta?.current_period != null &&
          selected.some((trend) =>
            trend.years.some((year) => year.year === meta.current_period!.year)
          ) && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="warning">{meta.comparison_period} only</Badge>
            </div>
          )}
      </CardContent>
    </Card>
  );
}
