"use client";

import { useParams, useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2, Clock, Flag, Play, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  useFinishAssessment,
  useReportViolation,
  useRunCode,
  useSubmitAnswer,
} from "@/hooks/use-assessments";
import { clearAttemptState, loadAttemptState, saveAttemptState, type AttemptState } from "@/lib/attempt-storage";
import type { CodeRunSummary } from "@/types/assessment";

const VIOLATION_THROTTLE_MS = 3000;

function formatTime(totalSec: number): string {
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function TakeAssessmentPage() {
  const params = useParams<{ attemptId: string }>();
  const attemptId = params.attemptId;
  const router = useRouter();
  const { toast } = useToast();

  const [attempt, setAttempt] = useState<AttemptState | null>(null);
  const [selectedOption, setSelectedOption] = useState<string>("");
  const [freeTextResponse, setFreeTextResponse] = useState<string>("");
  const [secondsLeft, setSecondsLeft] = useState<number>(0);
  const [violationBanner, setViolationBanner] = useState<string | null>(null);
  const [autoSubmittedDialogOpen, setAutoSubmittedDialogOpen] = useState(false);
  const [finishDialogOpen, setFinishDialogOpen] = useState(false);
  const [codeRunResult, setCodeRunResult] = useState<CodeRunSummary | null>(null);

  const questionStartRef = useRef<number>(Date.now());
  const lastViolationAtRef = useRef<Record<string, number>>({});
  const submittedRef = useRef(false); // guards against double-submit races (timer + auto-submit)
  const timeExpiredRef = useRef(false);
  const historyGuardRef = useRef(false);

  const submitAnswer = useSubmitAnswer();
  const reportViolation = useReportViolation();
  const runCode = useRunCode();
  const finishAssessment = useFinishAssessment();

  // ---- Load attempt state (from sessionStorage, set by the "Start" action) ----
  useEffect(() => {
    const stored = loadAttemptState(attemptId);
    if (!stored) {
      // Direct navigation with no active attempt in this browser session — nothing to resume.
      toast({
        title: "No active attempt found",
        description: "Start a new assessment attempt from the assessments page.",
        variant: "destructive",
      });
      router.replace("/dashboard/assessments");
      return;
    }
    setAttempt(stored);
    setSecondsLeft(Math.max(0, stored.timeLimitSec - Math.floor((Date.now() - stored.startedAtMs) / 1000)));
    questionStartRef.current = Date.now();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attemptId]);

  // ---- Reset editor state whenever the current question changes ----
  const currentQuestionId = attempt?.currentQuestion?.id;
  const currentQuestionType = attempt?.currentQuestion?.type;
  const currentStarterCode = attempt?.currentQuestion?.starter_code;

  useEffect(() => {
    if (!currentQuestionId) return;
    setSelectedOption("");
    setCodeRunResult(null);
    setFreeTextResponse(currentQuestionType === "coding" ? currentStarterCode ?? "" : "");
    questionStartRef.current = Date.now();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentQuestionId]);

  const finishAttempt = useCallback(
    (reason: "completed" | "auto_submitted") => {
      if (submittedRef.current) return;
      submittedRef.current = true;
      clearAttemptState(attemptId);
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => undefined);
      }
      if (reason === "auto_submitted") {
        setAutoSubmittedDialogOpen(true);
      } else {
        router.replace(`/dashboard/assessments/results/${attemptId}`);
      }
    },
    [attemptId, router]
  );

  const reportViolationThrottled = useCallback(
    (type: string, metadata?: Record<string, unknown>) => {
      if (!attempt || submittedRef.current) return;
      const now = Date.now();
      const last = lastViolationAtRef.current[type] ?? 0;
      if (now - last < VIOLATION_THROTTLE_MS) return;
      lastViolationAtRef.current[type] = now;

      reportViolation.mutate(
        { attemptId, sessionToken: attempt.sessionToken, type, metadata },
        {
          onSuccess: (result) => {
            setAttempt((prev) => (prev ? { ...prev, violationCount: result.violation_count } : prev));
            if (result.attempt_status === "submitted" || result.auto_submitted) {
              finishAttempt("auto_submitted");
              return;
            }
            setViolationBanner(
              `Violation recorded (${result.violation_count}/${result.max_violations}): ${type.replace(/_/g, " ")}`
            );
          },
        }
      );
    },
    [attempt, attemptId, finishAttempt, reportViolation]
  );

  // ---- Fullscreen enforcement ----
  useEffect(() => {
    if (!attempt) return;
    if (attempt.antiCheatConfig.require_fullscreen && !document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {
        reportViolationThrottled("fullscreen_denied");
      });
    }

    const onFullscreenChange = () => {
      if (attempt.antiCheatConfig.require_fullscreen && !document.fullscreenElement && !submittedRef.current) {
        reportViolationThrottled("fullscreen_exit");
      }
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt?.antiCheatConfig.require_fullscreen]);

  // ---- Tab-switch / visibility detection ----
  useEffect(() => {
    if (!attempt) return;
    const onVisibilityChange = () => {
      if (document.hidden) {
        reportViolationThrottled("tab_switch");
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  // ---- Copy/paste blocking ----
  useEffect(() => {
    if (!attempt) return;
    const block = (e: ClipboardEvent) => {
      e.preventDefault();
      reportViolationThrottled("copy_paste_attempt");
    };
    document.addEventListener("copy", block);
    document.addEventListener("paste", block);
    document.addEventListener("cut", block);
    return () => {
      document.removeEventListener("copy", block);
      document.removeEventListener("paste", block);
      document.removeEventListener("cut", block);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  // ---- Prevent accidental refresh/close while an attempt is active ----
  useEffect(() => {
    if (!attempt) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (submittedRef.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [attempt]);

  // ---- Keep browser Back inside the active assessment ----
  // The dashboard nav is hidden on this route, but the browser's Back button
  // is still a navigation path. A sentinel history entry turns Back into a
  // "finish first" prompt instead of silently abandoning the attempt.
  useEffect(() => {
    if (!attempt || submittedRef.current) return;

    const pushGuard = () => {
      window.history.pushState(
        { ...window.history.state, placerAssessmentGuard: true },
        "",
        window.location.href
      );
    };
    if (!historyGuardRef.current) {
      historyGuardRef.current = true;
      pushGuard();
    }

    const onPopState = () => {
      if (submittedRef.current) return;
      pushGuard();
      setFinishDialogOpen(true);
      toast({
        title: "Assessment in progress",
        description: "Use Finish to submit your attempt before leaving.",
      });
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [attempt, toast]);

  // ---- Countdown timer ----
  // This is a UX convenience only — server-side timer enforcement (per
  // Phase 11) is the actual source of truth; a client clock can't be
  // trusted, but the answer/violation endpoints will reject or auto-submit
  // regardless of what happens here.
  useEffect(() => {
    if (!attempt || submittedRef.current) return;
    const interval = setInterval(() => {
      setSecondsLeft((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  // When the client timer hits zero, finalize on the server immediately.
  // Without this, an expired attempt just sat in_progress forever unless the
  // student happened to answer another question (which the server would then
  // reject as past the deadline).
  useEffect(() => {
    if (secondsLeft > 0 || !attempt || submittedRef.current || timeExpiredRef.current) return;
    timeExpiredRef.current = true;
    reportViolationThrottled("time_expired");
    finishAssessment.mutate(
      { attemptId, sessionToken: attempt.sessionToken },
      {
        onSuccess: () => finishAttempt("auto_submitted"),
        onError: (err: any) => {
          const detail = err?.response?.data?.detail ?? "";
          const lower = String(detail).toLowerCase();
          // The server finalizes expired attempts before rejecting, so these
          // errors mean the attempt is already submitted and safe to view.
          if (lower.includes("already been submitted") || lower.includes("time limit exceeded")) {
            finishAttempt("auto_submitted");
            return;
          }
          toast({
            title: "Couldn't auto-submit",
            description: "The time limit is up. Use Finish to submit your answers.",
            variant: "destructive",
          });
        },
      }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secondsLeft]);

  const handleSubmitAnswer = async () => {
    if (!attempt?.currentQuestion) return;
    const question = attempt.currentQuestion;
    const response = question.type === "mcq" ? selectedOption : freeTextResponse;
    if (!response.trim()) {
      toast({ title: "Answer required", description: "Please provide a response before continuing." });
      return;
    }

    const timeTakenSec = (Date.now() - questionStartRef.current) / 1000;

    try {
      const result = await submitAnswer.mutateAsync({
        attemptId,
        sessionToken: attempt.sessionToken,
        questionId: question.id,
        response,
        timeTakenSec,
      });

      if (result.code_result && result.code_result.total > 0) {
        toast({
          title: result.code_result.all_passed ? "All test cases passed" : "Some test cases failed",
          description: `${result.code_result.passed}/${result.code_result.total} test cases passed.`,
          variant: result.code_result.all_passed ? "default" : "destructive",
        });
      }

      setSelectedOption("");
      setFreeTextResponse("");
      setCodeRunResult(null);
      questionStartRef.current = Date.now();

      if (result.attempt_status === "submitted" || !result.next_question) {
        finishAttempt("completed");
        return;
      }

      const updated: AttemptState = { ...attempt, currentQuestion: result.next_question };
      setAttempt(updated);
      saveAttemptState(attemptId, updated);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't submit your answer. Please try again.";
      toast({ title: "Submission failed", description: detail, variant: "destructive" });
    }
  };

  const handleFinishAssessment = async () => {
    if (!attempt || finishAssessment.isPending) return;
    try {
      await finishAssessment.mutateAsync({
        attemptId,
        sessionToken: attempt.sessionToken,
      });
      setFinishDialogOpen(false);
      finishAttempt("completed");
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't finish your assessment. Please try again.";
      const lower = String(detail).toLowerCase();
      // The server finalizes expired attempts before rejecting, and an
      // already-submitted attempt should still land on the results page.
      if (lower.includes("already been submitted") || lower.includes("time limit exceeded")) {
        setFinishDialogOpen(false);
        finishAttempt(lower.includes("time limit exceeded") ? "auto_submitted" : "completed");
        return;
      }
      toast({ title: "Couldn't finish assessment", description: detail, variant: "destructive" });
    }
  };

  const handleRunCode = async () => {
    if (!attempt?.currentQuestion) return;
    const question = attempt.currentQuestion;
    if (!freeTextResponse.trim()) {
      toast({ title: "Code required", description: "Write some code before running the sample tests." });
      return;
    }

    try {
      const result = await runCode.mutateAsync({
        attemptId,
        sessionToken: attempt.sessionToken,
        questionId: question.id,
        code: freeTextResponse,
      });
      setCodeRunResult(result);
      if (result.total === 0) {
        toast({
          title: "No sample test cases",
          description: "This question only has hidden tests — submit to be graded.",
        });
      } else {
        toast({
          title: result.all_passed ? "Sample tests passed" : "Sample tests failed",
          description: `${result.passed}/${result.total} visible test cases passed.`,
          variant: result.all_passed ? "default" : "destructive",
        });
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't run your code. Please try again.";
      toast({ title: "Run failed", description: detail, variant: "destructive" });
    }
  };

  if (!attempt) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Loading assessment…
      </div>
    );
  }

  const question = attempt.currentQuestion;

  return (
    <div className="mx-auto min-h-screen max-w-2xl space-y-4 p-4 lg:p-8">
      <div className="flex items-center justify-between gap-3">
        <Badge variant="outline" className="capitalize">
          {question?.difficulty ?? "—"}
        </Badge>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-sm font-medium">
            <Clock className="h-4 w-4" />
            {formatTime(secondsLeft)}
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setFinishDialogOpen(true)}
            disabled={finishAssessment.isPending || submitAnswer.isPending || runCode.isPending}
          >
            <Flag className="h-4 w-4" />
            Finish
          </Button>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        This is a focused assessment window. Use <span className="font-medium">Finish</span> to submit
        early — unanswered questions are skipped.
      </p>

      {violationBanner && (
        <div className="flex items-center gap-2 rounded-md border border-destructive bg-secondary px-3 py-2 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {violationBanner}
        </div>
      )}

      {!question ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            No more questions — wrapping up your attempt…
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-2">
              <CardTitle className="text-base font-normal leading-relaxed">{question.text}</CardTitle>
              {question.type === "coding" && (
                <Badge variant="secondary" className="shrink-0 uppercase">
                  {question.language ?? "code"}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {question.type === "mcq" ? (
              <div className="space-y-4">
                <div className="space-y-2">
                  {question.options.map((option, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => setSelectedOption(option)}
                      className={`w-full rounded-md border px-4 py-2.5 text-left text-sm transition-colors ${
                        selectedOption === option
                          ? "border-primary bg-secondary"
                          : "border-border hover:bg-secondary/50"
                      }`}
                    >
                      {option}
                    </button>
                  ))}
                </div>
                <Button
                  type="button"
                  onClick={handleSubmitAnswer}
                  disabled={!selectedOption || submitAnswer.isPending}
                  className="w-full"
                >
                  {submitAnswer.isPending ? "Submitting…" : "Submit & continue"}
                </Button>
              </div>
            ) : question.type === "coding" ? (
              <>
                {question.visible_test_cases.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">Sample test cases</p>
                    {question.visible_test_cases.map((testCase, index) => (
                      <div
                        key={index}
                        className="grid gap-2 rounded-md border border-border p-3 text-xs sm:grid-cols-2"
                      >
                        <div>
                          <p className="mb-1 font-medium">Input</p>
                          <pre className="whitespace-pre-wrap font-mono">
                            {testCase.input || "(no input)"}
                          </pre>
                        </div>
                        <div>
                          <p className="mb-1 font-medium">Expected output</p>
                          <pre className="whitespace-pre-wrap font-mono">
                            {testCase.expected_output || "(no output)"}
                          </pre>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <Textarea
                  rows={14}
                  spellCheck={false}
                  value={freeTextResponse}
                  onChange={(e) => {
                    setFreeTextResponse(e.target.value);
                    setCodeRunResult(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key !== "Tab") return;
                    e.preventDefault();
                    const target = e.currentTarget;
                    const start = target.selectionStart;
                    const end = target.selectionEnd;
                    const next =
                      freeTextResponse.slice(0, start) + "    " + freeTextResponse.slice(end);
                    setFreeTextResponse(next);
                    requestAnimationFrame(() => {
                      target.selectionStart = start + 4;
                      target.selectionEnd = start + 4;
                    });
                  }}
                  placeholder="Write your program here. Read from stdin and print to stdout."
                  className="font-mono text-sm"
                />

                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={handleRunCode}
                    disabled={runCode.isPending || submitAnswer.isPending}
                  >
                    <Play className="mr-1.5 h-4 w-4" />
                    {runCode.isPending ? "Running…" : "Run sample tests"}
                  </Button>
                  <Button
                    onClick={handleSubmitAnswer}
                    disabled={submitAnswer.isPending || runCode.isPending}
                    className="flex-1"
                  >
                    {submitAnswer.isPending ? "Submitting…" : "Submit & continue"}
                  </Button>
                </div>

                <p className="text-xs text-muted-foreground">
                  On submit, your code runs against every test case (including hidden ones). A question
                  counts as correct only when all test cases pass.
                </p>

                {codeRunResult && (
                  <div className="space-y-2 rounded-md border border-border p-3">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      {codeRunResult.all_passed ? (
                        <CheckCircle2 className="h-4 w-4 text-success" />
                      ) : (
                        <XCircle className="h-4 w-4 text-destructive" />
                      )}
                      {codeRunResult.total > 0
                        ? `${codeRunResult.passed}/${codeRunResult.total} sample tests passed`
                        : "No sample test cases for this question"}
                    </div>
                    {codeRunResult.error && (
                      <p className="text-xs text-destructive">{codeRunResult.error}</p>
                    )}
                    {codeRunResult.results.map((result) => (
                      <div key={result.index} className="rounded-md bg-secondary/50 p-2 text-xs">
                        <div className="flex items-center gap-2">
                          <Badge variant={result.passed ? "success" : "destructive"}>
                            {result.passed ? "Pass" : result.status.replace(/_/g, " ")}
                          </Badge>
                          <span>
                            Case {result.index}
                            {result.name ? ` — ${result.name}` : ""}
                          </span>
                          {result.runtime_ms != null && (
                            <span className="ml-auto text-muted-foreground">{result.runtime_ms} ms</span>
                          )}
                        </div>
                        {result.is_hidden ? (
                          <p className="mt-1 text-muted-foreground">Hidden test case</p>
                        ) : (
                          <div className="mt-1 space-y-1">
                            <pre className="whitespace-pre-wrap font-mono">
                              Input: {result.input || "(none)"}
                            </pre>
                            <pre className="whitespace-pre-wrap font-mono">
                              Expected: {result.expected_output || "(none)"}
                            </pre>
                            {result.actual_output != null && (
                              <pre className="whitespace-pre-wrap font-mono">
                                Actual: {result.actual_output || "(none)"}
                              </pre>
                            )}
                            {result.stderr && (
                              <pre className="whitespace-pre-wrap font-mono text-destructive">
                                {result.stderr}
                              </pre>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <>
                <Textarea
                  rows={6}
                  value={freeTextResponse}
                  onChange={(e) => setFreeTextResponse(e.target.value)}
                  placeholder="Write your answer here…"
                />
                <Button onClick={handleSubmitAnswer} disabled={submitAnswer.isPending} className="w-full">
                  {submitAnswer.isPending ? "Submitting…" : "Submit & continue"}
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <Dialog open={finishDialogOpen} onOpenChange={setFinishDialogOpen}>
        <DialogContent onInteractOutside={(e) => e.preventDefault()}>
          <DialogHeader>
            <DialogTitle>Finish this assessment?</DialogTitle>
            <DialogDescription>
              Your score will be based on the answers you have already submitted. Unanswered questions
              will be skipped, and this attempt cannot be resumed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setFinishDialogOpen(false)}
              disabled={finishAssessment.isPending}
            >
              Keep going
            </Button>
            <Button
              variant="destructive"
              onClick={handleFinishAssessment}
              disabled={finishAssessment.isPending}
            >
              {finishAssessment.isPending ? "Finishing…" : "Finish & see results"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={autoSubmittedDialogOpen}
        onOpenChange={(open) => {
          // The attempt is already submitted at this point; closing the
          // dialog in any way must send the student to the results page.
          if (!open) router.replace(`/dashboard/assessments/results/${attemptId}`);
        }}
      >
        <DialogContent onInteractOutside={(e) => e.preventDefault()}>
          <DialogHeader>
            <DialogTitle>Attempt auto-submitted</DialogTitle>
            <DialogDescription>
              This attempt was submitted automatically because the time limit expired or the
              anti-cheat violation limit was reached. Your answers so far have been saved.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={() => router.replace(`/dashboard/assessments/results/${attemptId}`)}>
              View results
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
