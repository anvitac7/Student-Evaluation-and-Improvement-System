"use client";

import { useParams } from "next/navigation";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Download,
  FileSpreadsheet,
  Filter,
  Play,
  Sparkles,
  Users,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/shared/empty-state";
import { StatCard } from "@/components/shared/stat-card";
import { useToast } from "@/hooks/use-toast";
import { useStudentKnowledgeStates } from "@/hooks/use-assessments";
import { downloadResumeFile } from "@/hooks/use-resumes";
import {
  exportApplicationsCsv,
  useBulkUpdateApplicationStatus,
  useDriveApplicants,
  useRecommendedShortlist,
  useScreeningSummary,
  useTriggerScreening,
  useUpdateApplicationStatus,
} from "@/hooks/use-tpo-drives";
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

function assessmentBadge(status: string, score: number | null | undefined) {
  switch (status) {
    case "passed":
      return (
        <Badge variant="success" className="gap-1">
          <CheckCircle2 className="h-3 w-3" /> Passed ({score ? Math.round(score) : 0}%)
        </Badge>
      );
    case "failed":
      return (
        <Badge variant="destructive" className="gap-1">
          <XCircle className="h-3 w-3" /> Failed ({score ? Math.round(score) : 0}%)
        </Badge>
      );
    case "pending":
      return (
        <Badge variant="secondary" className="gap-1">
          <Clock className="h-3 w-3" /> Pending Test
        </Badge>
      );
    case "expired":
      return (
        <Badge variant="outline" className="text-destructive border-destructive gap-1">
          <AlertCircle className="h-3 w-3" /> Expired
        </Badge>
      );
    default:
      return null;
  }
}

function ApplicantMastery({ studentId }: { studentId: string }) {
  const { data: states, isLoading } = useStudentKnowledgeStates(studentId);

  if (isLoading) return <Skeleton className="h-16 w-full" />;
  if (!states || states.length === 0) {
    return <p className="text-sm text-muted-foreground">No assessment attempts yet.</p>;
  }
  return (
    <div className="space-y-2">
      {states.map((s) => (
        <div key={s.skill_tag} className="flex items-center gap-3">
          <Badge variant="outline" className="w-28 shrink-0 justify-center truncate">
            {s.skill_tag}
          </Badge>
          <Progress value={s.mastery_pct} className="flex-1" />
          <span className="w-10 shrink-0 text-right text-sm text-muted-foreground">
            {Math.round(s.mastery_pct)}%
          </span>
        </div>
      ))}
    </div>
  );
}

