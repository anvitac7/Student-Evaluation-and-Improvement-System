import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type {
  ApplicationDetail,
  ApplicationStatus,
  BulkApplicationStatusRequest,
  BulkStatusResult,
  DriveCreateRequest,
  DriveDetail,
  DriveSummary,
  DriveUpdateRequest,
  ScreeningSummary,
} from "@/types/drive";

const MY_DRIVES_KEY = ["drives", "mine"] as const;
const DRIVE_DETAIL_KEY = (id: string) => ["drives", id] as const;
const DRIVE_APPLICANTS_KEY = (driveId: string, params?: Record<string, unknown>) =>
  ["drives", driveId, "applications", params] as const;
const DRIVE_SCREENING_SUMMARY_KEY = (driveId: string) => ["drives", driveId, "screening-summary"] as const;

export function useMyDrives() {
  return useQuery({
    queryKey: MY_DRIVES_KEY,
    queryFn: async () => {
      const { data } = await apiClient.get<DriveSummary[]>("/drives/mine", { params: { limit: 100 } });
      return data;
    },
  });
}

export function useCreateDrive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: DriveCreateRequest) => {
      const { data } = await apiClient.post<DriveDetail>("/drives", payload);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MY_DRIVES_KEY });
    },
  });
}

export function useUpdateDrive(driveId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: DriveUpdateRequest) => {
      const { data } = await apiClient.put<DriveDetail>(`/drives/${driveId}`, payload);
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(DRIVE_DETAIL_KEY(driveId), data);
      queryClient.invalidateQueries({ queryKey: MY_DRIVES_KEY });
    },
  });
}

export function useCloneDrive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (driveId: string) => {
      const { data } = await apiClient.post<DriveDetail>(`/drives/${driveId}/clone`);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MY_DRIVES_KEY });
    },
  });
}

export function useDeleteDrive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (driveId: string) => {
      await apiClient.delete(`/drives/${driveId}`);
      return driveId;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MY_DRIVES_KEY });
    },
  });
}

export function useDriveApplicants(
  driveId: string,
  filters?: {
    status?: string;
    assessment_status?: string;
    eligible_only?: boolean;
    sort_by?: string;
    sort_order?: string;
  }
) {
  return useQuery({
    queryKey: DRIVE_APPLICANTS_KEY(driveId, filters),
    queryFn: async () => {
      const { data } = await apiClient.get<ApplicationDetail[]>(`/drives/${driveId}/applications`, {
        params: filters,
      });
      return data;
    },
    enabled: Boolean(driveId),
  });
}

export function useScreeningSummary(driveId: string) {
  return useQuery({
    queryKey: DRIVE_SCREENING_SUMMARY_KEY(driveId),
    queryFn: async () => {
      const { data } = await apiClient.get<ScreeningSummary>(`/drives/${driveId}/screening-summary`);
      return data;
    },
    enabled: Boolean(driveId),
  });
}

export function useTriggerScreening(driveId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post<ApplicationDetail[]>(`/drives/${driveId}/screen`);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["drives", driveId] });
    },
  });
}

export function useRecommendedShortlist(driveId: string, topN = 10) {
  return useQuery({
    queryKey: ["drives", driveId, "recommended-shortlist", topN],
    queryFn: async () => {
      const { data } = await apiClient.get<ApplicationDetail[]>(`/drives/${driveId}/recommended-shortlist`, {
        params: { top_n: topN },
      });
      return data;
    },
    enabled: Boolean(driveId),
  });
}

export function useUpdateApplicationStatus(driveId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      applicationId,
      status,
      rejectionReasons,
      rejectionNote,
    }: {
      applicationId: string;
      status: ApplicationStatus;
      rejectionReasons?: string[];
      rejectionNote?: string;
    }) => {
      const { data } = await apiClient.patch<ApplicationDetail>(
        `/drives/${driveId}/applications/${applicationId}`,
        { status, rejection_reasons: rejectionReasons, rejection_note: rejectionNote }
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["drives", driveId] });
    },
  });
}

export function useBulkUpdateApplicationStatus(driveId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: BulkApplicationStatusRequest) => {
      const { data } = await apiClient.patch<BulkStatusResult>(
        `/drives/${driveId}/applications/bulk-status`,
        payload
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["drives", driveId] });
    },
  });
}

export async function exportApplicationsCsv(driveId: string, filename?: string): Promise<void> {
  const response = await apiClient.get(`/drives/${driveId}/applications/export`, {
    responseType: "blob",
  });
  const blobUrl = URL.createObjectURL(response.data as Blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename || `applicants_drive_${driveId.slice(0, 8)}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(blobUrl);
}
