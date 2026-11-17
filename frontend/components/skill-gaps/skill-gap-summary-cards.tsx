"use client";

import { GraduationCap, MessageSquareWarning, Target, TrendingUp, Users } from "lucide-react";

import { StatCard } from "@/components/shared/stat-card";
import type { SkillGapSummary } from "@/types/skill-gaps";

/**
 * The five summary cards. Every value is backend-computed; the labels state
 * exactly what each number means (documented definitions, not marketing).
 */
export function SkillGapSummaryCards({ summary }: { summary: SkillGapSummary }) {
  const missing = summary.most_demanded_missing_skill;
  const topRising = summary.rising_demand_skills[0];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      <StatCard
        label="Skills analyzed"
        value={summary.total_skills_analyzed}
        icon={Target}
      />
      <StatCard
        label="High-priority skill gaps"
        value={summary.high_priority_gaps}
        icon={MessageSquareWarning}
      />
      <StatCard
        label="Students without demonstrated skills"
        value={`${summary.students_lacking_demonstrated_skills} / ${summary.student_population}`}
        icon={GraduationCap}
      />
      <StatCard
        label="Most demanded missing skill"
        value={
          missing
            ? `${missing.name} (${missing.demand_pct}% demand)`
            : "Every demanded skill has demonstrated students"
        }
        icon={Users}
      />
      <StatCard
        label="Fastest-rising demand"
        value={
          topRising
            ? `${topRising.name} (+${topRising.latest_growth_pct}%)`
            : "No comparable growth data"
        }
        icon={TrendingUp}
      />
    </div>
  );
}
