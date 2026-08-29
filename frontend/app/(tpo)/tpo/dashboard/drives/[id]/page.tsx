"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { useAssessments } from "@/hooks/use-assessments";
import { useDriveDetail } from "@/hooks/use-drives";
import { useDeleteDrive, useUpdateDrive } from "@/hooks/use-tpo-drives";

const editSchema = z.object({
  job_title: z.string().min(1, "Job title is required."),
  description: z.string().min(1, "Description is required."),
  jd_text: z.string().min(1),
  required_skills: z.string().optional(),
  experience_required_years: z.preprocess(
    (v) => (v === "" || v === undefined ? undefined : v),
    z.coerce.number().min(0).max(50).optional()
  ),
  package: z.string().optional(),
  location: z.string().optional(),
  min_cgpa: z.preprocess(
    (v) => (v === "" || v === undefined ? undefined : v),
    z.coerce.number().min(0).max(10).optional()
  ),
  departments: z.string().optional(),
  batch_years: z.string().optional(),
  deadline: z.string().min(1),
  selection_process: z.string().optional(),
  required_assessment_id: z.string().optional(),
  assessment_min_score_pct: z.preprocess(
    (v) => (v === "" || v === undefined ? undefined : v),
    z.coerce.number().min(0).max(100).optional()
  ),
  assessment_deadline: z.string().optional(),
});

type EditFormValues = z.infer<typeof editSchema>;

