import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type {
  MarketAnalyticsParams,
  MarketAnalyticsResponse,
  MarketComparisonParams,
  MarketComparisonResponse,
  MarketFiltersResponse,
  MarketSort,
} from "@/types/market-analytics";

/**
 * React Query hooks for the TPO Market Insights dashboard.
 *
 * These only fetch — every aggregate, percentage and trend classification is
 * computed by the backend (Phase 3 / Phase 5) and consumed as-is. The active
 * filter state is part of the analytics query key, so changing filters issues
 * a new query while `placeholderData: keepPreviousData` keeps the previous
 * results visible until the fresh ones arrive (no page reload, no flashing).
 */

export interface MarketFiltersState {
  /** Posting-population filters — these change what is counted. */
  year_from: number | null;
  year_to: number | null;
  company: string | null;
  job_family: string | null;
  location: string | null;
  /** Skill-scope filters — these only narrow which skills are analysed. */
  skill_category: string | null;
  technical_only: boolean;
  /** Presentation options. */
  sort: MarketSort;
  limit: number;
}

export const DEFAULT_MARKET_FILTERS: MarketFiltersState = {
  year_from: null,
  year_to: null,
  company: null,
  job_family: null,
  location: null,
  skill_category: null,
  technical_only: false,
  sort: "trending",
  limit: 10,
};

const MARKET_ANALYTICS_KEY = (params: MarketAnalyticsParams) =>
  ["market", "analytics", params] as const;
const MARKET_FILTERS_KEY = ["market", "filters"] as const;
const MARKET_COMPARISON_KEY = (params: MarketComparisonParams) =>
  ["market", "comparison", params] as const;

/** Only send set values; never serialise nulls or empty strings. */
function buildQueryParams(filters: MarketFiltersState): MarketAnalyticsParams {
  const params: MarketAnalyticsParams = {
    sort: filters.sort,
    limit: filters.limit,
  };
  if (filters.year_from != null) params.year_from = filters.year_from;
  if (filters.year_to != null) params.year_to = filters.year_to;
  if (filters.company) params.company = filters.company;
  if (filters.job_family) params.job_family = filters.job_family;
  if (filters.location) params.location = filters.location;
  if (filters.skill_category) params.skill_category = filters.skill_category;
  if (filters.technical_only) params.technical_only = true;
  return params;
}

/** Input for the Phase 5 comparison endpoint. */
export interface MarketComparisonRequest {
  dimension: "company" | "job_family";
  /** Company slugs, or job-family names, in the user's chosen order. */
  entityKeys: string[];
  /**
   * Dashboard posting filters. The comparison reuses the year range,
   * location and the OPPOSITE dimension's filter (job-family filter for
   * company comparisons, company filter for family comparisons); the
   * dimension's own filter is replaced by the selection.
   */
  filters: Pick<
    MarketFiltersState,
    "year_from" | "year_to" | "company" | "job_family" | "location"
  >;
}

function buildComparisonParams(
  request: MarketComparisonRequest
): MarketComparisonParams | null {
  const entityKeys = request.entityKeys.filter((key) => key.length > 0);
  if (entityKeys.length === 0) return null;
  const params: MarketComparisonParams = {
    dimension: request.dimension,
    entities: entityKeys.join(","),
  };
  if (request.filters.year_from != null) params.year_from = request.filters.year_from;
  if (request.filters.year_to != null) params.year_to = request.filters.year_to;
  if (request.filters.location) params.location = request.filters.location;
  if (request.dimension === "company" && request.filters.job_family) {
    params.job_family = request.filters.job_family;
  }
  if (request.dimension === "job_family" && request.filters.company) {
    params.company = request.filters.company;
  }
  return params;
}

export function useMarketAnalytics(filters: MarketFiltersState) {
  const params = buildQueryParams(filters);
  return useQuery({
    queryKey: MARKET_ANALYTICS_KEY(params),
    queryFn: async () => {
      const { data } = await apiClient.get<MarketAnalyticsResponse>(
        "/analytics/tpo/market",
        { params }
      );
      return data;
    },
    placeholderData: keepPreviousData,
    // The demo dataset is static between seed refreshes; an hour avoids
    // hammering the analytics aggregation on every dashboard revisit while
    // still picking up a reseed within a reasonable window.
    staleTime: 60 * 60_000,
  });
}

export function useMarketFilters() {
  return useQuery({
    queryKey: MARKET_FILTERS_KEY,
    queryFn: async () => {
      const { data } = await apiClient.get<MarketFiltersResponse>(
        "/analytics/tpo/market/filters"
      );
      return data;
    },
    // Filter options only change when the dataset itself is reseeded.
    staleTime: 60 * 60_000,
  });
}

/**
 * Phase 5 entity comparison. Disabled (no request) until the selection
 * reaches the caller's minimum; `entityKeys` is part of the query key, so
 * adding or removing an entity issues exactly one new request.
 */
export function useMarketComparison(request: MarketComparisonRequest | null) {
  const params = request ? buildComparisonParams(request) : null;
  return useQuery({
    queryKey: params
      ? MARKET_COMPARISON_KEY(params)
      : (["market", "comparison", null] as const),
    queryFn: async () => {
      const { data } = await apiClient.get<MarketComparisonResponse>(
        "/analytics/tpo/market/comparison",
        { params }
      );
      return data;
    },
    enabled: params != null,
    placeholderData: keepPreviousData,
    staleTime: 60 * 60_000,
  });
}
