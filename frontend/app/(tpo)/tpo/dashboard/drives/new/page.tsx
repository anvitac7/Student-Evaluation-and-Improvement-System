"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { useAssessments } from "@/hooks/use-assessments";
import { useCreateDrive } from "@/hooks/use-tpo-drives";

const driveSchema = z.object({
  company_name: z.string().min(1, "Company name is required."),
  company_description: z.string().optional(),
  company_website: z.string().url("Enter a valid URL.").optional().or(z.literal("")),
  company_industry: z.string().optional(),
  job_title: z.string().min(1, "Job title is required."),
  description: z.string().min(1, "Description is required."),
  jd_text: z.string().min(1, "Paste the full job description text."),
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
  deadline: z.string().min(1, "Deadline is required."),
  selection_process: z.string().optional(),
  required_assessment_id: z.string().optional(),
  assessment_min_score_pct: z.preprocess(
    (v) => (v === "" || v === undefined ? undefined : v),
    z.coerce.number().min(0).max(100).optional()
  ),
  assessment_deadline: z.string().optional(),
});

type DriveFormValues = z.infer<typeof driveSchema>;

function splitCsv(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

export default function NewDrivePage() {
  const router = useRouter();
  const { toast } = useToast();
  const createDrive = useCreateDrive();
  const { data: assessments } = useAssessments();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<DriveFormValues>({ resolver: zodResolver(driveSchema) });

  const onSubmit = async (values: DriveFormValues) => {
    try {
      const created = await createDrive.mutateAsync({
        company_name: values.company_name,
        company_description: values.company_description || undefined,
        company_website: values.company_website || undefined,
        company_industry: values.company_industry || undefined,
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
      toast({ title: "Drive created", description: `${created.job_title} is now live.` });
      router.push(`/tpo/dashboard/drives/${created.id}`);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't create the drive. Please try again.";
      toast({ title: "Creation failed", description: detail, variant: "destructive" });
    }
  };

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 font-display text-2xl font-semibold">New placement drive</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Reusing a company name links this drive to that company&apos;s existing profile.
      </p>

      <Card>
        <form onSubmit={handleSubmit(onSubmit)}>
          <CardHeader>
            <CardTitle>Company</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="company_name">Company name</Label>
                <Input id="company_name" {...register("company_name")} />
                {errors.company_name && <p className="text-sm text-destructive">{errors.company_name.message}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="company_industry">Industry</Label>
                <Input id="company_industry" {...register("company_industry")} />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="company_website">Website</Label>
              <Input id="company_website" placeholder="https://..." {...register("company_website")} />
              {errors.company_website && <p className="text-sm text-destructive">{errors.company_website.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="company_description">Company description</Label>
              <Textarea id="company_description" rows={2} {...register("company_description")} />
            </div>
          </CardContent>

          <CardHeader>
            <CardTitle>Role</CardTitle>
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
              {errors.description && <p className="text-sm text-destructive">{errors.description.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="jd_text">Full job description</Label>
              <Textarea id="jd_text" rows={6} {...register("jd_text")} />
              {errors.jd_text && <p className="text-sm text-destructive">{errors.jd_text.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="required_skills">Required skills (comma-separated)</Label>
              <Input id="required_skills" placeholder="Python, React, SQL" {...register("required_skills")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="experience_required_years">Experience required (years)</Label>
              <Input
                id="experience_required_years"
                type="number"
                step="0.5"
                min={0}
                max={50}
                placeholder="0 for entry-level / freshers"
                {...register("experience_required_years")}
              />
              {errors.experience_required_years && (
                <p className="text-sm text-destructive">{errors.experience_required_years.message}</p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="package">Package</Label>
                <Input id="package" placeholder="12 LPA" {...register("package")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="location">Location</Label>
                <Input id="location" {...register("location")} />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="deadline">Application deadline</Label>
              <Input id="deadline" type="datetime-local" {...register("deadline")} />
              {errors.deadline && <p className="text-sm text-destructive">{errors.deadline.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="selection_process">Selection process steps (comma-separated)</Label>
              <Input id="selection_process" placeholder="Online test, Technical interview, HR round" {...register("selection_process")} />
            </div>
          </CardContent>

          <CardHeader>
            <CardTitle>Eligibility</CardTitle>
            <CardDescription>Leave a field blank to leave that criterion open to everyone.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="min_cgpa">Minimum CGPA</Label>
              <Input id="min_cgpa" type="number" step="0.01" min={0} max={10} {...register("min_cgpa")} />
              {errors.min_cgpa && <p className="text-sm text-destructive">{errors.min_cgpa.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="departments">Departments (comma-separated)</Label>
              <Input id="departments" placeholder="CS, IT" {...register("departments")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="batch_years">Batch years (comma-separated)</Label>
              <Input id="batch_years" placeholder="2026, 2027" {...register("batch_years")} />
            </div>
          </CardContent>

          <CardHeader>
            <CardTitle>Assessment Linkage (Optional)</CardTitle>
            <CardDescription>
              Require candidates to take an admin-created adaptive test before final shortlisting.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="required_assessment_id">Select Required Assessment</Label>
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
                <Label htmlFor="assessment_min_score_pct">Passing Cutoff Score (%)</Label>
                <Input
                  id="assessment_min_score_pct"
                  type="number"
                  placeholder="e.g. 60"
                  min={0}
                  max={100}
                  {...register("assessment_min_score_pct")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="assessment_deadline">Assessment Due Date</Label>
                <Input id="assessment_deadline" type="datetime-local" {...register("assessment_deadline")} />
              </div>
            </div>
          </CardContent>

          <CardFooter className="gap-2">
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Creating…" : "Create drive"}
            </Button>
            <Button type="button" variant="secondary" onClick={() => router.back()}>
              Cancel
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
