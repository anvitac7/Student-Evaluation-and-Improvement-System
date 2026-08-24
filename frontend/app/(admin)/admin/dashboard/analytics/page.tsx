"use client";

import { AlertCircle, Award, BarChart3, Briefcase, GraduationCap, Percent, TrendingUp, Users } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { StatCard } from "@/components/shared/stat-card";
import { StatusBreakdownChart } from "@/components/shared/status-breakdown-chart";
import { useAdminAnalytics } from "@/hooks/use-analytics";

export default function AdminAnalyticsPage() {
  const { data, isLoading, isError, refetch, isRefetching } = useAdminAnalytics();

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  // See the TPO analytics page for why this branch matters: without it,
  // a failed request shows an infinite loading skeleton instead of ever
  // surfacing an error, which looks exactly like "Analytics won't open."
  if (isError || !data) {
    return (
      <EmptyState
        icon={AlertCircle}
        title="Couldn't load analytics"
        description="Something went wrong while fetching platform analytics. Check your connection and try again."
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
        <h1 className="font-display text-2xl font-semibold">Platform analytics</h1>
        <p className="text-sm text-muted-foreground">A snapshot of placement activity and assessment performance.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Students" value={data.total_students} icon={GraduationCap} />
        <StatCard label="TPOs" value={data.total_tpos} icon={Users} />
        <StatCard label="Drives" value={`${data.total_drives} (${data.open_drives} open)`} icon={Briefcase} />
        <StatCard label="Placement rate" value={`${data.placement_rate_pct}%`} icon={Percent} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Application funnel</CardTitle>
            <CardDescription>{data.total_applications} total applications platform-wide.</CardDescription>
          </CardHeader>
          <CardContent>
            {data.total_applications === 0 ? (
              <EmptyState
                icon={BarChart3}
                title="No applications yet"
                description="Data will appear once students start applying to drives."
              />
            ) : (
              <StatusBreakdownChart breakdown={data.application_breakdown} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Award className="h-4 w-4" /> Assessment performance
            </CardTitle>
            <CardDescription>Across all submitted attempts.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Total assessments</span>
              <span className="font-medium">{data.total_assessments}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Total attempts</span>
              <span className="font-medium">{data.total_attempts}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Submitted attempts</span>
              <span className="font-medium">{data.submitted_attempts}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Average score</span>
              <span className="font-medium">{data.average_score_pct}%</span>
            </div>
            <div className="flex items-center justify-between border-t border-border pt-3 text-muted-foreground">
              <span>Question bank</span>
              <span>
                {data.total_questions} questions across {data.total_categories} categories
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <TrendingUp className="h-4 w-4" /> Skill mastery overview
          </CardTitle>
          <CardDescription>Average mastery per skill across every student with attempts, weakest first.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.skill_mastery_overview.length === 0 ? (
            <p className="text-sm text-muted-foreground">No assessment attempts yet.</p>
          ) : (
            <div className="space-y-3">
              {data.skill_mastery_overview.map((s) => (
                <div key={s.skill_tag} className="flex items-center gap-3">
                  <Badge variant="outline" className="w-32 shrink-0 justify-center truncate">
                    {s.skill_tag}
                  </Badge>
                  <Progress value={s.avg_mastery_pct} className="flex-1" />
                  <span className="w-12 shrink-0 text-right text-sm text-muted-foreground">
                    {s.avg_mastery_pct}%
                  </span>
                  <span className="w-24 shrink-0 text-right text-xs text-muted-foreground">
                    {s.student_count} student{s.student_count === 1 ? "" : "s"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
