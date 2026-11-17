"use client";

import { useMemo } from "react";
import { Building2, Layers } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EntityComparePanel, type CompareOption } from "@/components/market/entity-compare-panel";
import type { MarketFiltersState } from "@/hooks/use-market-analytics";
import type {
  CompanyFilterOption,
  HistoricalSkillTrend,
  MarketAnalyticsResponse,
  MarketFiltersResponse,
} from "@/types/market-analytics";

/**
 * Phase 5 advanced company/family comparisons, kept in ONE dedicated
 * section at the bottom of the dashboard so the main analytics stay
 * uncluttered. Both tabs reuse the same comparison panel and the same
 * backend endpoint; the company tab requires at least two selections, the
 * family tab allows single-family inspection.
 */
export function ComparisonSection({
  data,
  filters,
  filterOptions,
  optionsLoading,
  optionsError,
  onRetryOptions,
}: {
  data: MarketAnalyticsResponse;
  filters: MarketFiltersState;
  filterOptions: MarketFiltersResponse | undefined;
  optionsLoading: boolean;
  optionsError: boolean;
  onRetryOptions: () => void;
}) {
  // Overall (filtered-market) posting counts per skill, summed from the
  // backend's historical yearly counts — used to flag group-unique skills
  // that are also rare market-wide.
  const overallPostingCount = useMemo(() => {
    const map = new Map<string, number>();
    for (const trend of data.historical_trends as HistoricalSkillTrend[]) {
      map.set(
        trend.slug,
        trend.years.reduce((sum, year) => sum + year.posting_count, 0)
      );
    }
    return map;
  }, [data.historical_trends]);

  const companyOptions = useMemo<CompareOption[]>(
    () =>
      (filterOptions?.companies ?? []).map((company: CompanyFilterOption) => ({
        key: company.slug,
        label: company.name,
      })),
    [filterOptions]
  );
  const familyOptions = useMemo<CompareOption[]>(
    () => (filterOptions?.job_families ?? []).map((family) => ({ key: family, label: family })),
    [filterOptions]
  );

  const postingFilters = {
    year_from: filters.year_from,
    year_to: filters.year_to,
    company: filters.company,
    job_family: filters.job_family,
    location: filters.location,
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Skill requirement comparison</CardTitle>
        <CardDescription>
          Compare what selected companies or job families ask for — shared skills,
          requirements unique to one of them, and their demand for each skill.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="companies">
          <TabsList>
            <TabsTrigger value="companies">
              <Building2 className="mr-1.5 h-4 w-4" /> Companies
            </TabsTrigger>
            <TabsTrigger value="job-families">
              <Layers className="mr-1.5 h-4 w-4" /> Job families
            </TabsTrigger>
          </TabsList>
          <TabsContent value="companies">
            <EntityComparePanel
              dimension="company"
              options={companyOptions}
              optionsLoading={optionsLoading}
              optionsError={optionsError}
              onRetryOptions={onRetryOptions}
              postingFilters={postingFilters}
              overallPostingCount={overallPostingCount}
              totalPostings={data.summary.total_postings}
            />
          </TabsContent>
          <TabsContent value="job-families">
            <EntityComparePanel
              dimension="job_family"
              options={familyOptions}
              optionsLoading={optionsLoading}
              optionsError={optionsError}
              onRetryOptions={onRetryOptions}
              postingFilters={postingFilters}
              overallPostingCount={overallPostingCount}
              totalPostings={data.summary.total_postings}
            />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
