"use client";

import { useEffect, useMemo, useState } from "react";
import { Building2 as BuildingIcon, Layers as LayersIcon, RotateCcw, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useMarketComparison } from "@/hooks/use-market-analytics";
import {
  buildComparisonMatrix,
  buildSharedSkills,
  buildUniqueSkills,
  formatSignedGrowth,
  isRareMarketWide,
} from "@/lib/market-insights";
import type {
  ComparisonDimension,
  ComparisonEntityAnalytics,
  TrendingSkill,
} from "@/types/market-analytics";

/** Backend cap: at most 6 entities per comparison request. */
const MAX_ENTITIES = 6;
/** Rows shown in the demand matrix before the "Show all" toggle. */
const MATRIX_PREVIEW_ROWS = 12;

/** Human-readable note of which dashboard posting filters the comparison reuses. */
function comparisonFilterNote(
  dimension: ComparisonDimension,
  filters: CompareFilters
): string {
  const notes: string[] = [];
  if (filters.year_from != null || filters.year_to != null) {
    notes.push(
      `year range ${filters.year_from ?? "…"}–${filters.year_to ?? "…"}`
    );
  }
  if (filters.location) notes.push(`location "${filters.location}"`);
  if (dimension === "company" && filters.job_family) {
    notes.push(`job family "${filters.job_family}"`);
  }
  if (dimension === "job_family" && filters.company) {
    notes.push("the dashboard's company filter");
  }
  const applied =
    notes.length > 0
      ? ` (${notes.join(", ")})`
      : " (no posting filters are set)";
  return `The comparison follows the dashboard's posting filters${applied}.`;
}

export interface CompareOption {
  key: string;
  label: string;
}

interface CompareFilters {
  year_from: number | null;
  year_to: number | null;
  company: string | null;
  job_family: string | null;
  location: string | null;
}

function EntitySummaryCard({
  entity,
  dimension,
}: {
  entity: ComparisonEntityAnalytics;
  dimension: ComparisonDimension;
}) {
  const mostDemanded: TrendingSkill | undefined = entity.skills[0];
  const strongestGrowth = entity.skills
    .filter((skill) => skill.yoy_growth_pct != null)
    .sort(
      (a, b) =>
        (b.yoy_growth_pct ?? 0) - (a.yoy_growth_pct ?? 0) || a.name.localeCompare(b.name)
    )[0];

  return (
    <div className="rounded-md border border-border p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium">{entity.entity_label}</p>
          {entity.industry && (
            <p className="truncate text-xs text-muted-foreground">{entity.industry}</p>
          )}
        </div>
        <Badge variant="outline">
          {entity.posting_count} posting{entity.posting_count === 1 ? "" : "s"} ·{" "}
          {entity.posting_share_pct}%
        </Badge>
      </div>

      <p
        className="text-xs text-muted-foreground"
        title="Share of the entity's skill-demand instances (posting × skill pairs) that are technical vs soft, computed by the backend."
      >
        Skill mix: {entity.tech_share_pct}% technical · {entity.soft_share_pct}% soft
        <span className="block">
          ({entity.tech_skill_instances} technical and {entity.soft_skill_instances} soft
          instances)
        </span>
      </p>

      <p className="mt-2 text-xs text-muted-foreground">
        Most demanded skill:{" "}
        {mostDemanded ? (
          <span className="font-medium text-foreground">
            {mostDemanded.name} ({mostDemanded.posting_count} · {mostDemanded.demand_pct}%)
          </span>
        ) : (
          "—"
        )}
      </p>
      <p className="text-xs text-muted-foreground">
        {dimension === "company" ? "Strongest company-level growth" : "Strongest family-level growth"}:{" "}
        {strongestGrowth && strongestGrowth.yoy_growth_pct != null ? (
          <span className="font-medium text-foreground">
            {strongestGrowth.name} ({formatSignedGrowth(strongestGrowth.yoy_growth_pct)})
          </span>
        ) : (
          <span title="No comparable previous period for this entity under the current filters.">
            N/A
          </span>
        )}
      </p>

      <p className="mt-3 text-xs text-muted-foreground">
        Year-wise postings:{" "}
        {Object.entries(entity.yearly_counts)
          .map(([year, count]) => `${year}: ${count}`)
          .join(" · ") || "none in the filtered years"}
      </p>
    </div>
  );
}

