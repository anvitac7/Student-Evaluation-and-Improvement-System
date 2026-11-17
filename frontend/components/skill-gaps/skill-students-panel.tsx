"use client";

import { useEffect, useState } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, Search, Users } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { useSkillGapStudents } from "@/hooks/use-skill-gaps";
import type {
  SkillGapEntry,
  SkillGapStudentFilter,
  StudentSkillGapClass,
} from "@/types/skill-gaps";

const PAGE_SIZE = 10;

const CLASSIFICATION_FILTERS: { value: SkillGapStudentFilter; label: string }[] = [
  { value: "all", label: "All students" },
  { value: "both", label: "Both evidence types" },
  { value: "demonstrated", label: "Assessment-demonstrated" },
  { value: "developing", label: "Developing" },
  { value: "not_demonstrated", label: "Not demonstrated" },
  { value: "reported_only", label: "Self-reported only" },
  { value: "insufficient_evidence", label: "Insufficient evidence" },
  { value: "no_evidence", label: "No evidence" },
];

const CLASSIFICATION_BADGE: Record<StudentSkillGapClass, { label: string; variant: "success" | "warning" | "destructive" | "secondary" | "outline" }> = {
  both: { label: "Both", variant: "success" },
  demonstrated: { label: "Demonstrated", variant: "success" },
  developing: { label: "Developing", variant: "warning" },
  not_demonstrated: { label: "Not demonstrated", variant: "destructive" },
  reported_only: { label: "Self-reported only", variant: "warning" },
  insufficient_evidence: { label: "Insufficient evidence", variant: "outline" },
  no_evidence: { label: "No evidence", variant: "secondary" },
};

function useDebouncedValue<T>(value: T, delay = 400): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/**
 * Student-level inspection for ONE skill: name, department/batch, whether
 * the skill is self-reported vs assessment-demonstrated, the eligible drive
 * assessment evidence for THIS skill only, and the proficiency
 * classification. Search + classification filter + pagination; only the
 * selected skill's evidence is shown (never unrelated assessment data).
 */
export function SkillStudentsPanel({ skill }: { skill: SkillGapEntry }) {
  const [search, setSearch] = useState("");
  const [classification, setClassification] = useState<SkillGapStudentFilter>("all");
  const [page, setPage] = useState(1);
  const debouncedSearch = useDebouncedValue(search);

  // Filter changes reset pagination.
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, classification, skill.skill_id]);

  const { data, isLoading, isError, refetch, isRefetching } = useSkillGapStudents(
    skill.skill_id,
    page,
    classification,
    debouncedSearch
  );

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Users className="h-4 w-4" /> Students — {skill.name}
        </CardTitle>
        <CardDescription>
          {skill.students_demonstrated} demonstrated ·{" "}
          {skill.students_reported_only} self-reported only ·{" "}
          {skill.students_both} both · {skill.students_no_evidence} with no evidence.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="sg-student-search">Search by name</Label>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                id="sg-student-search"
                className="pl-8"
                placeholder="Student name…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5 sm:w-64">
            <Label htmlFor="sg-student-classification">Evidence classification</Label>
            <Select
              value={classification}
              onValueChange={(value) => setClassification(value as SkillGapStudentFilter)}
            >
              <SelectTrigger id="sg-student-classification">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CLASSIFICATION_FILTERS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : isError || !data ? (
          <EmptyState
            icon={AlertCircle}
            title="Couldn't load students"
            description="Something went wrong while fetching the student list."
            action={
              <Button variant="outline" onClick={() => refetch()} disabled={isRefetching}>
                {isRefetching ? "Retrying…" : "Retry"}
              </Button>
            }
          />
        ) : data.entries.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No students match"
            description="No students match this search or classification filter."
          />
        ) : (
          <ul className="space-y-2">
            {data.entries.map((student) => {
              const badge = CLASSIFICATION_BADGE[student.classification];
              return (
                <li
                  key={student.student_id}
                  className="rounded-md border p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="font-medium">
                        {student.student_name}
                        <span className="ml-2 text-xs text-muted-foreground">
                          {student.department ?? "—"}
                          {student.batch_year ? ` · ${student.batch_year}` : ""}
                        </span>
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {student.self_reported
                          ? `Self-reported via ${student.self_reported_via.join(" + ")}`
                          : "Not self-reported"}
                        {student.questions_answered > 0
                          ? ` · ${student.correct_answers}/${student.questions_answered} correct on graded skill questions`
                          : ""}
                        {student.skill_accuracy_pct != null
                          ? ` (${student.skill_accuracy_pct}% accuracy)`
                          : ""}
                      </p>
                    </div>
                    <Badge variant={badge.variant}>{badge.label}</Badge>
                  </div>
                  {student.assessment_evidence.length > 0 && (
                    <ul className="mt-2 space-y-1 border-t pt-2 text-xs text-muted-foreground">
                      {student.assessment_evidence.map((evidence) => (
                        <li key={evidence.assessment_title}>
                          Drive assessment &quot;{evidence.assessment_title}&quot;:{" "}
                          {evidence.correct_answers}/{evidence.questions_answered} correct
                          across {evidence.attempts_used} submitted attempt
                          {evidence.attempts_used === 1 ? "" : "s"}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {total > PAGE_SIZE && !isError && data && (
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              Page {data.page} of {totalPages} · {total} student{total === 1 ? "" : "s"}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                disabled={page <= 1 || isRefetching}
              >
                <ChevronLeft className="h-4 w-4" /> Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                disabled={page >= totalPages || isRefetching}
              >
                Next <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
