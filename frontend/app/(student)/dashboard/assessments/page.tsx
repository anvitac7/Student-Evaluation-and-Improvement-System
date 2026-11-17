"use client";

import { useRouter } from "next/navigation";
import { Award, Briefcase, Clock, GraduationCap, ListChecks } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/shared/empty-state";
import { useToast } from "@/hooks/use-toast";
import { useAssessments, useKnowledgeStates, useStartAssessment } from "@/hooks/use-assessments";
import { useDrives, useMyApplications } from "@/hooks/use-drives";
import { saveAttemptState } from "@/lib/attempt-storage";
import { fingerprintHash } from "@/lib/fingerprint";
import type { AssessmentResponse } from "@/types/assessment";
import type { ApplicationResponse } from "@/types/drive";

function formatMinutes(sec: number): string {
  const minutes = Math.round(sec / 60);
  return `${minutes} min`;
}

const ASSESSMENT_STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  passed: "Passed",
  failed: "Failed",
  expired: "Expired",
  not_required: "Not required",
};

export default function AssessmentsPage() {
  const { data: assessments, isLoading: assessmentsLoading } = useAssessments();
  const { data: applications } = useMyApplications();
  const { data: drives } = useDrives();
  const { data: knowledgeStates, isLoading: knowledgeLoading } = useKnowledgeStates();
  const startAssessment = useStartAssessment();
  const router = useRouter();
  const { toast } = useToast();
  const [startingId, setStartingId] = useState<string | null>(null);

  const beginAttempt = async (assessmentId: string, applicationId?: string) => {
    setStartingId(assessmentId);
    try {
      const result = await startAssessment.mutateAsync({
        assessmentId,
        applicationId,
        fingerprintHash: fingerprintHash(),
      });
      // A resumed attempt keeps its original server-side start time; offset
      // the local timer so it shows the actual time remaining, not a fresh
      // full time limit.
      const elapsedMs = Math.max(0, result.time_limit_sec - result.time_remaining_sec) * 1000;
      saveAttemptState(result.attempt_id, {
        sessionToken: result.session_token,
        timeLimitSec: result.time_limit_sec,
        antiCheatConfig: result.anti_cheat_config,
        currentQuestion: result.next_question,
        startedAtMs: Date.now() - elapsedMs,
        violationCount: 0,
      });
      router.push(`/dashboard/assessments/${result.attempt_id}/take`);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't start this assessment. Please try again.";
      toast({ title: "Couldn't start assessment", description: detail, variant: "destructive" });
    } finally {
      setStartingId(null);
    }
  };

  // Classification rule mirrors the backend: an assessment linked to a drive
  // is a drive assessment; everything else is practice. `type` is kept in sync
  // by the backend, but we also check drive_id so older records classify right.
  const isDriveAssessment = (a: AssessmentResponse) => a.type === "drive" || Boolean(a.drive_id);

  const practiceAssessments = (assessments ?? []).filter((a) => !isDriveAssessment(a));

  // A drive assessment is only actionable once the student has applied to that
  // drive — that application is what the attempt gets linked to for ranking.
  const driveAssessments = (assessments ?? [])
    .filter(isDriveAssessment)
    .map((assessment) => {
      const application = (applications ?? []).find((app) => app.drive_id === assessment.drive_id);
      const drive = (drives ?? []).find((d) => d.id === assessment.drive_id);
      return { assessment, application, drive };
    })
    .filter((entry) => Boolean(entry.application));

  const renderAssessmentCard = (assessment: AssessmentResponse, application?: ApplicationResponse) => (
    <Card key={assessment.id}>
      <CardHeader>
        <CardTitle className="text-base">{assessment.title}</CardTitle>
        <CardDescription className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" /> {formatMinutes(assessment.time_limit_sec)}
          </span>
          <span>{assessment.question_pool_size} questions</span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        {assessment.anti_cheat_config.require_fullscreen && (
          <p className="mb-3 text-xs text-muted-foreground">
            Runs in fullscreen mode with tab-switch and copy/paste monitoring.
          </p>
        )}
        <Button onClick={() => beginAttempt(assessment.id, application?.id)} disabled={startingId === assessment.id}>
          {startingId === assessment.id ? "Starting…" : "Start assessment"}
        </Button>
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-semibold">Assessments</h1>
        <p className="text-sm text-muted-foreground">
          Adaptive skill assessments — difficulty adjusts to your answers as you go.
        </p>
      </div>

      <Tabs defaultValue="practice">
        <TabsList>
          <TabsTrigger value="practice" className="gap-1.5">
            <GraduationCap className="h-4 w-4" /> Practice
          </TabsTrigger>
          <TabsTrigger value="drive" className="gap-1.5">
            <Briefcase className="h-4 w-4" /> Drive assessments
          </TabsTrigger>
        </TabsList>

        <TabsContent value="practice">
          <p className="mb-4 text-sm text-muted-foreground">
            Practice assessments are for your own growth. They never affect your drive assessment
            rankings.
          </p>
          {assessmentsLoading ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-40 w-full" />
              ))}
            </div>
          ) : practiceAssessments.length === 0 ? (
            <EmptyState
              icon={ListChecks}
              title="No practice assessments yet"
              description="Your TPO or admin hasn't published a practice assessment yet."
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {practiceAssessments.map((assessment) => renderAssessmentCard(assessment))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="drive">
          <p className="mb-4 text-sm text-muted-foreground">
            Drive assessments unlock after you apply to a drive that requires one. Your score here is
            what appears in the TPO&apos;s drive assessment rankings.
          </p>
          {assessmentsLoading ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-40 w-full" />
              ))}
            </div>
          ) : driveAssessments.length === 0 ? (
            <EmptyState
              icon={Briefcase}
              title="No drive assessments available"
              description="Apply to a drive with a required assessment and it will appear here."
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {driveAssessments.map(({ assessment, application, drive }) => (
                <Card key={assessment.id}>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <CardTitle className="text-base">{assessment.title}</CardTitle>
                        <CardDescription>
                          {drive ? `${drive.job_title} · ${drive.company.name}` : "Drive assessment"}
                        </CardDescription>
                      </div>
                      {application?.assessment_status && (
                        <Badge variant={application.assessment_status === "passed" ? "success" : "secondary"}>
                          {ASSESSMENT_STATUS_LABEL[application.assessment_status] ?? application.assessment_status}
                        </Badge>
                      )}
                    </div>
                    <CardDescription className="flex items-center gap-3 pt-1">
                      <span className="flex items-center gap-1">
                        <Clock className="h-3.5 w-3.5" /> {formatMinutes(assessment.time_limit_sec)}
                      </span>
                      <span>{assessment.question_pool_size} questions</span>
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {application?.assessment_score_pct != null && (
                      <p className="mb-3 text-sm text-muted-foreground">
                        Your best score so far: <span className="font-medium">{application.assessment_score_pct}%</span>
                      </p>
                    )}
                    {assessment.anti_cheat_config.require_fullscreen && (
                      <p className="mb-3 text-xs text-muted-foreground">
                        Runs in fullscreen mode with tab-switch and copy/paste monitoring.
                      </p>
                    )}
                    <Button
                      onClick={() => beginAttempt(assessment.id, application?.id)}
                      disabled={startingId === assessment.id}
                    >
                      {startingId === assessment.id
                        ? "Starting…"
                        : application?.assessment_status === "passed"
                          ? "Retake assessment"
                          : "Start assessment"}
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Award className="h-4 w-4" /> Skill mastery
          </CardTitle>
          <CardDescription>Built from an exponential moving average across your attempts.</CardDescription>
        </CardHeader>
        <CardContent>
          {knowledgeLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : !knowledgeStates || knowledgeStates.length === 0 ? (
            <p className="text-sm text-muted-foreground">No attempts yet — start an assessment above.</p>
          ) : (
            <div className="space-y-3">
              {knowledgeStates.map((state) => (
                <div key={state.skill_tag} className="flex items-center gap-3">
                  <Badge variant="outline" className="w-32 shrink-0 justify-center truncate">
                    {state.skill_tag}
                  </Badge>
                  <Progress value={state.mastery_pct} className="flex-1" />
                  <span className="w-12 shrink-0 text-right text-sm text-muted-foreground">
                    {Math.round(state.mastery_pct)}%
                  </span>
                  <span className="w-20 shrink-0 text-right text-xs text-muted-foreground">
                    {state.attempts_count} attempts
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
