"use client";

import Link from "next/link";
import { Award, Clock, PlusCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { useAssessments } from "@/hooks/use-assessments";

function formatMinutes(sec: number): string {
  return `${Math.round(sec / 60)} min`;
}

export default function AdminAssessmentsPage() {
  const { data: assessments, isLoading } = useAssessments();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold">Assessments</h1>
          <p className="text-sm text-muted-foreground">Adaptive assessments drawing from the question bank.</p>
        </div>
        <Button asChild>
          <Link href="/admin/dashboard/assessments/new">
            <PlusCircle className="mr-2 h-4 w-4" />
            New assessment
          </Link>
        </Button>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : !assessments || assessments.length === 0 ? (
        <EmptyState
          icon={Award}
          title="No assessments yet"
          description="Create an assessment to make it available to students."
          action={
            <Button asChild size="sm">
              <Link href="/admin/dashboard/assessments/new">Create an assessment</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {assessments.map((a) => (
            <Card key={a.id}>
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base">{a.title}</CardTitle>
                  <Badge variant={a.type === "drive" ? "default" : "secondary"} className="capitalize">
                    {a.type}
                  </Badge>
                </div>
                <CardDescription className="flex items-center gap-3">
                  <span className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5" /> {formatMinutes(a.time_limit_sec)}
                  </span>
                  <span>{a.question_pool_size} questions</span>
                </CardDescription>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                {a.category_ids.length} categor{a.category_ids.length === 1 ? "y" : "ies"} · Max{" "}
                {a.anti_cheat_config.max_violations ?? "—"} violations
                {a.anti_cheat_config.require_fullscreen && " · Fullscreen required"}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
