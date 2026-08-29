"use client";

import { useState } from "react";
import { Download, FileText, RefreshCw, Upload } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { useToast } from "@/hooks/use-toast";
import {
  downloadResumeFile,
  useApplyAutofill,
  useAutofillSuggestion,
  useReparseResume,
  useResumeDetail,
  useResumeHistory,
  useUploadResume,
} from "@/hooks/use-resumes";
import { cn } from "@/lib/utils";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export default function ResumePage() {
  const { data: history, isLoading: historyLoading } = useResumeHistory();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const activeId = selectedId ?? history?.find((r) => r.is_active)?.id ?? history?.[0]?.id ?? null;

  const { data: detail, isLoading: detailLoading } = useResumeDetail(activeId);
  const { data: suggestion } = useAutofillSuggestion(activeId);
  const applyAutofill = useApplyAutofill();
  const [autofillDismissed, setAutofillDismissed] = useState(false);

  const uploadResume = useUploadResume();
  const reparseResume = useReparseResume();
  const { toast } = useToast();

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const uploaded = await uploadResume.mutateAsync(file);
      setSelectedId(uploaded.id);
      setAutofillDismissed(false);
      toast({
        title: "Resume uploaded",
        description: `${file.name} uploaded successfully.`,
      });
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Upload failed. Please try a different file.";
      toast({ title: "Upload failed", description: detail, variant: "destructive" });
    }
  };

  const handleApplyAutofill = async () => {
    if (!activeId || !suggestion) return;
    try {
      await applyAutofill.mutateAsync({ resumeId: activeId, patch: suggestion.patch });
      setAutofillDismissed(true);
      toast({ title: "Profile updated", description: "We filled in your profile from your resume." });
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't update your profile. Please try again.";
      toast({ title: "Autofill failed", description: detail, variant: "destructive" });
    }
  };

  const handleReparse = async () => {
    if (!activeId) return;
    try {
      await reparseResume.mutateAsync(activeId);
      toast({ title: "Resume re-parsed", description: "Parsed data has been refreshed." });
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't re-parse this resume.";
      toast({ title: "Re-parse failed", description: detail, variant: "destructive" });
    }
  };

  const handleDownload = async () => {
    if (!activeId || !detail) return;
    try {
      await downloadResumeFile(activeId, detail.original_filename);
    } catch {
      toast({ title: "Download failed", description: "Please try again.", variant: "destructive" });
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold">Resume</h1>
          <p className="text-sm text-muted-foreground">Upload a resume and review what our parser extracted.</p>
        </div>
        <label>
          <Button asChild disabled={uploadResume.isPending}>
            <span className="cursor-pointer">
              <Upload className="mr-2 h-4 w-4" />
              {uploadResume.isPending ? "Uploading…" : "Upload new version"}
            </span>
          </Button>
          <input type="file" accept=".pdf,.doc,.docx" className="hidden" onChange={handleUpload} />
        </label>
      </div>

      {historyLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : !history || history.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No resume uploaded yet"
          description="Upload a PDF or Word resume to get started. It'll be parsed automatically and used for drive applications."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle className="text-base">Versions</CardTitle>
              <CardDescription>{history.length} uploaded</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {history.map((resume) => (
                <button
                  key={resume.id}
                  onClick={() => setSelectedId(resume.id)}
                  className={cn(
                    "flex w-full flex-col items-start gap-1 rounded-md border px-3 py-2 text-left text-sm transition-colors",
                    resume.id === activeId
                      ? "border-primary bg-secondary"
                      : "border-border hover:bg-secondary/50"
                  )}
                >
                  <div className="flex w-full items-center justify-between">
                    <span className="truncate font-medium">v{resume.version}</span>
                    {resume.is_active && <Badge variant="success">Active</Badge>}
                  </div>
                  <span className="truncate text-xs text-muted-foreground">{resume.original_filename}</span>
                  <span className="text-xs text-muted-foreground">{formatDate(resume.uploaded_at)}</span>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader className="flex flex-row items-start justify-between space-y-0">
              <div>
                <CardTitle className="text-base">Parsed data</CardTitle>
                <CardDescription>{detail?.original_filename}</CardDescription>
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={handleReparse} disabled={reparseResume.isPending}>
                  <RefreshCw className={cn("mr-2 h-3.5 w-3.5", reparseResume.isPending && "animate-spin")} />
                  Re-parse
                </Button>
                <Button size="sm" variant="secondary" onClick={handleDownload}>
                  <Download className="mr-2 h-3.5 w-3.5" />
                  Download
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {detailLoading || !detail ? (
                <Skeleton className="h-64 w-full" />
              ) : !detail.parsed ? (
                <p className="text-sm text-muted-foreground">
                  This resume hasn&apos;t been parsed yet, or parsing failed. Try re-parsing it.
                </p>
              ) : (
                <div className="space-y-4 text-sm">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-muted-foreground">Name: </span>
                      {detail.parsed.name ?? "—"}
                    </div>
                    <div>
                      <span className="text-muted-foreground">Email: </span>
                      {detail.parsed.email ?? "—"}
                    </div>
                    <div>
                      <span className="text-muted-foreground">Phone: </span>
                      {detail.parsed.phone ?? "—"}
                    </div>
                    <div>
                      <span className="text-muted-foreground">Experience: </span>
                      {detail.experience_years !== null ? `${detail.experience_years} yrs` : "—"}
                    </div>
                  </div>

                  <div>
                    <p className="mb-1 font-medium">Skills</p>
                    {detail.skill_set.length === 0 ? (
                      <p className="text-muted-foreground">None detected.</p>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {detail.skill_set.map((skill) => (
                          <Badge key={skill} variant="secondary">
                            {skill}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>

                  {detail.parsed.education.length > 0 && (
                    <div>
                      <p className="mb-1 font-medium">Education</p>
                      <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
                        {detail.parsed.education.map((edu, i) => (
                          <li key={i}>{Object.values(edu).filter(Boolean).join(" — ")}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {detail.parsed.experience.length > 0 && (
                    <div>
                      <p className="mb-1 font-medium">Experience</p>
                      <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
                        {detail.parsed.experience.map((exp, i) => (
                          <li key={i}>{Object.values(exp).filter(Boolean).join(" — ")}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {detail.parsed.projects.length > 0 && (
                    <div>
                      <p className="mb-1 font-medium">Projects</p>
                      <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
                        {detail.parsed.projects.map((proj, i) => (
                          <li key={i}>{Object.values(proj).filter(Boolean).join(" — ")}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
