import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type { ApplicationExplanation } from "@/types/explanation";

export function useApplicationExplanation(applicationId: string | null) {
  return useQuery({
    queryKey: ["applications", applicationId, "explanation"],
    queryFn: async () => {
      const { data } = await apiClient.get<ApplicationExplanation>(`/applications/${applicationId}/explanation`);
      return data;
    },
    enabled: Boolean(applicationId),
  });
}

