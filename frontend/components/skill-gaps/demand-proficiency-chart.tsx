"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Info } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { SkillGapEntry } from "@/types/skill-gaps";

/**
 * Industry demand vs student proficiency, three series per skill:
 * demand %, assessment-demonstrated %, self-reported %. Self-reported is a
 * separate bar on purpose — reporting a skill is NOT demonstrating it.
 * Shows the top skills by priority (a chart of every skill is unreadable);
 * "Show all" expands the full list.
 */
const PREVIEW_COUNT = 12;

export function DemandProficiencyChart({ skills }: { skills: SkillGapEntry[] }) {
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? skills : skills.slice(0, PREVIEW_COUNT);
  const data = rows.map((skill) => ({
    name: skill.name,
    "Industry demand %": skill.demand_pct,
    "Assessment-demonstrated %": skill.demonstrated_pct,
    "Self-reported %": skill.reported_pct,
  }));

  if (skills.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          Demand vs student proficiency
        </CardTitle>
        <CardDescription className="flex items-start gap-1.5">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            High demand with low demonstrated percentage marks a skill worth
            training. The self-reported bar includes students who only list the
            skill in their profile or resume — it is not proof of proficiency.
            {skills.length > PREVIEW_COUNT && !showAll &&
              ` Showing the ${PREVIEW_COUNT} highest-priority skills of ${skills.length}.`}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={340}>
          <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 11 }}
              interval={0}
              angle={-30}
              textAnchor="end"
              height={64}
            />
            <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} unit="%" />
            <Tooltip formatter={(value) => `${value}%`} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="Industry demand %" fill="#6366f1" radius={[3, 3, 0, 0]} />
            <Bar dataKey="Assessment-demonstrated %" fill="#22c55e" radius={[3, 3, 0, 0]} />
            <Bar dataKey="Self-reported %" fill="#f59e0b" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        {skills.length > PREVIEW_COUNT && (
          <div className="mt-2 text-center">
            <Button variant="outline" size="sm" onClick={() => setShowAll((value) => !value)}>
              {showAll ? "Show top skills only" : `Show all ${skills.length} skills`}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
