"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  RotateCcw,
  Search,
  Trophy,
  Users,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/shared/empty-state";
import {
  useDriveApplicants,
  useDriveParticipants,
  useDriveRanking,
} from "@/hooks/use-analytics";
import type { DriveFunnel } from "@/types/analytics";

/**
 * Per-drive analytics breakdown. Every drive expands into its own overview
 * plus Rankings / Applied students / Test participants tabs — the rankings
 * live HERE now (one list per drive) instead of in a separate standalone
 * section. Panels fetch their own data lazily: a collapsed drive issues no
 * requests, and an expanded drive only fetches the tab being viewed.
 */

const PAGE_SIZE = 20;

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function useDebouncedValue<T>(value: T, delay = 400): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function RetryBox({ onRetry, label }: { onRetry: () => void; label: string }) {
  return (
    <div className="flex flex-col items-start gap-2 py-4">
      <p className="flex items-center gap-2 text-sm text-destructive">
        <AlertCircle className="h-4 w-4" /> Couldn&apos;t load {label}.
      </p>
      <Button size="sm" variant="outline" onClick={onRetry} className="gap-1.5">
        <RotateCcw className="h-3.5 w-3.5" /> Retry
      </Button>
    </div>
  );
}

function SearchBox({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <div className="relative w-full max-w-xs">
      <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="pl-8"
      />
    </div>
  );
}

