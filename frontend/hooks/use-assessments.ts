import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type {
  AssessmentResponse,
  AttemptResultResponse,
  KnowledgeStateResponse,
  StartAttemptResponse,
  StudentInsightsResponse,
  SubmitAnswerResponse,
  ViolationReportResponse,
} from "@/types/assessment";

export function useAssessments() {
  return useQuery({
    queryKey: ["assessments"],
    queryFn: async () => {
      const { data } = await apiClient.get<AssessmentResponse[]>("/assessments");
      return data;
    },
  });
}

/** Cross-attempt focus areas + study guide for the logged-in student. */
export function useStudentInsights() {
  return useQuery({
    queryKey: ["insights", "me"],
    queryFn: async () => {
      const { data } = await apiClient.get<StudentInsightsResponse>("/insights/me");
      return data;
    },
  });
}

export function useKnowledgeStates() {
  return useQuery({
    queryKey: ["assessments", "knowledge-states", "me"],
    queryFn: async () => {
      const { data } = await apiClient.get<KnowledgeStateResponse[]>("/assessments/knowledge-states/me");
      return data;
    },
  });
}

/** TPO/admin view of a specific student's mastery — used from the applicant-review page. */
export function useStudentKnowledgeStates(studentId: string | null) {
  return useQuery({
    queryKey: ["assessments", "knowledge-states", studentId],
    queryFn: async () => {
      const { data } = await apiClient.get<KnowledgeStateResponse[]>(`/assessments/knowledge-states/${studentId}`);
      return data;
    },
    enabled: Boolean(studentId),
  });
}

export function useAttemptResults(attemptId: string | null) {
  return useQuery({
    queryKey: ["assessments", "attempts", attemptId, "results"],
    queryFn: async () => {
      const { data } = await apiClient.get<AttemptResultResponse>(`/assessments/attempts/${attemptId}/results`);
      return data;
    },
    enabled: Boolean(attemptId),
  });
}

/**
 * The rest of the attempt flow (start -> answer -> answer -> ... -> submit)
 * is inherently sequential, stateful, per-session data, not something that
 * benefits from react-query's caching model — the take-assessment page
 * keeps that state locally and just uses these as plain mutation wrappers.
 */
export function useStartAssessment() {
  return useMutation({
    mutationFn: async ({ assessmentId, fingerprintHash }: { assessmentId: string; fingerprintHash?: string }) => {
      const { data } = await apiClient.post<StartAttemptResponse>(`/assessments/${assessmentId}/start`, {
        fingerprint_hash: fingerprintHash ?? null,
      });
      return data;
    },
  });
}

export function useSubmitAnswer() {
  return useMutation({
    mutationFn: async (payload: {
      attemptId: string;
      sessionToken: string;
      questionId: string;
      response: string;
      timeTakenSec?: number;
    }) => {
      const { data } = await apiClient.post<SubmitAnswerResponse>(`/assessments/attempts/${payload.attemptId}/answer`, {
        session_token: payload.sessionToken,
        question_id: payload.questionId,
        response: payload.response,
        time_taken_sec: payload.timeTakenSec ?? null,
      });
      return data;
    },
  });
}

export function useReportViolation() {
  return useMutation({
    mutationFn: async (payload: {
      attemptId: string;
      sessionToken: string;
      type: string;
      metadata?: Record<string, unknown>;
    }) => {
      const { data } = await apiClient.post<ViolationReportResponse>(
        `/assessments/attempts/${payload.attemptId}/violation`,
        {
          session_token: payload.sessionToken,
          type: payload.type,
          metadata: payload.metadata ?? {},
        }
      );
      return data;
    },
  });
}
