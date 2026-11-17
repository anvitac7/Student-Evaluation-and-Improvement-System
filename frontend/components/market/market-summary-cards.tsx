import { Building2, Briefcase, Code2, TrendingUp, Trophy } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCard } from "@/components/shared/stat-card";
import type { MarketSummary } from "@/types/market-analytics";

function SummarySkeleton() {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-6">
        <div className="w-full space-y-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-8 w-16" />
        </div>
        <Skeleton className="h-11 w-11 rounded-full" />
      </CardContent>
    </Card>
  );
}

/** Formats the signed YoY growth, or an explicit "not comparable" marker. */
function formatGrowth(growth: number | null): string {
  if (growth == null) return "N/A";
  return `${growth > 0 ? "+" : ""}${growth}%`;
}

export function MarketSummaryCards({
  summary,
  isLoading,
}: {
  summary: MarketSummary | undefined;
  isLoading: boolean;
}) {
  if (isLoading || !summary) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <SummarySkeleton key={index} />
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      <StatCard label="Total job postings" value={summary.total_postings} icon={Briefcase} />
      <StatCard label="Companies tracked" value={summary.company_count} icon={Building2} />
      <StatCard label="Skills tracked" value={summary.distinct_skill_count} icon={Code2} />
      <StatCard
        label="Most demanded skill"
        value={
          summary.most_demanded_skill ? (
            <span className="text-lg font-semibold">
              {summary.most_demanded_skill.name}
              <span className="ml-1 text-sm font-normal text-muted-foreground">
                ({summary.most_demanded_skill.demand_pct}%)
              </span>
            </span>
          ) : (
            "—"
          )
        }
        icon={Trophy}
      />
      <StatCard
        label="YoY posting growth"
        value={
          <span title={summary.yoy_posting_growth_pct == null ? "No comparable previous period" : undefined}>
            {formatGrowth(summary.yoy_posting_growth_pct)}
          </span>
        }
        icon={TrendingUp}
      />
    </div>
  );
}
