"use client";

import { useEffect, useState } from "react";
import { Filter, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { DEFAULT_MARKET_FILTERS, type MarketFiltersState } from "@/hooks/use-market-analytics";
import type { MarketFiltersResponse } from "@/types/market-analytics";

const ALL = "all";
const LIMIT_CHOICES = [10, 15, 20];

/**
 * Draft-based filter panel: selections update local draft state and only the
 * "Apply filters" action issues a new query, so adjusting several filters in
 * a row does not fire a request per change. "Reset filters" restores the
 * defaults and applies immediately.
 */
export function MarketFilterPanel({
  active,
  onApply,
  options,
  optionsLoading,
  optionsError,
  onRetryOptions,
}: {
  active: MarketFiltersState;
  onApply: (filters: MarketFiltersState) => void;
  options: MarketFiltersResponse | undefined;
  optionsLoading: boolean;
  optionsError: boolean;
  onRetryOptions: () => void;
}) {
  const [draft, setDraft] = useState<MarketFiltersState>(active);

  // Keep the draft in sync when the applied filters change (e.g. Reset).
  useEffect(() => {
    setDraft(active);
  }, [active]);

  const invalidYearRange =
    draft.year_from != null && draft.year_to != null && draft.year_from > draft.year_to;

  const update = (patch: Partial<MarketFiltersState>) =>
    setDraft((previous) => ({ ...previous, ...patch }));

  const yearValue = (year: number | null) => (year != null ? String(year) : ALL);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Filter className="h-4 w-4" /> Filters
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {optionsError ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
            <span>Couldn&apos;t load filter options.</span>
            <Button variant="outline" size="sm" onClick={onRetryOptions}>
              Retry
            </Button>
          </div>
        ) : optionsLoading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 9 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {/* --- Posting-population filters ----------------------------- */}
            <div className="space-y-1.5">
              <Label htmlFor="year-from">From year</Label>
              <Select
                value={yearValue(draft.year_from)}
                onValueChange={(value) =>
                  update({ year_from: value === ALL ? null : Number(value) })
                }
              >
                <SelectTrigger id="year-from">
                  <SelectValue placeholder="All years" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All years</SelectItem>
                  {(options?.years ?? []).map((year) => (
                    <SelectItem key={year} value={String(year)}>
                      {year}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="year-to">To year</Label>
              <Select
                value={yearValue(draft.year_to)}
                onValueChange={(value) => update({ year_to: value === ALL ? null : Number(value) })}
              >
                <SelectTrigger id="year-to">
                  <SelectValue placeholder="All years" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All years</SelectItem>
                  {(options?.years ?? []).map((year) => (
                    <SelectItem key={year} value={String(year)}>
                      {year}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="company">Company</Label>
              <Select
                value={draft.company ?? ALL}
                onValueChange={(value) => update({ company: value === ALL ? null : value })}
              >
                <SelectTrigger id="company">
                  <SelectValue placeholder="All companies" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All companies</SelectItem>
                  {(options?.companies ?? []).map((company) => (
                    <SelectItem key={company.slug} value={company.slug}>
                      {company.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="job-family">Job family</Label>
              <Select
                value={draft.job_family ?? ALL}
                onValueChange={(value) => update({ job_family: value === ALL ? null : value })}
              >
                <SelectTrigger id="job-family">
                  <SelectValue placeholder="All job families" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All job families</SelectItem>
                  {(options?.job_families ?? []).map((family) => (
                    <SelectItem key={family} value={family}>
                      {family}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="location">Location</Label>
              <Select
                value={draft.location ?? ALL}
                onValueChange={(value) => update({ location: value === ALL ? null : value })}
              >
                <SelectTrigger id="location">
                  <SelectValue placeholder="All locations" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All locations</SelectItem>
                  {(options?.locations ?? []).map((location) => (
                    <SelectItem key={location} value={location}>
                      {location}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* --- Skill-scope filters ----------------------------------- */}
            <div className="space-y-1.5">
              <Label htmlFor="skill-category">Skill category</Label>
              <Select
                value={draft.skill_category ?? ALL}
                onValueChange={(value) =>
                  update({ skill_category: value === ALL ? null : value })
                }
              >
                <SelectTrigger id="skill-category">
                  <SelectValue placeholder="All categories" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All categories</SelectItem>
                  {(options?.skill_categories ?? []).map((category) => (
                    <SelectItem key={category} value={category}>
                      {category}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="technical-only">Skill type</Label>
              <Select
                value={draft.technical_only ? "technical" : ALL}
                onValueChange={(value) => update({ technical_only: value === "technical" })}
              >
                <SelectTrigger id="technical-only">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All skills</SelectItem>
                  <SelectItem value="technical">Technical skills only</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* --- Presentation options ---------------------------------- */}
            <div className="space-y-1.5">
              <Label htmlFor="sort-by">Sort by</Label>
              <Select
                value={draft.sort}
                onValueChange={(value) => update({ sort: value as MarketFiltersState["sort"] })}
              >
                <SelectTrigger id="sort-by">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="trending">Trending</SelectItem>
                  <SelectItem value="demand">Most demanded</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="skill-limit">Skill limit</Label>
              <Select
                value={String(draft.limit)}
                onValueChange={(value) => update({ limit: Number(value) })}
              >
                <SelectTrigger id="skill-limit">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LIMIT_CHOICES.map((choice) => (
                    <SelectItem key={choice} value={String(choice)}>
                      {choice}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}

        {invalidYearRange && (
          <p className="text-sm text-destructive">From year must be on or before To year.</p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() => onApply(draft)}
            disabled={invalidYearRange || optionsLoading || optionsError}
          >
            Apply filters
          </Button>
          <Button
            variant="outline"
            onClick={() => onApply({ ...DEFAULT_MARKET_FILTERS })}
            disabled={optionsLoading}
          >
            <RotateCcw className="mr-2 h-4 w-4" /> Reset filters
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
