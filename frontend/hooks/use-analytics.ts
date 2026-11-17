import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type {
  AdminAnalytics,
  DriveApplicantsResponse,
  DriveAssessmentRanking,
  DriveParticipantsResponse,
  TpoAnalytics,
} from "@/types/analytics";

export function useTpoAnalytics() {
  return useQuery({
    queryKey: ["analytics", "tpo"],
    queryFn: async () => {
      const { data } = await apiClient.get<TpoAnalytics>("/analytics/tpo");
      return data;
    },
  });
}

/**
 * Per-drive analytics detail (rankings / applicants / participants), shown
 * inside each drive's expanded breakdown. `enabled` keeps a closed drive
 * from issuing requests; every parameter is part of the query key so a
 * page/search change can never display another combination's results, and
 * `keepPreviousData` keeps the current list visible while the next page or
 * search result loads.
 */
export function useDriveRanking(driveId: string | null) {
  return useQuery({
    queryKey: ["analytics", "tpo", "drive", driveId, "ranking"] as const,
    enabled: Boolean(driveId),
    queryFn: async () => {
      const { data } = await apiClient.get<DriveAssessmentRanking>(
        `/analytics/tpo/drives/${driveId}/ranking`
      );
      return data;
    },
  });
}

export function useDriveApplicants(driveId: string | null, page: number, search: string) {
  const trimmed = search.trim();
  return useQuery({
    queryKey: ["analytics", "tpo", "drive", driveId, "applicants", page, trimmed] as const,
    enabled: Boolean(driveId),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data } = await apiClient.get<DriveApplicantsResponse>(
        `/analytics/tpo/drives/${driveId}/applicants`,
        { params: { page, limit: 20, ...(trimmed ? { search: trimmed } : {}) } }
      );
      return data;
    },
  });
}

export function useDriveParticipants(driveId: string | null, page: number, search: string) {
  const trimmed = search.trim();
  return useQuery({
    queryKey: ["analytics", "tpo", "drive", driveId, "participants", page, trimmed] as const,
    enabled: Boolean(driveId),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data } = await apiClient.get<DriveParticipantsResponse>(
        `/analytics/tpo/drives/${driveId}/participants`,
        { params: { page, limit: 20, ...(trimmed ? { search: trimmed } : {}) } }
      );
      return data;
    },
  });
}

export function useAdminAnalytics() {
  return useQuery({
    queryKey: ["analytics", "admin"],
    queryFn: async () => {
      const { data } = await apiClient.get<AdminAnalytics>("/analytics/admin");
      return data;
    },
  });
}