export default function DriveApplicantsPage() {
  const params = useParams<{ id: string }>();
  const driveId = params.id;

  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [assessmentFilter, setAssessmentFilter] = useState<string>("all");
  const [eligibleOnly, setEligibleOnly] = useState<boolean>(false);
  const [sortBy, setSortBy] = useState<string>("applied_at");
  const [sortOrder, setSortOrder] = useState<string>("desc");

  const [selectedAppIds, setSelectedAppIds] = useState<string[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Rejection modal state
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectingTarget, setRejectingTarget] = useState<{ id: string; bulk: boolean } | null>(null);
  const [selectedReasons, setSelectedReasons] = useState<string[]>([]);
  const [rejectionNote, setRejectionNote] = useState("");

  const filters = useMemo(() => {
    const p: Record<string, any> = {
      sort_by: sortBy,
      sort_order: sortOrder,
      eligible_only: eligibleOnly,
    };
    if (statusFilter !== "all") p.status = statusFilter;
    if (assessmentFilter !== "all") p.assessment_status = assessmentFilter;
    return p;
  }, [statusFilter, assessmentFilter, eligibleOnly, sortBy, sortOrder]);

  const { data: applicants, isLoading } = useDriveApplicants(driveId, filters);
  const { data: summary } = useScreeningSummary(driveId);
  const triggerScreening = useTriggerScreening(driveId);
  const updateStatus = useUpdateApplicationStatus(driveId);
  const bulkUpdate = useBulkUpdateApplicationStatus(driveId);
  const { toast } = useToast();

  const handleSelectAll = () => {
    if (!applicants) return;
    if (selectedAppIds.length === applicants.length) {
      setSelectedAppIds([]);
    } else {
      setSelectedAppIds(applicants.map((a) => a.id));
    }
  };

  const handleToggleSelect = (id: string) => {
    setSelectedAppIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const handleTriggerScreening = async () => {
    try {
      await triggerScreening.mutateAsync();
      toast({ title: "Screening completed", description: "All applicants have been evaluated & scored." });
    } catch (err: any) {
      toast({ title: "Screening failed", description: err.message, variant: "destructive" });
    }
  };

  const handleExportCsv = async () => {
    try {
      await exportApplicationsCsv(driveId);
      toast({ title: "CSV exported successfully" });
    } catch {
      toast({ title: "Export failed", variant: "destructive" });
    }
  };

  const handleStatusChange = async (applicationId: string, status: ApplicationStatus) => {
    if (status === "rejected") {
      setRejectingTarget({ id: applicationId, bulk: false });
      setSelectedReasons([]);
      setRejectionNote("");
      setRejectModalOpen(true);
      return;
    }
    try {
      await updateStatus.mutateAsync({ applicationId, status });
      toast({ title: `Status updated to ${status}` });
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't update status.";
      toast({ title: "Update failed", description: detail, variant: "destructive" });
    }
  };

  const handleBulkStatus = async (status: ApplicationStatus) => {
    if (selectedAppIds.length === 0) return;
    if (status === "rejected") {
      setRejectingTarget({ id: "", bulk: true });
      setSelectedReasons([]);
      setRejectionNote("");
      setRejectModalOpen(true);
      return;
    }
    try {
      const res = await bulkUpdate.mutateAsync({
        application_ids: selectedAppIds,
        status,
      });
      toast({ title: `Updated ${res.updated_count} applicants to ${status}` });
      setSelectedAppIds([]);
    } catch (err: any) {
      toast({ title: "Bulk update failed", description: err.message, variant: "destructive" });
    }
  };

  const confirmRejection = async () => {
    if (!rejectingTarget) return;
    try {
      if (rejectingTarget.bulk) {
        const res = await bulkUpdate.mutateAsync({
          application_ids: selectedAppIds,
          status: "rejected",
          rejection_reasons: selectedReasons,
          rejection_note: rejectionNote || undefined,
        });
        toast({ title: `Rejected ${res.updated_count} applicants` });
        setSelectedAppIds([]);
      } else {
        await updateStatus.mutateAsync({
          applicationId: rejectingTarget.id,
          status: "rejected",
          rejectionReasons: selectedReasons,
          rejectionNote: rejectionNote || undefined,
        });
        toast({ title: "Applicant rejected with feedback" });
      }
      setRejectModalOpen(false);
    } catch (err: any) {
      toast({ title: "Rejection failed", description: err.message, variant: "destructive" });
    }
  };

  const handleDownload = async (resumeId: string, filename: string) => {
    try {
      await downloadResumeFile(resumeId, filename);
    } catch {
      toast({ title: "Download failed", variant: "destructive" });
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold">Applicant Management & Screening</h1>
          <p className="text-sm text-muted-foreground">
            Ranked review, automated eligibility screening, assessments, and decision workflows.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleTriggerScreening}
            disabled={triggerScreening.isPending}
            className="gap-1.5"
          >
            <Play className="h-3.5 w-3.5" />
            {triggerScreening.isPending ? "Screening…" : "Run Screening Engine"}
          </Button>
          <Button size="sm" variant="secondary" onClick={handleExportCsv} className="gap-1.5">
            <FileSpreadsheet className="h-3.5 w-3.5" /> Export CSV
          </Button>
        </div>
      </div>

      {/* Screening Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          <StatCard label="Total Applicants" value={summary.total_applications} icon={Users} />
          <StatCard label="Eligible" value={summary.eligible} icon={CheckCircle2} />
          <StatCard label="Test Passed" value={summary.assessment_passed} icon={Sparkles} />
          <StatCard label="Test Pending" value={summary.assessment_pending} icon={Clock} />
          <StatCard label="Recommended" value={summary.recommended_shortlist} icon={Sparkles} />
          <StatCard label="Shortlisted" value={summary.shortlisted} icon={CheckCircle2} />
        </div>
      )}

      {/* Controls & Filters Bar */}
      <Card>
        <CardContent className="p-4 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1">
                <Filter className="h-3 w-3" /> Filters:
              </span>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-32 h-8 text-xs">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Statuses</SelectItem>
                  <SelectItem value="applied">Applied</SelectItem>
                  <SelectItem value="shortlisted">Shortlisted</SelectItem>
                  <SelectItem value="rejected">Rejected</SelectItem>
                  <SelectItem value="selected">Selected</SelectItem>
                </SelectContent>
              </Select>

              <Select value={assessmentFilter} onValueChange={setAssessmentFilter}>
                <SelectTrigger className="w-36 h-8 text-xs">
                  <SelectValue placeholder="Assessment" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Assessments</SelectItem>
                  <SelectItem value="passed">Passed</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                  <SelectItem value="expired">Expired</SelectItem>
                </SelectContent>
              </Select>

              <Button
                size="sm"
                variant={eligibleOnly ? "default" : "outline"}
                onClick={() => setEligibleOnly(!eligibleOnly)}
                className="h-8 text-xs"
              >
                Eligible Only
              </Button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Sort:
              </span>
              <Select
                value={`${sortBy}_${sortOrder}`}
                onValueChange={(val) => {
                  if (!val) return;
                  const [b, o] = val.split("_");
                  setSortBy(b || "applied_at");
                  setSortOrder(o || "desc");
                }}
              >
                <SelectTrigger className="w-44 h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="final_score_desc">Highest Match Score</SelectItem>
                  <SelectItem value="applied_at_desc">Newest Applied</SelectItem>
                  <SelectItem value="applied_at_asc">Oldest Applied</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Bulk Action Controls */}
          {selectedAppIds.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-border bg-muted/40 p-2 rounded">
              <span className="text-sm font-medium">
                {selectedAppIds.length} candidate(s) selected
              </span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => handleBulkStatus("shortlisted")}>
                  Shortlist Selected
                </Button>
                <Button size="sm" variant="destructive" onClick={() => handleBulkStatus("rejected")}>
                  Reject Selected
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSelectedAppIds([])}>
                  Deselect
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Applicant List */}
      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : !applicants || applicants.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No applicants found"
          description="Try adjusting your filters or wait for candidates to apply."
        />
      ) : (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between py-3 px-4 border-b border-border">
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                checked={selectedAppIds.length === applicants.length && applicants.length > 0}
                onChange={handleSelectAll}
                className="h-4 w-4 rounded border-gray-300"
              />
              <CardTitle className="text-sm font-medium">
                Showing {applicants.length} Applicant(s)
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="p-0 divide-y divide-border">
            {applicants.map((applicant) => {
              const expanded = expandedId === applicant.id;
              const isSelected = selectedAppIds.includes(applicant.id);

              return (
                <div key={applicant.id} className={isSelected ? "bg-muted/20" : ""}>
                  <div className="flex flex-wrap items-center justify-between gap-3 p-4">
                    <div className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => handleToggleSelect(applicant.id)}
                        className="h-4 w-4 rounded border-gray-300"
                      />
                      <button
                        onClick={() => setExpandedId(expanded ? null : applicant.id)}
                        className="flex items-center gap-2 text-left"
                      >
                        {expanded ? (
                          <ChevronUp className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        )}
                        <div>
                          <div className="flex items-center gap-2">
                            <p className="font-semibold text-base">{applicant.student_name}</p>
                            {applicant.eligibility_passed === false && (
                              <Badge variant="destructive" className="text-xs">
                                Ineligible
                              </Badge>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground">
                            {applicant.student_department ?? "Department —"} · CGPA:{" "}
                            {applicant.student_cgpa ?? "N/A"} · Applied {formatDate(applicant.applied_at)}
                          </p>
                        </div>
                      </button>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      {/* Match Score Badge */}
                      {applicant.final_score !== null && applicant.final_score !== undefined && (
                        <Badge variant="outline" className="font-mono gap-1 text-primary border-primary">
                          <Sparkles className="h-3 w-3" />
                          {Math.round(applicant.final_score * 100)}% Match
                        </Badge>
                      )}

                      {/* Assessment Badge */}
                      {assessmentBadge(applicant.assessment_status || "not_required", applicant.assessment_score_pct)}

                      {/* Application Status Badge */}
                      <Badge variant={statusVariant(applicant.status)}>{applicant.status}</Badge>

                      {/* Resume Download */}
                      {applicant.resume_filename && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleDownload(applicant.resume_id, applicant.resume_filename!)}
                          className="h-8 gap-1"
                        >
                          <Download className="h-3 w-3" /> Resume
                        </Button>
                      )}

                      {/* Status Dropdown */}
                      <Select
                        value={applicant.status}
                        onValueChange={(value) => handleStatusChange(applicant.id, value as ApplicationStatus)}
                      >
                        <SelectTrigger className="w-32 h-8 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="applied">Applied</SelectItem>
                          <SelectItem value="shortlisted">Shortlist</SelectItem>
                          <SelectItem value="rejected">Reject</SelectItem>
                          <SelectItem value="selected">Select</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  {/* Expanded Breakdown Drawer */}
                  {expanded && (
                    <div className="border-t border-border bg-muted/40 p-4 space-y-4">
                      {/* Match breakdown terms */}
                      {applicant.final_score !== null && applicant.final_score !== undefined && (
                        <div className="rounded border bg-card p-3 space-y-2">
                          <p className="text-xs font-semibold uppercase text-muted-foreground">
                            Deterministic Match Breakdown (40% Sem + 30% Skill + 20% Exp + 10% Test)
                          </p>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                            <div>Semantic Score: <b>{Math.round((applicant.semantic_score || 0) * 100)}%</b></div>
                            <div>Skills Match: <b>{Math.round((applicant.skills_score || 0) * 100)}%</b></div>
                            <div>Exp Fit: <b>{Math.round((applicant.experience_score || 0) * 100)}%</b></div>
                            <div>Assessment: <b>{applicant.assessment_score_pct ? `${Math.round(applicant.assessment_score_pct)}%` : "N/A"}</b></div>
                          </div>

                          <div className="pt-2">
                            <p className="text-xs font-medium mb-1">Skills Comparison:</p>
                            <div className="flex flex-wrap gap-1">
                              {applicant.matched_skills?.map((skill) => (
                                <Badge key={skill} variant="success" className="text-xs">
                                  ✓ {skill}
                                </Badge>
                              ))}
                              {applicant.missing_skills?.map((skill) => (
                                <Badge key={skill} variant="outline" className="text-xs text-muted-foreground">
                                  ✗ {skill}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Ineligibility notice if any */}
                      {applicant.eligibility_reasons && applicant.eligibility_reasons.length > 0 && (
                        <div className="rounded border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
                          <p className="font-semibold">Ineligibility Factors:</p>
                          <ul className="list-disc list-inside">
                            {applicant.eligibility_reasons.map((r, i) => (
                              <li key={i}>{r}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Rejection note if already rejected */}
                      {applicant.status === "rejected" && applicant.rejection_reasons && (
                        <div className="rounded border bg-card p-3 text-xs space-y-1">
                          <p className="font-semibold text-destructive">Recorded Rejection Reasons:</p>
                          <p className="text-muted-foreground">{applicant.rejection_reasons.join(", ")}</p>
                          {applicant.rejection_note && <p className="italic">{applicant.rejection_note}</p>}
                        </div>
                      )}

                      {/* Knowledge state mastery */}
                      <div>
                        <p className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                          Knowledge Tracing Skill Profile
                        </p>
                        <ApplicantMastery studentId={applicant.student_id} />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* Structured Rejection Modal */}
      <Dialog open={rejectModalOpen} onOpenChange={setRejectModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Candidate with Feedback</DialogTitle>
            <DialogDescription>
              Select structured reasons for rejection. This ensures fair, explainable feedback for the student.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-xs font-semibold">Structured Rejection Reasons:</label>
              <div className="grid grid-cols-1 gap-1.5 text-xs">
                {[
                  { id: "skill_gap", label: "Core Technical Skill Gap" },
                  { id: "low_match_score", label: "Low Overall Profile Match Score" },
                  { id: "low_assessment_score", label: "Assessment Score Below Cutoff" },
                  { id: "assessment_not_attempted", label: "Assessment Not Attempted Before Deadline" },
                  { id: "eligibility", label: "Academic / Department Eligibility Criteria" },
                  { id: "experience_gap", label: "Insufficient Hands-on Project Experience" },
                  { id: "other", label: "Other Placement Policy Criteria" },
                ].map((item) => (
                  <label key={item.id} className="flex items-center gap-2 p-1.5 rounded hover:bg-muted cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedReasons.includes(item.id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedReasons([...selectedReasons, item.id]);
                        } else {
                          setSelectedReasons(selectedReasons.filter((r) => r !== item.id));
                        }
                      }}
                      className="h-3.5 w-3.5 rounded"
                    />
                    <span>{item.label}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-semibold">Advisor Feedback Note (Optional):</label>
              <Textarea
                placeholder="Constructive advice or specific recommendations for the student..."
                value={rejectionNote}
                onChange={(e) => setRejectionNote(e.target.value)}
                rows={3}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectModalOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmRejection}>
              Confirm Rejection
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