function DemandMatrixSection({
  entities,
  dimension,
}: {
  entities: ComparisonEntityAnalytics[];
  dimension: ComparisonDimension;
}) {
  const [showAll, setShowAll] = useState(false);
  const matrix = useMemo(() => buildComparisonMatrix(entities), [entities]);
  const visible = showAll ? matrix : matrix.slice(0, MATRIX_PREVIEW_ROWS);
  const entityLabel = dimension === "company" ? "company" : "family";

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold">Skill demand comparison</h4>
      <p className="text-xs text-muted-foreground">
        Percentages are each {entityLabel}&apos;s demand for the skill relative to its OWN
        postings (backend-computed), so columns are directly comparable. A dash means the{" "}
        {entityLabel} does not require the skill.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
          <caption className="sr-only">Skill demand across the selected {entityLabel}s</caption>
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th scope="col" className="py-2 pr-3 font-medium">Skill</th>
              {entities.map((entity) => (
                <th
                  key={entity.entity_key}
                  scope="col"
                  className="py-2 pr-3 text-right font-medium"
                >
                  {entity.entity_label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {visible.map((row) => (
              <tr key={row.slug}>
                <td className="py-2 pr-3 font-medium">{row.name}</td>
                {row.cells.map((cell, index) => (
                  <td
                    key={entities[index]?.entity_key ?? index}
                    className="py-2 pr-3 text-right tabular-nums"
                    title={
                      cell
                        ? undefined
                        : `Not required by ${entities[index]?.entity_label ?? "this " + entityLabel}`
                    }
                  >
                    {cell ? `${cell.demandPct}% (${cell.postingCount})` : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {matrix.length > MATRIX_PREVIEW_ROWS && (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={() => setShowAll((previous) => !previous)}
        >
          {showAll
            ? "Show top skills only"
            : `Show all ${matrix.length} skills`}
        </Button>
      )}
    </div>
  );
}

function SharedSkillsSection({
  entities,
  dimension,
}: {
  entities: ComparisonEntityAnalytics[];
  dimension: ComparisonDimension;
}) {
  const shared = useMemo(() => buildSharedSkills(entities), [entities]);
  const entityLabel = dimension === "company" ? "companies" : "job families";
  if (shared.length === 0) {
    return (
      <div className="space-y-2">
        <h4 className="text-sm font-semibold">Shared skills</h4>
        <p className="text-sm text-muted-foreground">
          No skill is required by more than one of the selected {entityLabel}.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold">Shared skills</h4>
      <p className="text-xs text-muted-foreground">
        Skills required by multiple selected {entityLabel}, with each one&apos;s demand
        percentage relative to its own postings.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
          <caption className="sr-only">Skills shared across the selected {entityLabel}</caption>
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th scope="col" className="py-2 pr-3 font-medium">Skill</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">Required by</th>
              <th scope="col" className="py-2 font-medium">Demand by {entityLabel}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {shared.map((skill) => (
              <tr key={skill.slug}>
                <td className="py-2 pr-3 font-medium">{skill.name}</td>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {skill.entityCount} of {entities.length}
                </td>
                <td className="py-2">
                  <div className="flex flex-wrap gap-1.5">
                    {skill.requiring.map((entry) => (
                      <Badge key={entry.key} variant="secondary" className="font-normal">
                        {entry.label}: {entry.demandPct}% ({entry.postingCount})
                      </Badge>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UniqueSkillsSection({
  entities,
  dimension,
  overallPostingCount,
  totalPostings,
}: {
  entities: ComparisonEntityAnalytics[];
  dimension: ComparisonDimension;
  overallPostingCount: Map<string, number>;
  totalPostings: number;
}) {
  const groups = useMemo(
    () => buildUniqueSkills(entities, overallPostingCount),
    [entities, overallPostingCount]
  );
  const entityLabel = dimension === "company" ? "company" : "family";
  if (groups.length === 0) {
    return (
      <div className="space-y-2">
        <h4 className="text-sm font-semibold">{dimension === "company" ? "Company" : "Family"}-specific skills</h4>
        <p className="text-sm text-muted-foreground">
          Every skill required by one selected {entityLabel} is also required by another
          selected {entityLabel}.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h4 className="text-sm font-semibold">
          {dimension === "company" ? "Company" : "Family"}-specific skills
        </h4>
        <p className="text-xs text-muted-foreground">
          Skills required by exactly one selected {entityLabel} but none of the others.
          Each chip also shows how rare the skill is in the overall filtered market, so a
          skill that is unique here but common elsewhere is not mistaken for a niche
          requirement.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {groups.map((group) => (
          <div key={group.entityKey} className="rounded-md border border-border p-3">
            <p className="mb-2 font-medium">{group.entityLabel}</p>
            <div className="flex flex-wrap gap-1.5">
              {group.skills.map((skill) => (
                <Badge
                  key={skill.slug}
                  variant="secondary"
                  className="font-normal"
                  title={
                    skill.overallPostingCount != null
                      ? `Required by ${skill.overallPostingCount} of ${totalPostings} filtered postings overall.`
                      : undefined
                  }
                >
                  {skill.name} · {skill.postingCount} ({skill.demandPct}%)
                  {isRareMarketWide(skill.overallPostingCount, totalPostings) && (
                    <span className="ml-1 text-muted-foreground">· rare market-wide</span>
                  )}
                </Badge>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Phase 5 entity-comparison panel: pick several companies (or job families),
 * then compare their FULL skill requirements — demand matrix, shared skills,
 * and skills unique to one entity — plus per-entity summaries (postings,
 * industry, technical/soft mix, year-wise counts, strongest growth).
 *
 * Selection is draft-based like the filter panel: "Apply" issues exactly one
 * comparison request; "Reset" clears the comparison. The comparison reuses
 * the dashboard's posting filters (year range, location, and the opposite
 * dimension's filter); skill-category filters never apply because the
 * comparison always shows the technical/soft split.
 */
export function EntityComparePanel({
  dimension,
  options,
  optionsLoading,
  optionsError,
  onRetryOptions,
  postingFilters,
  overallPostingCount,
  totalPostings,
}: {
  dimension: ComparisonDimension;
  options: CompareOption[];
  optionsLoading: boolean;
  optionsError: boolean;
  onRetryOptions: () => void;
  postingFilters: CompareFilters;
  overallPostingCount: Map<string, number>;
  totalPostings: number;
}) {
  const minSelection = dimension === "company" ? 2 : 1;
  const [appliedKeys, setAppliedKeys] = useState<string[]>([]);
  const [draftKeys, setDraftKeys] = useState<string[]>([]);

  useEffect(() => {
    setDraftKeys(appliedKeys);
  }, [appliedKeys]);

  const comparison = useMarketComparison(
    appliedKeys.length >= minSelection
      ? { dimension, entityKeys: appliedKeys, filters: postingFilters }
      : null
  );

  const labelFor = (key: string) =>
    options.find((option) => option.key === key)?.label ?? key;
  const addable = options.filter((option) => !draftKeys.includes(option.key));
  const entityLabel = dimension === "company" ? "company" : "job family";

  const data = comparison.data;
  const entities = data?.entities ?? [];
  const emptyEntities = entities.filter((entity) => entity.posting_count === 0);
  const allEmpty = entities.length > 0 && emptyEntities.length === entities.length;

  return (
    <div className="space-y-4">
      {/* --- Selection ------------------------------------------------------ */}
      {optionsError ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <span>Couldn&apos;t load {entityLabel} options.</span>
          <Button variant="outline" size="sm" onClick={onRetryOptions}>
            Retry
          </Button>
        </div>
      ) : optionsLoading ? (
        <Skeleton className="h-10 w-full" />
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-56">
              <Select
                value=""
                disabled={addable.length === 0 || draftKeys.length >= MAX_ENTITIES}
                onValueChange={(value) =>
                  setDraftKeys((previous) =>
                    previous.includes(value) ? previous : [...previous, value]
                  )
                }
              >
                <SelectTrigger aria-label={`Select a ${entityLabel} to compare`}>
                  <SelectValue
                    placeholder={
                      draftKeys.length >= MAX_ENTITIES
                        ? `Maximum ${MAX_ENTITIES} selected`
                        : `Add a ${entityLabel}…`
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {addable.map((option) => (
                    <SelectItem key={option.key} value={option.key}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              onClick={() => setAppliedKeys(draftKeys)}
              disabled={draftKeys.length < minSelection}
            >
              {dimension === "company"
                ? "Compare"
                : appliedKeys.length === 0
                  ? "Inspect"
                  : "Update"}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setDraftKeys([]);
                setAppliedKeys([]);
              }}
              disabled={draftKeys.length === 0 && appliedKeys.length === 0}
            >
              <RotateCcw className="mr-2 h-4 w-4" /> Reset comparison
            </Button>
          </div>
          {draftKeys.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {draftKeys.map((key) => (
                <Badge key={key} variant="secondary" className="gap-1 font-normal">
                  {labelFor(key)}
                  <button
                    type="button"
                    aria-label={`Remove ${labelFor(key)} from the comparison`}
                    className="ml-0.5 rounded-full p-0.5 hover:bg-background/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => setDraftKeys((previous) => previous.filter((k) => k !== key))}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              {dimension === "company"
                ? `Select at least ${minSelection} companies (up to ${MAX_ENTITIES}) to compare their skill requirements.`
                : "Select one job family to inspect its skills, or several (up to 6) to compare them."}
            </p>
          )}
          {draftKeys.length > 0 && draftKeys.length < minSelection && (
            <p className="text-xs text-muted-foreground">
              Select at least {minSelection} {dimension === "company" ? "companies" : "job families"} to{" "}
              {dimension === "company" ? "compare" : "proceed"}.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            {comparisonFilterNote(dimension, postingFilters)} Skill-category filters don&apos;t
            apply to comparisons so the technical/soft split stays visible.
          </p>
        </div>
      )}

      {/* --- Results -------------------------------------------------------- */}
      {appliedKeys.length >= minSelection &&
        (comparison.isError && !comparison.data ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
            <span>Couldn&apos;t load the comparison.</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => comparison.refetch()}
              disabled={comparison.isRefetching}
            >
              {comparison.isRefetching ? "Retrying…" : "Retry"}
            </Button>
          </div>
        ) : comparison.isLoading || !data ? (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
            <Skeleton className="h-64 w-full" />
          </div>
        ) : allEmpty ? (
          <EmptyState
            icon={dimension === "company" ? BuildingIcon : LayersIcon}
            title="No postings match the current filters for the selected entities"
            description="The compared entities exist in the dataset, but none of their postings fall inside the current filter combination. Reset the dashboard filters or widen the year range."
          />
        ) : (
          <div className="space-y-6">
            {comparison.isFetching && (
              <p className="text-xs text-muted-foreground" role="status">
                Updating comparison…
              </p>
            )}
            {emptyEntities.length > 0 && (
              <p className="text-xs text-muted-foreground" role="status">
                No postings match the current filters for{" "}
                {emptyEntities.map((entity) => entity.entity_label).join(", ")} — their
                columns are empty.
              </p>
            )}

            <div
              className={
                entities.length === 1
                  ? "grid gap-3"
                  : "grid gap-3 md:grid-cols-2 xl:grid-cols-3"
              }
            >
              {entities.map((entity) => (
                <EntitySummaryCard key={entity.entity_key} entity={entity} dimension={dimension} />
              ))}
            </div>

            {entities.length >= 2 && (
              <>
                <DemandMatrixSection entities={entities} dimension={dimension} />
                <SharedSkillsSection entities={entities} dimension={dimension} />
                <UniqueSkillsSection
                  entities={entities}
                  dimension={dimension}
                  overallPostingCount={overallPostingCount}
                  totalPostings={totalPostings}
                />
              </>
            )}
          </div>
        ))}
    </div>
  );
}
