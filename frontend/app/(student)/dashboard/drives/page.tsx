"use client";

import { useState } from "react";
import Link from "next/link";
import { Briefcase, MapPin, Sparkles, Filter } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { useDrives } from "@/hooks/use-drives";
import { useRecommendedDrives } from "@/hooks/use-matching";

function formatDeadline(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function isPastDeadline(iso: string): boolean {
  return new Date(iso).getTime() < Date.now();
}

export default function DrivesPage() {
  const [statusFilter, setStatusFilter] = useState<"open" | "closed" | "all">("all");
  const { data: drives, isLoading } = useDrives(statusFilter === "all" ? undefined : statusFilter);
  const { data: recommended, isLoading: recommendedLoading, error: recommendedError } = useRecommendedDrives(3);
  const recommendedUnavailable = (recommendedError as any)?.response?.status === 503;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold">Placement drives</h1>
          <p className="text-sm text-muted-foreground">Browse open drives and apply with your active resume.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={statusFilter === "open" ? "default" : "outline"}
            size="sm"
            onClick={() => setStatusFilter("open")}
            className="gap-1.5"
          >
            <Filter className="h-3.5 w-3.5" />
            Open
          </Button>
          <Button
            variant={statusFilter === "closed" ? "default" : "outline"}
            size="sm"
            onClick={() => setStatusFilter("closed")}
            className="gap-1.5"
          >
            <Filter className="h-3.5 w-3.5" />
            Closed
          </Button>
          <Button
            variant={statusFilter === "all" ? "default" : "outline"}
            size="sm"
            onClick={() => setStatusFilter("all")}
            className="gap-1.5"
          >
            All
          </Button>
        </div>
      </div>

      {!recommendedUnavailable && (recommendedLoading || (recommended && recommended.length > 0)) && (
        <div>
          <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
            <Sparkles className="h-4 w-4" /> Recommended for you
          </h2>
          {recommendedLoading ? (
            <div className="grid gap-4 sm:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-32 w-full" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-3">
              {recommended!.map((rec) => (
                <Link key={rec.drive_id} href={`/dashboard/drives/${rec.drive_id}`}>
                  <Card className="h-full border-primary transition-colors hover:border-primary">
                    <CardHeader>
                      <div className="flex items-start justify-between gap-2">
                        <CardTitle className="text-base">{rec.job_title}</CardTitle>
                        <Badge>{Math.round(rec.final_score * 100)}%</Badge>
                      </div>
                      <p className="text-sm text-muted-foreground">{rec.company_name}</p>
                    </CardHeader>
                    <CardContent className="text-sm text-muted-foreground">
                      {rec.matched_skills.length > 0 ? (
                        <span>Matches on {rec.matched_skills.slice(0, 3).join(", ")}</span>
                      ) : (
                        <span>Based on your profile</span>
                      )}
                    </CardContent>
                  </Card>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}

      <div>
        {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      ) : !drives || drives.length === 0 ? (
        <EmptyState icon={Briefcase} title="No drives available" description="Check back later for new placement drives." />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {drives.map((drive) => {
            const closed = drive.status === "closed" || isPastDeadline(drive.deadline);
            return (
              <Link key={drive.id} href={`/dashboard/drives/${drive.id}`}>
                <Card className="h-full transition-colors hover:border-primary">
                  <CardHeader>
                    <div className="flex items-start justify-between gap-2">
                      <CardTitle className="text-base">{drive.job_title}</CardTitle>
                      <Badge variant={closed ? "secondary" : "success"}>{closed ? "Closed" : "Open"}</Badge>
                    </div>
                    <p className="text-sm text-muted-foreground">{drive.company.name}</p>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    {drive.location && (
                      <div className="flex items-center gap-1.5 text-muted-foreground">
                        <MapPin className="h-3.5 w-3.5" />
                        {drive.location}
                      </div>
                    )}
                    {drive.package && <div className="text-muted-foreground">Package: {drive.package}</div>}
                    <div className="text-muted-foreground">Apply by {formatDeadline(drive.deadline)}</div>
                    {drive.required_skills.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {drive.required_skills.slice(0, 4).map((skill) => (
                          <Badge key={skill} variant="outline">
                            {skill}
                          </Badge>
                        ))}
                        {drive.required_skills.length > 4 && (
                          <Badge variant="outline">+{drive.required_skills.length - 4}</Badge>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
      </div>
    </div>
  );
}
