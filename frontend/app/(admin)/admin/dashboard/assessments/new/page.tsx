"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Tags } from "lucide-react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { useToast } from "@/hooks/use-toast";
import { useCreateAssessment } from "@/hooks/use-admin-assessments";
import { useCategories } from "@/hooks/use-admin-questions";

const assessmentSchema = z.object({
  title: z.string().min(1, "Title is required."),
  category_ids: z.array(z.string()).min(1, "Select at least one category."),
  question_pool_size: z.coerce.number().int().min(1).max(100),
  time_limit_minutes: z.coerce.number().int().min(1).max(300),
  max_violations: z.coerce.number().int().min(1).max(20),
  require_fullscreen: z.boolean(),
  type: z.enum(["practice", "drive"]),
});

type AssessmentFormValues = z.infer<typeof assessmentSchema>;

export default function NewAssessmentPage() {
  const router = useRouter();
  const { toast } = useToast();
  const { data: categories, isLoading: categoriesLoading } = useCategories();
  const createAssessment = useCreateAssessment();

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<AssessmentFormValues>({
    resolver: zodResolver(assessmentSchema),
    defaultValues: {
      category_ids: [],
      question_pool_size: 10,
      time_limit_minutes: 30,
      max_violations: 3,
      require_fullscreen: true,
      type: "practice",
    },
  });

  const selectedCategoryIds = watch("category_ids");

  const toggleCategory = (id: string) => {
    const current = selectedCategoryIds ?? [];
    setValue(
      "category_ids",
      current.includes(id) ? current.filter((c) => c !== id) : [...current, id],
      { shouldValidate: true }
    );
  };

  const onSubmit = async (values: AssessmentFormValues) => {
    try {
      const created = await createAssessment.mutateAsync({
        title: values.title,
        category_ids: values.category_ids,
        question_pool_size: values.question_pool_size,
        time_limit_sec: values.time_limit_minutes * 60,
        max_violations: values.max_violations,
        require_fullscreen: values.require_fullscreen,
        type: values.type,
      });
      toast({ title: "Assessment created", description: `${created.title} is now available to students.` });
      router.push("/admin/dashboard/assessments");
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't create the assessment. Please try again.";
      toast({ title: "Creation failed", description: detail, variant: "destructive" });
    }
  };

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 font-display text-2xl font-semibold">New assessment</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Difficulty adapts automatically as students answer — correct answers pull harder questions, wrong answers
        pull easier ones.
      </p>

      {!categoriesLoading && (!categories || categories.length === 0) ? (
        <EmptyState
          icon={Tags}
          title="No categories yet"
          description="Create at least one question category with some questions in it before building an assessment."
        />
      ) : (
        <Card>
          <form onSubmit={handleSubmit(onSubmit)}>
            <CardHeader>
              <CardTitle className="text-base">Assessment details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="title">Title</Label>
                <Input id="title" placeholder="e.g. Core CS Fundamentals" {...register("title")} />
                {errors.title && <p className="text-sm text-destructive">{errors.title.message}</p>}
              </div>

              <div className="space-y-2">
                <Label>Assessment type</Label>
                <div className="flex gap-2">
                  {(["practice", "drive"] as const).map((option) => {
                    const active = watch("type") === option;
                    return (
                      <button
                        type="button"
                        key={option}
                        onClick={() => setValue("type", option, { shouldValidate: true })}
                        className={`rounded-md border px-3 py-1.5 text-sm capitalize transition-colors ${
                          active ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-secondary"
                        }`}
                      >
                        {option}
                      </button>
                    );
                  })}
                </div>
                <p className="text-xs text-muted-foreground">
                  Practice assessments are for student self-improvement and are excluded from drive
                  rankings. Drive assessments are linked to a drive by a TPO and appear in drive rankings.
                </p>
              </div>

              <div className="space-y-2">
                <Label>Categories to draw questions from</Label>
                {categoriesLoading ? (
                  <Skeleton className="h-20 w-full" />
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {categories?.map((c) => {
                      const active = selectedCategoryIds?.includes(c.id);
                      return (
                        <button
                          type="button"
                          key={c.id}
                          onClick={() => toggleCategory(c.id)}
                          className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
                            active
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-border hover:bg-secondary"
                          }`}
                        >
                          {c.name}
                        </button>
                      );
                    })}
                  </div>
                )}
                {errors.category_ids && <p className="text-sm text-destructive">{errors.category_ids.message}</p>}
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="question_pool_size">Number of questions</Label>
                  <Input id="question_pool_size" type="number" min={1} max={100} {...register("question_pool_size")} />
                  {errors.question_pool_size && (
                    <p className="text-sm text-destructive">{errors.question_pool_size.message}</p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="time_limit_minutes">Time limit (minutes)</Label>
                  <Input id="time_limit_minutes" type="number" min={1} max={300} {...register("time_limit_minutes")} />
                  {errors.time_limit_minutes && (
                    <p className="text-sm text-destructive">{errors.time_limit_minutes.message}</p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="max_violations">Max anti-cheat violations before auto-submit</Label>
                <Input id="max_violations" type="number" min={1} max={20} {...register("max_violations")} />
              </div>

              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4 rounded border-input" {...register("require_fullscreen")} />
                Require fullscreen mode during the attempt
              </label>
            </CardContent>
            <CardFooter className="gap-2">
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Creating…" : "Create assessment"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => router.back()}>
                Cancel
              </Button>
            </CardFooter>
          </form>
        </Card>
      )}
    </div>
  );
}
