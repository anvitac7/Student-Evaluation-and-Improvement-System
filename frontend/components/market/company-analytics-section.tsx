"use client";

import { Building2 as BuildingIcon } from "lucide-react";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { CompanyMarketAnalytics } from "@/types/market-analytics";

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: CompanyMarketAnalytics }>;
}) {
  const entry = payload?.[0];
  if (!active || !entry) return null;
  const company = entry.payload;
  return (
    <div className="rounded-md border border-border bg-popover p-3 text-sm shadow-md">
      <p className="font-semibold">{company.company_name}</p>
      <p className="text-muted-foreground">
        {company.posting_count} postings · {company.posting_share_pct}% of filtered postings
      </p>
    </div>
  );
}

function SkillChips({ company }: { company: CompanyMarketAnalytics }) {
  if (company.top_skills.length === 0) {
    return <p className="text-xs text-muted-foreground">No skill demand recorded.</p>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {company.top_skills.map((skill) => (
        <Badge key={skill.slug} variant="secondary" className="font-normal">
          {skill.name} · {skill.posting_count} ({skill.demand_pct}%)
        </Badge>
      ))}
    </div>
  );
}

export function CompanyAnalyticsSection({
  companies,
  isLoading,
}: {
  companies: CompanyMarketAnalytics[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading || !companies) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Company requirements</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-72 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (companies.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Company requirements</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={BuildingIcon}
            title="No companies match the current filters"
            description="Try widening the year range or clearing the job-family filter."
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Company requirements</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="overflow-hidden">
          <ResponsiveContainer
            width="100%"
            height={Math.max(220, Math.min(companies.length, 12) * 32 + 40)}
          >
            <BarChart
              data={companies}
              layout="vertical"
              margin={{ top: 4, right: 24, left: 4, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
              <YAxis
                type="category"
                dataKey="company_name"
                width={150}
                tick={{ fontSize: 12 }}
                tickFormatter={(value: string) =>
                  value.length > 20 ? `${value.slice(0, 19)}…` : value
                }
              />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(59,130,246,0.06)" }} />
              <Bar dataKey="posting_count" fill="#8b5cf6" radius={[0, 4, 4, 0]} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          {companies.map((company) => (
            <div key={company.company_slug} className="rounded-md border border-border p-4">
              <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-medium">{company.company_name}</p>
                  <p className="truncate text-xs text-muted-foreground">{company.industry}</p>
                </div>
                <Badge variant="outline">
                  {company.posting_count} postings · {company.posting_share_pct}%
                </Badge>
              </div>
              <SkillChips company={company} />
              <p className="mt-3 text-xs text-muted-foreground">
                Year-wise postings:{" "}
                {Object.entries(company.yearly_counts)
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