function ListPager({
  page,
  totalPages,
  onPage,
}: {
  page: number;
  totalPages: number;
  onPage: (page: number) => void;
}) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between border-t border-border pt-3 text-sm text-muted-foreground">
      <span>
        Page {page} of {totalPages}
      </span>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          Previous
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={page >= totalPages}
          onClick={() => onPage(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

function applicationStatusVariant(status: string) {
  switch (status) {
    case "selected":
      return "success" as const;
    case "shortlisted":
      return "outline" as const;
    case "rejected":
      return "destructive" as const;
    default:
      return "secondary" as const;
  }
}

// ---------------------------------------------------------------------------
// Rankings (inside the drive — relocated from the standalone section)
// ---------------------------------------------------------------------------
function RankingPanel({ drive }: { drive: DriveFunnel }) {
  const { data, isLoading, isError, refetch } = useDriveRanking(drive.drive_id);

  if (isLoading) {
    return (
      <div className="space-y-2 py-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }
  if (isError || !data) {
    return <RetryBox onRetry={() => refetch()} label="the ranking" />;
  }
  if (data.entries.length === 0) {
    return (
      <p className="py-3 text-sm text-muted-foreground">
        {drive.required_assessment_id
          ? "No submitted attempts yet. Rankings appear once students complete this drive's assessment."
          : "This drive has no required assessment, so there is nothing to rank."}
      </p>
    );
  }

  return (
    <div className="divide-y divide-border rounded-md border border-border">
      <div className="flex items-center justify-between border-b border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        <span>{data.assessment_title}</span>
        <span>{data.entries.length} ranked</span>
      </div>
      {data.entries.map((entry) => (
        <div key={entry.student_id} className="flex items-center gap-3 p-3 text-sm">
          <span
            className={
              entry.rank === 1
                ? "flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
                : "flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold"
            }
          >
            {entry.rank}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{entry.student_name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {entry.department ?? "—"}
              {entry.cgpa != null && ` · CGPA ${entry.cgpa}`}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="font-semibold">{entry.score_pct}%</p>
            <p className="text-xs text-muted-foreground">{formatDate(entry.submitted_at)}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Applied students (via the application → drive relationship)
// ---------------------------------------------------------------------------
function ApplicantsPanel({ drive }: { drive: DriveFunnel }) {
  const [searchDraft, setSearchDraft] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebouncedValue(searchDraft);
  const { data, isLoading, isError, refetch, isRefetching } = useDriveApplicants(
    drive.drive_id,
    page,
    search
  );

  // A narrowed search can shrink the result below the current page.
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;
  useEffect(() => {
    if (data && data.page > totalPages) setPage(1);
  }, [data, totalPages]);

  return (
    <div className="space-y-3">
      <SearchBox
        value={searchDraft}
        onChange={(value) => {
          setSearchDraft(value);
          setPage(1);
        }}
        placeholder="Search applicants by name…"
      />
      {isLoading ? (
        <div className="space-y-2 py-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : isError || !data ? (
        <RetryBox onRetry={() => refetch()} label="the applicant list" />
      ) : data.entries.length === 0 ? (
        <p className="py-3 text-sm text-muted-foreground">
          {searchDraft
            ? "No applicants match that search."
            : "No students have applied to this drive yet."}
        </p>
      ) : (
        <div className="divide-y divide-border rounded-md border border-border">
          {data.entries.map((entry) => (
            <div key={entry.application_id} className="flex items-center gap-3 p-3 text-sm">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{entry.student_name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {entry.department ?? "—"}
                  {entry.batch_year != null && ` · Batch ${entry.batch_year}`}
                </p>
              </div>
              <Badge
                variant={applicationStatusVariant(entry.status)}
                className="w-24 shrink-0 justify-center"
              >
                {entry.status}
              </Badge>
              <span className="hidden w-24 shrink-0 text-right text-xs text-muted-foreground sm:block">
                {formatDate(entry.applied_at)}
              </span>
            </div>
          ))}
        </div>
      )}
      {data && data.entries.length > 0 && (
        <ListPager page={data.page} totalPages={totalPages} onPage={setPage} />
      )}
      {isRefetching && <p className="text-xs text-muted-foreground">Updating…</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Test participants (actual attempts — never applications or assignments)
// ---------------------------------------------------------------------------
function ParticipantsPanel({ drive }: { drive: DriveFunnel }) {
  const [searchDraft, setSearchDraft] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebouncedValue(searchDraft);
  const { data, isLoading, isError, refetch, isRefetching } = useDriveParticipants(
    drive.drive_id,
    page,
    search
  );

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;
  useEffect(() => {
    if (data && data.page > totalPages) setPage(1);
  }, [data, totalPages]);

  return (
    <div className="space-y-3">
      <SearchBox
        value={searchDraft}
        onChange={(value) => {
          setSearchDraft(value);
          setPage(1);
        }}
        placeholder="Search participants by name…"
      />
      {isLoading ? (
        <div className="space-y-2 py-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : isError || !data ? (
        <RetryBox onRetry={() => refetch()} label="the participant list" />
      ) : data.entries.length === 0 ? (
        <p className="py-3 text-sm text-muted-foreground">
          {data.assessment_id
            ? searchDraft
              ? "No participants match that search."
              : "No one has started this drive's assessment yet."
            : "This drive has no required assessment."}
        </p>
      ) : (
        <div className="divide-y divide-border rounded-md border border-border">
          {data.entries.map((entry) => (
            <div key={entry.attempt_id} className="flex items-center gap-3 p-3 text-sm">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{entry.student_name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {entry.department ?? "—"}
                  {entry.batch_year != null && ` · Batch ${entry.batch_year}`}
                </p>
              </div>
              <Badge
                variant={entry.attempt_status === "submitted" ? "success" : "warning"}
                className="w-24 shrink-0 justify-center"
              >
                {entry.attempt_status === "submitted" ? "submitted" : "in progress"}
              </Badge>
              <div className="w-24 shrink-0 text-right">
                <p className="font-semibold">{entry.score_pct != null ? `${entry.score_pct}%` : "—"}</p>
                <p className="hidden text-xs text-muted-foreground sm:block">
                  {formatDate(entry.submitted_at)}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
      {data && data.entries.length > 0 && (
        <ListPager page={data.page} totalPages={totalPages} onPage={setPage} />
      )}
      {isRefetching && <p className="text-xs text-muted-foreground">Updating…</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The expandable per-drive card
// ---------------------------------------------------------------------------
function DriveCard({ drive }: { drive: DriveFunnel }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-md border border-border">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start justify-between gap-3 p-4 text-left"
        aria-expanded={open}
      >
        <div className="min-w-0">
          <p className="font-medium">{drive.job_title}</p>
          <p className="text-sm text-muted-foreground">{drive.company_name}</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>{drive.total_applications} applied</span>
            <span>{drive.breakdown.shortlisted} shortlisted</span>
            <span>{drive.breakdown.rejected} rejected</span>
            <span>{drive.breakdown.selected} selected</span>
            <span>
              {drive.participant_count} took the test
              {drive.submitted_participant_count !== drive.participant_count &&
                ` (${drive.submitted_participant_count} submitted)`}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant={drive.status === "open" ? "success" : "secondary"}>{drive.status}</Badge>
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>

      {open && (
        <div className="border-t border-border p-4">
          <Tabs defaultValue="ranking">
            <TabsList className="mb-3">
              <TabsTrigger value="ranking" className="gap-1.5">
                <Trophy className="h-3.5 w-3.5" /> Rankings
              </TabsTrigger>
              <TabsTrigger value="applicants" className="gap-1.5">
                <Users className="h-3.5 w-3.5" /> Applied students
              </TabsTrigger>
              <TabsTrigger value="participants" className="gap-1.5">
                <ClipboardList className="h-3.5 w-3.5" /> Test participants
              </TabsTrigger>
            </TabsList>
            <TabsContent value="ranking">
              <RankingPanel drive={drive} />
            </TabsContent>
            <TabsContent value="applicants">
              <ApplicantsPanel drive={drive} />
            </TabsContent>
            <TabsContent value="participants">
              <ParticipantsPanel drive={drive} />
            </TabsContent>
          </Tabs>
        </div>
      )}
    </div>
  );
}

export function DriveBreakdown({ drives }: { drives: DriveFunnel[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Per-drive breakdown</CardTitle>
        <p className="text-sm text-muted-foreground">
          Expand a drive to see its rankings, applied students and test participants.
        </p>
      </CardHeader>
      <CardContent className="space-y-2">
        {drives.length === 0 ? (
          <p className="text-sm text-muted-foreground">No drives created yet.</p>
        ) : (
          drives.map((drive) => <DriveCard key={drive.drive_id} drive={drive} />)
        )}
      </CardContent>
    </Card>
  );
}
