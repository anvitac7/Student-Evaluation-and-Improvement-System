"use client";

import { GraduationCap, Info } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { SkillGapEntry } from "@/types/skill-gaps";

/**
 * Explainable training recommendations: the highest-priority skills by
 * backend-computed priority score, each with the exact numbers that justify
 * it. No course providers, certifications, costs or placement claims are
 * invented here — the recommendation is simply "train these skills first,
 * because demand is high and demonstrated proficiency is low".
 */
export function TrainingRecommendations({ skills }: { skills: SkillGapEntry[] }) {
  const top = skills.slice(0, 5);
  if (top.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <GraduationCap className="h-4 w-4" /> Training priorities
        </CardTitle>
        <CardDescription>
          Suggested training order, from the same transparent priority score
          (demand 50% + demonstrated gap 40% + comparable growth 10%). These
          are the skills with the largest gap between what industry demands and
          what students have actually demonstrated.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="space-y-2">
          {top.map((skill, index) => (
            <li
              key={skill.skill_id}
              className="flex flex-wrap items-baseline justify-between gap-2 rounded-md border p-3"
            >
              <p className="text-sm">
                <span className="mr-2 font-semibold">{index + 1}.</span>
                <span className="font-medium">{skill.name}</span>
                <span className="text-muted-foreground">
                  {" "}
                  — {skill.demand_pct}% of postings require it, but only{" "}
                  {skill.demonstrated_pct}% of students have demonstrated it
                  {skill.students_reported > skill.students_demonstrated
                    ? ` (${skill.students_reported_only} report it without assessment evidence)`
                    : ""}
                  .
                </span>
              </p>
              <span className="text-xs text-muted-foreground">
                priority {skill.priority_score} ({skill.priority_class})
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-3 flex items-start gap-1 text-xs text-muted-foreground">
          <Info className="mt-0.5 h-3 w-3 shrink-0" />
          Priority is a transparent demo weighting, not an industry standard —
          the exact weights are documented in the API metadata. Growth
          contributes only when a comparable historical period exists.
        </p>
      </CardContent>
    </Card>
  );
}
