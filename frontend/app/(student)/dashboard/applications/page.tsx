"use client";

import Link from "next/link";
import {
  AlertCircle,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Clock,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { useDrives, useMyApplications } from "@/hooks/use-drives";
import { useApplicationExplanation } from "@/hooks/use-explanation";
import type { ApplicationStatus } from "@/types/drive";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function statusVariant(status: ApplicationStatus): "success" | "destructive" | "secondary" | "outline" {
  switch (status) {
    case "selected":
      return "success";
    case "shortlisted":
      return "outline";
    case "rejected":
      return "destructive";
    default:
      return "secondary";
  }
}

function ExplanationDrawer({ applicationId }: { applicationId: string }) {
  const { data: explanation, isLoading } = useApplicationExplanation(applicationId);

  if (isLoading) {
    return <Skeleton className="h-24 w-full" />;
  }
  if (!explanation) {
    return <p className="text-xs text-muted-foreground">No explanation report available yet.</p>;
  }

  return (
    <div className="border-t border-border bg-muted/40 p-4 space-y-3 rounded-b-md text-xs">
      {/* Evaluation Scores Breakdown */}
      {explanation.final_score !== null && (
        <div className="rounded border bg-card p-3 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-foreground flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5 text-primary" /> Deterministic Match Score:{" "}
              {Math.round(explanation.final_score * 100)}%
            </span>
            {explanation.assessment_score_pct !== null && (
              <span className="font-mono text-muted-foreground">
                Assessment: {Math.round(explanation.assessment_score_pct)}% ({explanation.assessment_status})
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-muted-foreground pt-1">
            <div>Semantic Relevance: {Math.round((explanation.semantic_score || 0) * 100)}%</div>
            <div>Skills Match: {Math.round((explanation.skills_score || 0) * 100)}%</div>
            <div>Exp Fit: {Math.round((explanation.experience_score || 0) * 100)}%</div>
          </div>
        </div>
      )}

      {/* Rejection / Ineligibility Details */}
      {explanation.rejection_reasons && explanation.rejection_reasons.length > 0 && (
        <div className="rounded border border-destructive/30 bg-destructive/10 p-3 text-destructive space-y-1">
          <p className="font-semibold flex items-center gap-1">
            <AlertCircle className="h-3.5 w-3.5" /> Decision Factors:
          </p>
          <p className="text-foreground">{explanation.rejection_reasons.join(", ")}</p>
          {explanation.rejection_note && <p className="italic text-xs text-muted-foreground">&quot;{explanation.rejection_note}&quot;</p>}
        </div>
      )}

      {/* AI Decision Coach Narrative */}
      {explanation.narrative && (
        <div className="rounded border border-primary/20 bg-primary/5 p-3 space-y-1.5">
          <p className="font-semibold text-primary flex items-center gap-1">
            <Brain className="h-3.5 w-3.5" /> Placement Advisor Insights:
          </p>
          <p className="leading-relaxed text-foreground whitespace-pre-line">{explanation.narrative}</p>
        </div>
      )}
    </div>
  );
}

export default function ApplicationsPage() {
  const { data: applications, isLoading: applicationsLoading } = useMyApplications();
  const { data: drives, isLoading: drivesLoading } = useDrives();
  const [expandedAppId, setExpandedAppId] = useState<string | null>(null);

  const isLoading = applicationsLoading || drivesLoading;
  const driveById = new Map((drives ?? []).map((d) => [d.id, d]));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-semibold">My Applications</h1>
        <p className="text-sm text-muted-foreground">
          Track application progress, review evaluations, and view constructive feedback.
        </p>
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : !applications || applications.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="No applications yet"
          description="Browse open drives and apply to see them tracked here."
        />
      ) : (
        <div className="space-y-3">
          {applications.map((app) => {
            const drive = driveById.get(app.drive_id);
            const isExpanded = expandedAppId === app.id;

            return (
              <Card key={app.id} className="transition-colors hover:border-primary/50">
                <CardContent className="p-0">
                  <div className="flex flex-wrap items-center justify-between gap-4 p-4">
                    <Link href={`/dashboard/drives/${app.drive_id}`} className="hover:underline flex-1 min-w-[200px]">
                      <p className="font-semibold text-base">{drive?.job_title ?? "Drive"}</p>
                      <p className="text-xs text-muted-foreground">
                        {drive?.company.name ?? "—"} · Applied {formatDate(app.applied_at)}
                      </p>
                    </Link>

                    <div className="flex items-center gap-2">
                      {app.final_score !== null && app.final_score !== undefined && (
                        <Badge variant="outline" className="font-mono text-xs text-primary border-primary">
                          {Math.round(app.final_score * 100)}% Match
                        </Badge>
                      )}
                      <Badge variant={statusVariant(app.status)}>{app.status}</Badge>

                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setExpandedAppId(isExpanded ? null : app.id)}
                        className="h-8 gap-1 text-xs"
                      >
                        {isExpanded ? (
                          <>
                            Hide Report <ChevronUp className="h-3 w-3" />
                          </>
                        ) : (
                          <>
                            View Report <ChevronDown className="h-3 w-3" />
                          </>
                        )}
                      </Button>
                    </div>
                  </div>

                  {isExpanded && <ExplanationDrawer applicationId={app.id} />}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
