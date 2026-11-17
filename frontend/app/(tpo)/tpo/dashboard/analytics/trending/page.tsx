"use client";

import { useState } from "react";
import { AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ComparisonSection } from "@/components/market/comparison-section";
import { CompanyAnalyticsSection } from "@/components/market/company-analytics-section";
import { EmergingSkillsSection } from "@/components/market/emerging-skills-section";
import { HistoricalTrendsSection } from "@/components/market/historical-trends-section";
import { JobFamilySection } from "@/components/market/job-family-section";
import { MarketFilterPanel } from "@/components/market/market-filter-panel";
import { MarketSummaryCards } from "@/components/market/market-summary-cards";
import { TrendingSkillsSection } from "@/components/market/trending-skills-section";
import {
  DEFAULT_MARKET_FILTERS,
  useMarketAnalytics,
  useMarketFilters,
  type MarketFiltersState,
} from "@/hooks/use-market-analytics";

/**
 * TPO Market Insights — Trending Skills & Company Requirements.
 *
 * Consumes the Phase 3 aggregate APIs (`/analytics/tpo/market`, its
 * `/filters` endpoint) and the Phase 5 comparison API
 * (`/analytics/tpo/market/comparison`). Every number, percentage and trend
 * classification is backend-computed; frontend-derived observations are
 * built by the documented formulas in `lib/market-insights.ts`. The response
 * metadata (partial-year comparison window) is surfaced so partial-year
 * figures are never mistaken for full-year verified hiring statistics.
 */
export default function MarketInsightsPage() {
  const [filters, setFilters] = useState<MarketFiltersState>({ ...DEFAULT_MARKET_FILTERS });

  const analytics = useMarketAnalytics(filters);
  const filterOptions = useMarketFilters();

  const data = analytics.data;
  const meta = data?.meta;
  const isEmpty = data != null && data.summary.total_postings === 0;

  return (
    <div className="space-y-6">
      {/* --- Header --------------------------------------------------------- */}
      <div className="space-y-1.5">
        <h1 className="font-display text-2xl font-semibold">Market Insights</h1>
        <p className="text-sm text-muted-foreground">
          A market-wide view of trending skills and company requirements.
        </p>
        {meta?.current_period && (
          <p className="text-xs text-muted-foreground">
            {meta.comparison_comparable && meta.previous_period
              ? `${meta.current_period.label} compared with ${meta.previous_period.label}.`
              : `${meta.current_period.label} — no comparable previous period, so growth values are unavailable.`}
          </p>
        )}
      </div>

      {/* --- Filters (always interactive, even while data loads) ------------- */}
      <MarketFilterPanel
        active={filters}
        onApply={setFilters}
        options={filterOptions.data}
        optionsLoading={filterOptions.isLoading}
        optionsError={filterOptions.isError}
        onRetryOptions={() => filterOptions.refetch()}
      />

      {/* --- Data ------------------------------------------------------------ */}
      {analytics.isError && !analytics.data ? (
        <EmptyState
          icon={AlertCircle}
          title="Couldn't load market insights"
          description="Something went wrong while fetching the market analytics. Check your connection and try again."
          action={
            <Button
              variant="outline"
              onClick={() => analytics.refetch()}
              disabled={analytics.isRefetching}
            >
              {analytics.isRefetching ? "Retrying…" : "Retry"}
            </Button>
          }
        />
      ) : analytics.isLoading ? (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-24 w-full rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-80 w-full" />
          <Skeleton className="h-80 w-full" />
        </div>
      ) : isEmpty ? (
        <EmptyState
          icon={AlertCircle}
          title="No postings match the selected filters"
          description="Nothing in the market dataset matches the current filter combination. Reset the filters or widen the year range."
          action={
            <Button variant="outline" onClick={() => setFilters({ ...DEFAULT_MARKET_FILTERS })}>
              Reset filters
            </Button>
          }
        />
      ) : (
        data && (
          <div className="space-y-6">
            {/* While a refetch is in flight the previous results stay visible
                (placeholderData), so only this small status line changes. */}
            {analytics.isFetching && (
              <p className="text-xs text-muted-foreground" role="status">
                Updating…
              </p>
            )}

            <MarketSummaryCards summary={data.summary} isLoading={false} />

            <TrendingSkillsSection
              skills={data.trending_skills}
              historical={data.historical_trends}
              families={data.job_families}
              companies={data.companies}
              meta={meta}
              isLoading={false}
            />

            <HistoricalTrendsSection
              trends={data.historical_trends}
              meta={meta}
              isLoading={false}
            />

            <EmergingSkillsSection
              emerging={data.emerging_skills}
              trending={data.trending_skills}
              historical={data.historical_trends}
              meta={meta}
              isLoading={false}
            />

            <CompanyAnalyticsSection companies={data.companies} isLoading={false} />

            <JobFamilySection families={data.job_families} isLoading={false} />

            <ComparisonSection
              data={data}
              filters={filters}
              filterOptions={filterOptions.data}
              optionsLoading={filterOptions.isLoading}
              optionsError={filterOptions.isError}
              onRetryOptions={() => filterOptions.refetch()}
            />
          </div>
        )
      )}
    </div>
  );
}
