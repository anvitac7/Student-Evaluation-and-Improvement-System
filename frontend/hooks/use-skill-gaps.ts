import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type {
  SkillGapAnalysisResponse,
  SkillGapParams,
  SkillGapSort,
  SkillGapStudentFilter,
  SkillGapStudentsResponse,
} from "@/types/skill-gaps";
import type { MarketFiltersResponse } from "@/types/market-analytics";

/**
 * React Query hooks for the TPO Skill Gap Analysis dashboard (Phase 8).
 *
 * Fetch-only: every demand count, evidence classification, gap percentage and
 * priority score is computed by the backend and consumed as-is. The active
 * filter state is part of the query key so changing filters issues a new
 * query while `keepPreviousData` keeps the previous results visible.
 */

export interface SkillGapFiltersState {
  /** Posting-population filters — these change what demand is counted on. */
  year_from: number | null;
  year_to: number | null;
  company: string | null;
  job_family: string | null;
  location: string | null;
  /** Skill-scope filters — these only narrow which skills are analysed. */
  skill_category: string | null;
  technical_only: boolean;
  /** Presentation option. */
  sort: SkillGapSort;
}

export const DEFAULT_SKILL_GAP_FILTERS: SkillGapFiltersState = {
  year_from: null,
  year_to: null,
  company: null,
  job_family: null,
  location: null,
  skill_category: null,
  technical_only: false,
  sort: "priority",
};

function buildQueryParams(filters: SkillGapFiltersState): SkillGapParams {
  const params: SkillGapParams = { sort: filters.sort };
  if (filters.year_from != null) params.year_from = filters.year_from;
  if (filters.year_to != null) params.year_to = filters.year_to;
  if (filters.company) params.company = filters.company;
  if (filters.job_family) params.job_family = filters.job_family;
  if (filters.location) params.location = filters.location;
  if (filters.skill_category) params.skill_category = filters.skill_category;
  if (filters.technical_only) params.technical_only = true;
  return params;
}

export function useSkillGaps(filters: SkillGapFiltersState) {
  const params = buildQueryParams(filters);
  return useQuery({
    queryKey: ["skill-gaps", params] as const,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data } = await apiClient.get<SkillGapAnalysisResponse>(
        "/analytics/tpo/skill-gaps",
        { params }
      );
      return data;
    },
  });
}

/** Same live filter options the Market Insights dashboard derives. */
export function useSkillGapFilterOptions() {
  return useQuery({
    queryKey: ["skill-gaps", "filters"] as const,
    staleTime: 5 * 60 * 1000,
    queryFn: async () => {
      const { data } = await apiClient.get<MarketFiltersResponse>(
        "/analytics/tpo/skill-gaps/filters"
      );
      return data;
    },
  });
}

export function useSkillGapStudents(
  skillId: string | null,
  page: number,
  classification: SkillGapStudentFilter,
  search: string
) {
  const trimmed = search.trim();
  return useQuery({
    queryKey: [
      "skill-gaps",
      "students",
      skillId,
      page,
      classification,
      trimmed,
    ] as const,
    enabled: Boolean(skillId),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data } = await apiClient.get<SkillGapStudentsResponse>(
        `/analytics/tpo/skill-gaps/${skillId}/students`,
        {
          params: {
            page,
            limit: 10,
            classification,
            ...(trimmed ? { search: trimmed } : {}),
          },
        }
      );
      return data;
    },
  });
}
