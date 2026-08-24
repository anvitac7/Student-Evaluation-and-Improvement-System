"use client";

import { AlertCircle, BarChart3, Briefcase, Percent, Users } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { StatCard } from "@/components/shared/stat-card";
import { StatusBreakdownChart } from "@/components/shared/status-breakdown-chart";
import { useTpoAnalytics } from "@/hooks/use-analytics";

export default function TpoAnalyticsPage() {
  const { data, isLoading, isError, refetch, isRefetching } = useTpoAnalytics();

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  // Without this branch, a failed request left isLoading=false and
  // data=undefined forever, so the page fell through to the loading
  // skeleton indefinitely — indistinguishable from the page "never
  // opening." Surfacing the error with a retry button fixes that.
  if (isError || !data) {
    return (
      <EmptyState
        icon={AlertCircle}
        title="Couldn't load analytics"
        description="Something went wrong while fetching your analytics. Check your connection and try again."
        action={
          <Button variant="outline" onClick={() => refetch()} disabled={isRefetching}>
            {isRefetching ? "Retrying…" : "Retry"}
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-semibold">Analytics</h1>
        <p className="text-sm text-muted-foreground">How your drives are performing.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Total drives" value={data.total_drives} icon={Briefcase} />
        <StatCard label="Total applications" value={data.total_applications} icon={Users} />
        <StatCard label="Selection rate" value={`${data.selection_rate_pct}%`} icon={Percent} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Application funnel</CardTitle>
          <CardDescription>Across all your drives combined.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.total_applications === 0 ? (
            <EmptyState
              icon={BarChart3}
              title="No applications yet"
              description="Data will appear here once students start applying."
            />
          ) : (
            <StatusBreakdownChart breakdown={data.breakdown} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Per-drive breakdown</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {data.drives.length === 0 ? (
            <p className="text-sm text-muted-foreground">No drives created yet.</p>
          ) : (
            data.drives.map((drive) => (
              <div key={drive.drive_id} className="rounded-md border border-border p-4">
                <div className="mb-2 flex items-center justify-between">
                  <div>
                    <p className="font-medium">{drive.job_title}</p>
                    <p className="text-sm text-muted-foreground">{drive.company_name}</p>
                  </div>
                  <Badge variant={drive.status === "open" ? "success" : "secondary"}>{drive.status}</Badge>
                </div>
                <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
                  <span>{drive.total_applications} applied</span>
                  <span>{drive.breakdown.shortlisted} shortlisted</span>
                  <span>{drive.breakdown.rejected} rejected</span>
                  <span>{drive.breakdown.selected} selected</span>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