function splitCsv(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

function toDatetimeLocal(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function TpoDriveDetailPage() {
  const params = useParams<{ id: string }>();
  const driveId = params.id;
  const router = useRouter();
  const { toast } = useToast();

  const { data: drive, isLoading } = useDriveDetail(driveId);
  const { data: assessments } = useAssessments();
  const updateDrive = useUpdateDrive(driveId);
  const deleteDrive = useDeleteDrive();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<EditFormValues>({ resolver: zodResolver(editSchema) });

  useEffect(() => {
    if (!drive) return;
    reset({
      job_title: drive.job_title,
      description: drive.description,
      jd_text: drive.jd_text,
      required_skills: drive.required_skills.join(", "),
      experience_required_years: drive.experience_required_years,
      package: drive.package ?? "",
      location: drive.location ?? "",
      min_cgpa: drive.eligibility.min_cgpa ?? undefined,
      departments: drive.eligibility.departments.join(", "),
      batch_years: drive.eligibility.batch_years.join(", "),
      deadline: toDatetimeLocal(drive.deadline),
      selection_process: drive.selection_process.join(", "),
      required_assessment_id: drive.required_assessment_id ?? "",
      assessment_min_score_pct: drive.assessment_min_score_pct ?? undefined,
      assessment_deadline: drive.assessment_deadline ? toDatetimeLocal(drive.assessment_deadline) : "",
    });
  }, [drive, reset]);

  const onSubmit = async (values: EditFormValues) => {
    try {
      await updateDrive.mutateAsync({
        job_title: values.job_title,
        description: values.description,
        jd_text: values.jd_text,
        required_skills: splitCsv(values.required_skills),
        experience_required_years: values.experience_required_years ?? 0,
        package: values.package || undefined,
        location: values.location || undefined,
        eligibility: {
          min_cgpa: values.min_cgpa ?? null,
          departments: splitCsv(values.departments),
          batch_years: splitCsv(values.batch_years)
            .map((y) => Number(y))
            .filter((y) => Number.isInteger(y)),
        },
        deadline: new Date(values.deadline).toISOString(),
        selection_process: splitCsv(values.selection_process),
        required_assessment_id: values.required_assessment_id || undefined,
        assessment_min_score_pct: values.assessment_min_score_pct,
        assessment_deadline: values.assessment_deadline ? new Date(values.assessment_deadline).toISOString() : undefined,
      });
      toast({ title: "Drive updated" });
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't save changes. Please try again.";
      toast({ title: "Update failed", description: detail, variant: "destructive" });
    }
  };

  const toggleStatus = async () => {
    if (!drive) return;
    try {
      await updateDrive.mutateAsync({ status: drive.status === "open" ? "closed" : "open" });
      toast({ title: drive.status === "open" ? "Drive closed" : "Drive reopened" });
    } catch {
      toast({ title: "Couldn't update status", variant: "destructive" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteDrive.mutateAsync(driveId);
      toast({ title: "Drive deleted" });
      router.push("/tpo/dashboard/drives");
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't delete this drive.";
      toast({ title: "Delete failed", description: detail, variant: "destructive" });
    }
  };

  if (isLoading || !drive) {
    return (
      <div className="max-w-2xl space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <Badge variant={drive.status === "open" ? "success" : "secondary"}>{drive.status}</Badge>
          </div>
          <h1 className="font-display text-2xl font-semibold">{drive.job_title}</h1>
          <p className="text-sm text-muted-foreground">{drive.company.name}</p>
        </div>
        <div className="flex gap-2">
          <Button asChild variant="secondary" size="sm">
            <Link href={`/tpo/dashboard/drives/${driveId}/applicants`}>View applicants</Link>
          </Button>
          <Button variant="outline" size="sm" onClick={toggleStatus} disabled={updateDrive.isPending}>
            {drive.status === "open" ? "Close drive" : "Reopen drive"}
          </Button>
          <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="destructive" size="sm">
                Delete
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Delete this drive?</DialogTitle>
                <DialogDescription>
                  This permanently removes &quot;{drive.job_title}&quot; and can&apos;t be undone. Existing
                  applications will remain in the database but the drive itself will no longer be visible.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="secondary" onClick={() => setDeleteDialogOpen(false)}>
                  Cancel
                </Button>
                <Button variant="destructive" onClick={handleDelete} disabled={deleteDrive.isPending}>
                  {deleteDrive.isPending ? "Deleting…" : "Delete permanently"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <Card>
        <form onSubmit={handleSubmit(onSubmit)}>
          <CardHeader>
            <CardTitle className="text-base">Edit details</CardTitle>
            <CardDescription>Company info is fixed after creation — only the role details can change.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="job_title">Job title</Label>
              <Input id="job_title" {...register("job_title")} />
              {errors.job_title && <p className="text-sm text-destructive">{errors.job_title.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">Short description</Label>
              <Textarea id="description" rows={2} {...register("description")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="jd_text">Full job description</Label>
              <Textarea id="jd_text" rows={6} {...register("jd_text")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="required_skills">Required skills (comma-separated)</Label>
              <Input id="required_skills" {...register("required_skills")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="experience_required_years">Experience required (years)</Label>
              <Input
                id="experience_required_years"
                type="number"
                step="0.5"
                min={0}
                max={50}
                {...register("experience_required_years")}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="package">Package</Label>
                <Input id="package" {...register("package")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="location">Location</Label>
                <Input id="location" {...register("location")} />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="deadline">Application deadline</Label>
              <Input id="deadline" type="datetime-local" {...register("deadline")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="selection_process">Selection process steps (comma-separated)</Label>
              <Input id="selection_process" {...register("selection_process")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="min_cgpa">Minimum CGPA</Label>
              <Input id="min_cgpa" type="number" step="0.01" min={0} max={10} {...register("min_cgpa")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="departments">Departments (comma-separated)</Label>
              <Input id="departments" {...register("departments")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="batch_years">Batch years (comma-separated)</Label>
              <Input id="batch_years" {...register("batch_years")} />
            </div>

            <div className="pt-4 border-t border-border space-y-4">
              <h3 className="font-semibold text-sm">Assessment Linkage (Optional)</h3>
              <div className="space-y-2">
                <Label htmlFor="required_assessment_id">Attached Assessment</Label>
                <select
                  id="required_assessment_id"
                  {...register("required_assessment_id")}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">No assessment required</option>
                  {assessments?.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.title} ({a.question_pool_size} questions, {Math.round(a.time_limit_sec / 60)} min)
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="assessment_min_score_pct">Cutoff Score (%)</Label>
                  <Input
                    id="assessment_min_score_pct"
                    type="number"
                    min={0}
                    max={100}
                    {...register("assessment_min_score_pct")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="assessment_deadline">Assessment Deadline</Label>
                  <Input id="assessment_deadline" type="datetime-local" {...register("assessment_deadline")} />
                </div>
              </div>
            </div>
          </CardContent>
          <CardFooter>
            <Button type="submit" disabled={isSubmitting || !isDirty}>
              {isSubmitting ? "Saving…" : "Save changes"}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
