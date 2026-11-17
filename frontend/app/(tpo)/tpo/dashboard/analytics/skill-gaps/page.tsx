"use client";

import { useMemo, useState } from "react";
import { AlertCircle, Puzzle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import {
  DEFAULT_SKILL_GAP_FILTERS,
  useSkillGaps,
  useSkillGapFilterOptions,
  type SkillGapFiltersState,
} from "@/hooks/use-skill-gaps";
import { DemandProficiencyChart } from "@/components/skill-gaps/demand-proficiency-chart";
import { PriorityGapsTable } from "@/components/skill-gaps/priority-gaps-table";
import { SkillDetailPanel } from "@/components/skill-gaps/skill-detail-panel";
import {
  SkillGapFilterPanel,
} from "@/components/skill-gaps/skill-gap-filter-panel";
import { SkillGapSummaryCards } from "@/components/skill-gaps/skill-gap-summary-cards";
import { SkillStudentsPanel } from "@/components/skill-gaps/skill-students-panel";
import { TrainingRecommendations } from "@/components/skill-gaps/training-recommendations";
import type { SkillGapEntry } from "@/types/skill-gaps";

/**
 * TPO Skill Gap Analysis (Phase 8): industry demand from the Market Insights
 * dataset vs two separate student evidence types (assessment-demonstrated
 * and self-reported), with a transparent priority score. All values are
 * backend-computed; this page only fetches, filters and presents.
 */
export default function SkillGapAnalysisPage() {
  const [filters, setFilters] = useState<SkillGapFiltersState>({
    ...DEFAULT_SKILL_GAP_FILTERS,
  });
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(null);

  const {
    data: options,
    isLoading: optionsLoading,
    isError: optionsError,
    refetch: refetchOptions,
  } = useSkillGapFilterOptions();

  const { data, isLoading, isError, refetch, isRefetching } = useSkillGaps(filters);

  const selectedSkill: SkillGapEntry | null = useMemo(() => {
    if (!data || !selectedSkillId) return null;
    return data.skills.find((skill) => skill.skill_id === selectedSkillId) ?? null;
  }, [data, selectedSkillId]);

  const evidenceCoverage = data
    ? `${data.summary.students_with_assessment_evidence} of ${data.summary.student_population} students have graded evidence on the analyzed skills; ${data.summary.students_with_reported_skills} report skills via profile/resume.`
    : null;

  if (isLoading && !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-24 w-full" />
          ))}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <EmptyState
        icon={AlertCircle}
        title="Couldn't load skill gap analysis"
        description="Something went wrong while fetching the analysis. Check your connection and try again."
        action={
          <Button variant="outline" onClick={() => refetch()} disabled={isRefetching}>
            {isRefetching ? "Retrying…" : "Retry"}
          </Button>
        }
      />
    );
  }

  if (data.skills.length === 0) {
    return (
      <div className="space-y-4">
        <PageIntro meta={data.meta.notes[0]} />
        <SkillGapFilterPanel
          active={filters}
          onApply={setFilters}
          options={options}
          optionsLoading={optionsLoading}
          optionsError={optionsError}
          onRetryOptions={() => refetchOptions()}
        />
        <EmptyState
          icon={Puzzle}
          title="No skills match the current filters"
          description="Try widening the year range or clearing the company / job-family / category filters."
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Skill Gap Analysis</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Industry demand vs what students can actually demonstrate. Assessment
          evidence uses SUBMITTED attempts on placement drives&apos; required
          assessments only (practice assessments never count); self-reported
          skills from profiles and resumes are shown separately and never
          treated as proficiency.
        </p>
      </div>

      <SkillGapSummaryCards summary={data.summary} />

      {evidenceCoverage && (
        <p className="text-xs text-muted-foreground">{evidenceCoverage} Classification thresholds: demonstrated ≥ {data.meta.thresholds.demonstrated_min_pct}%, developing ≥ {data.meta.thresholds.developing_min_pct}%, with at least {data.meta.thresholds.min_graded_answers} graded answers (below that, evidence is insufficient).</p>
      )}

      <SkillGapFilterPanel
        active={filters}
        onApply={setFilters}
        options={options}
        optionsLoading={optionsLoading}
        optionsError={optionsError}
        onRetryOptions={() => refetchOptions()}
      />

      <DemandProficiencyChart skills={data.skills} />

      <PriorityGapsTable
        skills={data.skills}
        sort={filters.sort}
        onSortChange={(sort) => setFilters((previous) => ({ ...previous, sort }))}
        selectedSkillId={selectedSkillId}
        onSelectSkill={(skillId) =>
          setSelectedSkillId((current) => (current === skillId ? null : skillId))
        }
      />

      {selectedSkill && (
        <>
          <SkillDetailPanel
            skill={selectedSkill}
            onClose={() => setSelectedSkillId(null)}
            thresholds={data.meta.thresholds}
          />
          <SkillStudentsPanel skill={selectedSkill} />
        </>
      )}

      <TrainingRecommendations skills={data.skills} />

      {data.meta.unmapped_assessment_skill_tags.length > 0 && (
        <UnmappedCard
          title="Unmapped assessment skill tags"
          items={data.meta.unmapped_assessment_skill_tags}
          description="Question skill tags with no entry in the market skill catalog — their evidence is excluded from the gap rows (reported here rather than silently dropped)."
        />
      )}
      {data.meta.unmapped_self_reported_skills.length > 0 && (
        <UnmappedCard
          title="Unmapped self-reported skills"
          items={data.meta.unmapped_self_reported_skills}
          description="Profile/resume skills that do not match any catalog or demanded skill — they cannot be compared against industry demand."
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Dataset &amp; methodology notes</CardTitle>
          <CardDescription>
            {data.meta.market.is_mock_data ? data.meta.market.disclaimer : null}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {data.meta.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function PageIntro({ meta }: { meta?: string }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold">Skill Gap Analysis</h1>
      {meta && <p className="mt-1 text-sm text-muted-foreground">{meta}</p>}
    </div>
  );
}

function UnmappedCard({
  title,
  items,
  description,
}: {
  title: string;
  items: string[];
  description: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <span
              key={item}
              className="rounded-md border bg-secondary/50 px-2 py-1 text-xs"
            >
              {item}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
