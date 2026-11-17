import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type { ApplicationResponse, DriveDetail, DriveSummary } from "@/types/drive";

const DRIVES_LIST_KEY = ["drives"] as const;
const DRIVE_DETAIL_KEY = (id: string) => ["drives", id] as const;
const MY_APPLICATIONS_KEY = ["drives", "applications", "me"] as const;

export function useDrives(statusFilter?: "open" | "closed") {
  return useQuery({
    queryKey: [...DRIVES_LIST_KEY, statusFilter ?? "all"],
    queryFn: async () => {
      const params: Record<string, string | number> = { limit: 100 };
      if (statusFilter) {
        params.status_filter = statusFilter;
      }
      const { data } = await apiClient.get<DriveSummary[]>("/drives", { params });
      return data;
    },
  });
}

export function useDriveDetail(driveId: string) {
  return useQuery({
    queryKey: DRIVE_DETAIL_KEY(driveId),
    queryFn: async () => {
      const { data } = await apiClient.get<DriveDetail>(`/drives/${driveId}`);
      return data;
    },
    enabled: Boolean(driveId),
  });
}

export function useMyApplications() {
  return useQuery({
    queryKey: MY_APPLICATIONS_KEY,
    queryFn: async () => {
      const { data } = await apiClient.get<ApplicationResponse[]>("/drives/applications/me");
      return data;
    },
  });
}

export function useApplyToDrive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (driveId: string) => {
      const { data } = await apiClient.post<ApplicationResponse>(`/drives/${driveId}/apply`);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MY_APPLICATIONS_KEY });
    },
  });
}
