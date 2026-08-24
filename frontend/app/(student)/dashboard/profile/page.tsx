"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Combobox } from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { useStudentProfile, useUpdateStudentProfile } from "@/hooks/use-student-profile";
import { DEPARTMENTS } from "@/lib/departments";

const currentYear = new Date().getFullYear();

/**
 * z.coerce.number() on an empty string input coerces to 0, not NaN
 * (Number("") === 0) — so a blank "optional" numeric field would silently
 * submit 0 instead of being omitted. This preprocesses blank/undefined
 * input to `undefined` before coercion so the field is genuinely optional.
 */
function optionalNumber(min: number, max: number, label = "Value") {
  return z.preprocess(
    (val) => (val === "" || val === undefined || val === null ? undefined : val),
    z.coerce
      .number()
      .min(min, `${label} cannot be less than ${min}.`)
      .max(max, `${label} cannot be more than ${max}.`)
      .optional()
  );
}

const profileSchema = z.object({
  name: z.string().min(1, "Name is required."),
  department: z.string().optional(),
  batch_year: optionalNumber(currentYear - 6, currentYear + 6, "Graduation year"),
  cgpa: optionalNumber(0, 10, "CGPA"),
  phone: z.string().optional(),
  linkedin_url: z.string().url("Enter a valid URL.").optional().or(z.literal("")),
  github_url: z.string().url("Enter a valid URL.").optional().or(z.literal("")),
  portfolio_url: z.string().url("Enter a valid URL.").optional().or(z.literal("")),
  skills: z.string().optional(),
  achievements: z.string().optional(),
  certificates: z.string().optional(),
});

type ProfileFormValues = z.infer<typeof profileSchema>;

function splitCsv(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

export default function StudentProfilePage() {
  const { data: profile, isLoading } = useStudentProfile();
  const updateProfile = useUpdateStudentProfile();
  const { toast } = useToast();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<ProfileFormValues>({ resolver: zodResolver(profileSchema) });

  useEffect(() => {
    if (!profile) return;
    reset({
      name: profile.name,
      department: profile.department ?? "",
      batch_year: profile.batch_year ?? undefined,
      cgpa: profile.cgpa ?? undefined,
      phone: profile.phone ?? "",
      linkedin_url: profile.linkedin_url ?? "",
      github_url: profile.github_url ?? "",
      portfolio_url: profile.portfolio_url ?? "",
      skills: profile.skills.join(", "),
      achievements: profile.achievements.join(", "),
      certificates: profile.certificates.join(", "),
    });
  }, [profile, reset]);

  const onSubmit = async (values: ProfileFormValues) => {
    try {
      await updateProfile.mutateAsync({
        name: values.name,
        department: values.department || undefined,
        batch_year: values.batch_year,
        cgpa: values.cgpa,
        phone: values.phone || undefined,
        linkedin_url: values.linkedin_url || undefined,
        github_url: values.github_url || undefined,
        portfolio_url: values.portfolio_url || undefined,
        skills: splitCsv(values.skills),
        achievements: splitCsv(values.achievements),
        certificates: splitCsv(values.certificates),
      });
      toast({ title: "Profile updated", description: "Your changes have been saved." });
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't save your profile. Please try again.";
      toast({ title: "Update failed", description: detail, variant: "destructive" });
    }
  };

  if (isLoading || !profile) {
    return (
      <div className="max-w-2xl space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 font-display text-2xl font-semibold">Your profile</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Kept up to date, this helps drive-eligibility checks and gives TPOs a clearer picture of you.
      </p>

      <Card>
        <form onSubmit={handleSubmit(onSubmit)}>
          <CardHeader>
            <CardTitle>Basic details</CardTitle>
            <CardDescription>{profile.profile_completeness_pct}% complete</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Full name</Label>
              <Input id="name" {...register("name")} />
              {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="department">Department</Label>
                <Combobox
                  id="department"
                  options={DEPARTMENTS}
                  placeholder="Type or select a department"
                  {...register("department")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="batch_year">Graduation year</Label>
                <Input
                  id="batch_year"
                  type="number"
                  min={currentYear - 6}
                  max={currentYear + 6}
                  step={1}
                  {...register("batch_year")}
                />
                {errors.batch_year && <p className="text-sm text-destructive">{errors.batch_year.message}</p>}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cgpa">CGPA</Label>
                <Input id="cgpa" type="number" step="0.01" min={0} max={10} {...register("cgpa")} />
                {errors.cgpa && <p className="text-sm text-destructive">{errors.cgpa.message}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="phone">Phone</Label>
                <Input id="phone" {...register("phone")} />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="linkedin_url">LinkedIn URL</Label>
              <Input id="linkedin_url" placeholder="https://linkedin.com/in/..." {...register("linkedin_url")} />
              {errors.linkedin_url && <p className="text-sm text-destructive">{errors.linkedin_url.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="github_url">GitHub URL</Label>
              <Input id="github_url" placeholder="https://github.com/..." {...register("github_url")} />
              {errors.github_url && <p className="text-sm text-destructive">{errors.github_url.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="portfolio_url">Portfolio URL</Label>
              <Input id="portfolio_url" placeholder="https://..." {...register("portfolio_url")} />
              {errors.portfolio_url && <p className="text-sm text-destructive">{errors.portfolio_url.message}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="skills">Skills (comma-separated)</Label>
              <Textarea id="skills" rows={2} placeholder="Python, React, SQL" {...register("skills")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="achievements">Achievements (comma-separated)</Label>
              <Textarea id="achievements" rows={2} {...register("achievements")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="certificates">Certificates (comma-separated)</Label>
              <Textarea id="certificates" rows={2} {...register("certificates")} />
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
