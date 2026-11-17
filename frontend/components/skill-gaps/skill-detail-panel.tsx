"use client";

import { Building2, Info, Layers, X } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { SkillGapEntry } from "@/types/skill-gaps";

/**
 * Detail view for ONE selected skill: industry demand (companies, job
 * families, year-wise series) and the student evidence breakdown. All
 * numbers come from the backend; the evidence classes are the documented
 * classifications, so the tooltip text states them verbatim.
 */
export function SkillDetailPanel({
  skill,
  onClose,
  thresholds,
}: {
  skill: SkillGapEntry;
  onClose: () => void;
  thresholds: { min_graded_answers: number; demonstrated_min_pct: number; developing_min_pct: number };
}) {
  const yearData = skill.years.map((year) => ({
    year: String(year.year),
    "Postings requiring the skill": year.posting_count,
    "Growth vs previous period": year.yoy_growth_pct,
  }));

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              {skill.name}
              {skill.category && (
                <Badge variant="outline" className="font-normal">
                  {skill.category}
                </Badge>
              )}
              <Badge
                variant={
                  skill.priority_class === "high"
                    ? "destructive"
                    : skill.priority_class === "medium"
                      ? "warning"
                      : "secondary"
                }
              >
                {skill.priority_class} priority
              </Badge>
            </CardTitle>
            <CardDescription>
              {skill.posting_count} posting{skill.posting_count === 1 ? "" : "s"} require
              this skill ({skill.demand_pct}% of the filtered postings).{" "}
              {skill.growth_comparable
                ? skill.latest_growth_pct != null
                  ? `Comparable-period demand growth: ${skill.latest_growth_pct > 0 ? "+" : ""}${skill.latest_growth_pct}%.`
                  : "No comparable previous-period demand to compare against."
                : "No comparable historical period for growth."}
            </CardDescription>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close skill detail">
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* --- Student evidence breakdown --- */}
        <div>
          <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
            <Layers className="h-4 w-4" /> Student evidence breakdown
          </h4>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <EvidenceTile
              label="Demonstrated"
              value={skill.students_demonstrated}
              hint={`Accuracy ≥ ${thresholds.demonstrated_min_pct}% on ≥ ${thresholds.min_graded_answers} graded questions across eligible drive assessments`}
            />
            <EvidenceTile
              label="Developing"
              value={skill.students_developing}
              hint={`Accuracy ≥ ${thresholds.developing_min_pct}% (below ${thresholds.demonstrated_min_pct}%) on ≥ ${thresholds.min_graded_answers} graded questions`}
            />
            <EvidenceTile
              label="Not demonstrated"
              value={skill.students_not_demonstrated}
              hint={`Accuracy below ${thresholds.developing_min_pct}% on ≥ ${thresholds.min_graded_answers} graded questions`}
            />
            <EvidenceTile
              label="Insufficient evidence"
              value={skill.students_insufficient_evidence}
              hint={`Some graded answers, but fewer than ${thresholds.min_graded_answers} — never classified`}
            />
            <EvidenceTile
              label="Self-reported"
              value={skill.students_reported}
              hint="Listed in the profile and/or active resume — NOT proof of proficiency"
            />
            <EvidenceTile
              label="Both evidence types"
              value={skill.students_both}
              hint="Self-reported AND classified assessment evidence"
            />
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {skill.students_no_evidence} student
            {skill.students_no_evidence === 1 ? "" : "s"} have no evidence for this
            skill at all (not reported, no graded assessment evidence).
          </p>
        </div>

        {/* --- Year-wise demand --- */}
        {yearData.length > 0 && (
          <div>
            <h4 className="mb-2 text-sm font-semibold">Year-wise demand</h4>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={yearData} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="year" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar
                  dataKey="Postings requiring the skill"
                  fill="#6366f1"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* --- Company + job family demand --- */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <CompanyDemandList
            title="Company demand"
            icon={<Building2 className="h-4 w-4" />}
            rows={skill.top_companies.map((company) => ({
              key: company.company_slug,
              label: company.company_name,
              count: company.posting_count,
              pct: company.demand_pct,
            }))}
            emptyText="No filtered company demands this skill."
          />
          <CompanyDemandList
            title="Job-family demand"
            icon={<Layers className="h-4 w-4" />}
            rows={skill.top_job_families.map((family) => ({
              key: family.job_family,
              label: family.job_family,
              count: family.posting_count,
              pct: family.demand_pct,
            }))}
            emptyText="No filtered job family demands this skill."
          />
        </div>
      </CardContent>
    </Card>
  );
}

function EvidenceTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <div
      className="rounded-md border bg-secondary/40 p-3"
      title={hint}
    >
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  );
}

function CompanyDemandList({
  title,
  icon,
  rows,
  emptyText,
}: {
  title: string;
  icon: React.ReactNode;
  rows: { key: string; label: string; count: number; pct: number }[];
  emptyText: string;
}) {
  return (
    <div>
      <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
        {icon} {title}
      </h4>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((row) => (
            <li
              key={row.key}
              className="flex items-center justify-between gap-2 rounded-md border px-3 py-1.5 text-sm"
            >
              <span className="truncate">{row.label}</span>
              <span className="shrink-0 text-muted-foreground">
                {row.count} posting{row.count === 1 ? "" : "s"} ({row.pct}%)
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1.5 flex items-start gap-1 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-3 w-3 shrink-0" />
        Percentages are the entity&apos;s own postings requiring the skill
        (top {rows.length > 0 ? rows.length : 0} shown).
      </p>
    </div>
  );
}
