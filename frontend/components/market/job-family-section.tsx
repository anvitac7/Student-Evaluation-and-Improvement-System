"use client";

import { Layers as LayersIcon } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { JobFamilyMarketAnalytics } from "@/types/market-analytics";

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: JobFamilyMarketAnalytics }>;
}) {
  const entry = payload?.[0];
  if (!active || !entry) return null;
  const family = entry.payload;
  return (
    <div className="rounded-md border border-border bg-popover p-3 text-sm shadow-md">
      <p className="font-semibold">{family.job_family}</p>
      <p className="text-muted-foreground">
        {family.posting_count} postings · {family.posting_share_pct}% of filtered postings
      </p>
    </div>
  );
}

export function JobFamilySection({
  families,
  isLoading,
}: {
  families: JobFamilyMarketAnalytics[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading || !families) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Job family breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-72 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (families.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Job family breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={LayersIcon}
            title="No job families match the current filters"
            description="Try widening the year range or clearing the company filter."
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Job family breakdown</CardTitle>
        <CardDescription>
          How the filtered postings distribute across job families, with each family&apos;s
          most-demanded skills. Use the comparison section below to inspect a family&apos;s
          full skill list, growth and technical/soft mix.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <ResponsiveContainer width="100%" height={Math.max(220, families.length * 32 + 40)}>
          <BarChart data={families} layout="vertical" margin={{ top: 4, right: 24, left: 4, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
            <YAxis
              type="category"
              dataKey="job_family"
              width={170}
              tick={{ fontSize: 12 }}
              tickFormatter={(value: string) =>
                value.length > 22 ? `${value.slice(0, 21)}…` : value
              }
            />
            <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(34,197,94,0.06)" }} />
            <Bar dataKey="posting_count" fill="#22c55e" radius={[0, 4, 4, 0]} barSize={14} />
          </BarChart>
        </ResponsiveContainer>

        <div className="grid gap-4 md:grid-cols-2">
          {families.map((family) => (
            <div key={family.job_family} className="rounded-md border border-border p-4">
              <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
                <p className="min-w-0 font-medium">{family.job_family}</p>
                <Badge variant="outline">
                  {family.posting_count} postings · {family.posting_share_pct}%
                </Badge>
              </div>
              {family.top_skills.length === 0 ? (
                <p className="text-xs text-muted-foreground">No skill demand recorded.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {family.top_skills.map((skill) => (
                    <Badge key={skill.slug} variant="secondary" className="font-normal">
                      {skill.name} · {skill.posting_count} ({skill.demand_pct}%)
                    </Badge>
                  ))}
                </div>
              )}
              <p className="mt-3 text-xs text-muted-foreground">
                Year-wise postings:{" "}
                {Object.entries(family.yearly_counts)
                  .map(([year, count]) => `${year}: ${count}`)
                  .join(" · ")}
              </p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
