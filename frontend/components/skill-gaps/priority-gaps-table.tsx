"use client";

import { ArrowUp, ArrowUpDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { PriorityClass, SkillGapEntry, SkillGapSort } from "@/types/skill-gaps";

const PRIORITY_VARIANT: Record<PriorityClass, "destructive" | "warning" | "secondary"> = {
  high: "destructive",
  medium: "warning",
  low: "secondary",
};

const SORTABLE_COLUMNS: { key: SkillGapSort; label: string }[] = [
  { key: "demand", label: "Demand %" },
  { key: "gap", label: "Gap %" },
  { key: "priority", label: "Priority" },
];

/**
 * The ranked gap table. Sorting is applied by the BACKEND (the `sort`
 * parameter) so the order is deterministic; clicking a column re-queries
 * with that sort. Clicking a row opens that skill's detail + student views.
 */
export function PriorityGapsTable({
  skills,
  sort,
  onSortChange,
  selectedSkillId,
  onSelectSkill,
}: {
  skills: SkillGapEntry[];
  sort: SkillGapSort;
  onSortChange: (sort: SkillGapSort) => void;
  selectedSkillId: string | null;
  onSelectSkill: (skillId: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Highest priority skill gaps</CardTitle>
        <CardDescription>
          Priority combines demand (50%), the demonstrated-skill gap (40%) and
          demand growth (10% when a comparable period exists). Demonstrated and
          self-reported counts are separate evidence types — reporting a skill
          is not demonstrating it. Click a column header to re-sort, a row to
          inspect the skill.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {skills.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No skills match the current filters.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-2 py-2 font-medium">Skill</th>
                  <th className="px-2 py-2 font-medium">Category</th>
                  <th className="px-2 py-2 text-right font-medium">Postings</th>
                  {SORTABLE_COLUMNS.map((column) => (
                    <th
                      key={column.key}
                      className="px-2 py-2 text-right font-medium"
                    >
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 hover:text-foreground"
                        onClick={() => onSortChange(column.key)}
                      >
                        {column.label}
                        {sort === column.key ? (
                          <ArrowUp className="h-3 w-3" />
                        ) : (
                          <ArrowUpDown className="h-3 w-3 opacity-40" />
                        )}
                      </button>
                    </th>
                  ))}
                  <th className="px-2 py-2 text-right font-medium">Demonstrated</th>
                  <th className="px-2 py-2 text-right font-medium">Self-reported</th>
                  <th className="px-2 py-2 text-right font-medium">Lacking</th>
                  <th className="px-2 py-2 text-right font-medium">Priority</th>
                </tr>
              </thead>
              <tbody>
                {skills.map((skill) => (
                  <tr
                    key={skill.skill_id}
                    onClick={() => onSelectSkill(skill.skill_id)}
                    className={`cursor-pointer border-b transition-colors hover:bg-secondary/60 ${
                      selectedSkillId === skill.skill_id ? "bg-secondary" : ""
                    }`}
                  >
                    <td className="px-2 py-2 font-medium">{skill.name}</td>
                    <td className="px-2 py-2 text-muted-foreground">
                      {skill.category ?? "—"}
                    </td>
                    <td className="px-2 py-2 text-right">{skill.posting_count}</td>
                    <td className="px-2 py-2 text-right">{skill.demand_pct}%</td>
                    <td className="px-2 py-2 text-right">{skill.gap_pct}%</td>
                    <td className="px-2 py-2 text-right">{skill.priority_score}</td>
                    <td className="px-2 py-2 text-right">
                      {skill.students_demonstrated}
                      <span className="text-muted-foreground">
                        {" "}
                        ({skill.demonstrated_pct}%)
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right">
                      {skill.students_reported}
                      <span className="text-muted-foreground"> ({skill.reported_pct}%)</span>
                    </td>
                    <td className="px-2 py-2 text-right">
                      {skill.students_lacking_demonstrated}
                    </td>
                    <td className="px-2 py-2 text-right">
                      <Badge variant={PRIORITY_VARIANT[skill.priority_class]}>
                        {skill.priority_class}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
