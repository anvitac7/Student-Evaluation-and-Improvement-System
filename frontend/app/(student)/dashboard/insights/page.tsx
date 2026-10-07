"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  Lightbulb,
  Minus,
  Sparkles,
  Target,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCard } from "@/components/shared/stat-card";
import { useStudentInsights } from "@/hooks/use-assessments";
import type { SkillFocus } from "@/types/assessment";

/** Maps the backend's severity enum to a badge variant + label. */
const SEVERITY: Record<SkillFocus["severity"], { label: string; variant: "destructive" | "warning" | "secondary" | "outline" }> = {
  critical: { label: "Critical", variant: "destructive" },
  weak: { label: "Needs work", variant: "warning" },
  watch: { label: "Watch", variant: "secondary" },
  ok: { label: "On track", variant: "outline" },
};

function TrendIcon({ trend }: { trend: SkillFocus["trend"] }) {
  if (trend === "improving") return <ArrowUpRight className="h-3.5 w-3.5 text-success" />;
  if (trend === "declining") return <ArrowDownRight className="h-3.5 w-3.5 text-destructive" />;
  if (trend === "steady") return <Minus className="h-3.5 w-3.5 text-muted-foreground" />;
  // "unknown" means there's not enough history yet to claim a direction —
  // deliberately not rendered as "steady", which would overstate what we know.
  return <Minus className="h-3.5 w-3.5 text-muted-foreground/50" />;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export default function StudentInsightsPage() {
  const { data, isLoading, isError } = useStudentInsights();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Insights unavailable</CardTitle>
          <CardDescription>
            We couldn&apos;t load your insights right now. Try again shortly.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const hasHistory = data.total_attempts > 0;

  if (!hasHistory) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="font-display text-2xl font-semibold">Insights</h1>
          <p className="text-sm text-muted-foreground">
            Focus areas and a study plan, built from your assessment history.
          </p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Lightbulb className="h-4 w-4" /> No insights yet
            </CardTitle>
            <CardDescription>
              Take an assessment and we&apos;ll identify which skills need work and build a
              study guide from the questions you missed.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild size="sm">
              <Link href="/dashboard/assessments">Take an assessment</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-semibold">Insights</h1>
        <p className="text-sm text-muted-foreground">
          Based on {data.total_attempts} completed assessment{data.total_attempts === 1 ? "" : "s"} — where to
          focus, and what to revise.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Overall accuracy"
          value={`${Math.round(data.overall_accuracy_pct)}%`}
          icon={Target}
        />
        <StatCard
          label="Avg. mastery"
          value={data.average_mastery_pct !== null ? `${Math.round(data.average_mastery_pct)}%` : "—"}
          icon={Lightbulb}
        />
        <StatCard
          label="Focus areas"
          value={data.focus_areas.length}
          icon={AlertTriangle}
        />
        <StatCard
          label="To revise"
          value={data.study_guide.length}
          icon={BookOpen}
        />
      </div>

      {/* LLM narrative — only rendered when a provider actually returned one.
          Its absence is not an error state; the deterministic sections below
          are the primary content, not a fallback. */}
      {data.narrative && (
        <Card className="border-primary/30 bg-primary/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4" /> Your coach&apos;s take
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-line text-sm leading-relaxed">{data.narrative}</p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Focus areas</CardTitle>
            <CardDescription>Ranked by mastery gap plus how often you missed them.</CardDescription>
          </CardHeader>
          <CardContent>
            {data.focus_areas.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nothing flagged right now — every tracked skill is at or above the threshold. Keep
                the streak going.
              </p>
            ) : (
              <div className="space-y-4">
                {data.focus_areas.map((f) => (
                  <div key={f.skill} className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <Badge variant={SEVERITY[f.severity].variant}>{SEVERITY[f.severity].label}</Badge>
                      <span className="text-sm font-medium">{f.skill}</span>
                      <TrendIcon trend={f.trend} />
                      <span className="ml-auto text-sm text-muted-foreground">
                        {Math.round(f.mastery_pct)}% mastery
                      </span>
                    </div>
                    <Progress
                      value={f.mastery_pct}
                      className={f.severity === "critical" ? "[&>div]:bg-destructive" : undefined}
                    />
                    <p className="text-xs text-muted-foreground">
                      {f.wrong_count} missed across {f.attempts_touched} attempt
                      {f.attempts_touched === 1 ? "" : "s"}
                      {f.last_missed_at && ` · last ${formatDate(f.last_missed_at)}`}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <CheckCircle2 className="h-4 w-4" /> Strengths
            </CardTitle>
            <CardDescription>Skills you&apos;ve answered correctly with room to spare.</CardDescription>
          </CardHeader>
          <CardContent>
            {data.strengths.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No strong skills yet. Once you&apos;ve cleared a skill with no misses, it shows up here.
              </p>
            ) : (
              <div className="space-y-3">
                {data.strengths.map((s) => (
                  <div key={s.skill} className="flex items-center gap-3">
                    <Badge variant="outline" className="w-28 shrink-0 justify-center truncate">
                      {s.skill}
                    </Badge>
                    <Progress value={s.mastery_pct} className="flex-1" />
                    <span className="w-10 shrink-0 text-right text-sm text-muted-foreground">
                      {Math.round(s.mastery_pct)}%
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BookOpen className="h-4 w-4" /> Study guide
          </CardTitle>
          <CardDescription>
            The specific questions you got wrong, strongest focus area first. Work top to bottom.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data.study_guide.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing to revise — you haven&apos;t missed a question yet.
            </p>
          ) : (
            <ol className="space-y-4">
              {data.study_guide.map((item, index) => (
                <li key={item.question_id} className="rounded-lg border p-4">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{index + 1}</Badge>
                    <Badge variant="outline">{item.skill}</Badge>
                    <Badge variant="outline" className="capitalize">
                      {item.difficulty}
                    </Badge>
                    <span className="ml-auto text-xs text-muted-foreground">
                      missed {item.missed_count}×
                    </span>
                  </div>
                  <p className="text-sm font-medium">{item.text}</p>
                  <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                    <div className="rounded-md bg-destructive/10 p-2">
                      <p className="text-xs font-medium text-destructive">Your answer</p>
                      <p className="text-muted-foreground">{item.your_answer ?? "—"}</p>
                    </div>
                    <div className="rounded-md bg-success/10 p-2">
                      <p className="text-xs font-medium text-success">Correct answer</p>
                      <p className="text-muted-foreground">{item.correct_answer ?? "—"}</p>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button asChild variant="secondary">
          <Link href="/dashboard/assessments">
            Take another assessment <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
      </div>
    </div>
  );
}