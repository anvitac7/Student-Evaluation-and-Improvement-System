/**
 * Types for the TPO Skill Gap Analysis dashboard (Phase 8).
 *
 * Mirrors the backend Pydantic response models exactly
 * (backend/app/models/analytics.py, "Phase 8" section). Field names,
 * nullability and enum values must not diverge — the backend contract is
 * the source of truth.
 *
 * Two student evidence perspectives are always kept separate:
 * assessment-demonstrated proficiency vs self-reported skills. Yearly
 * maps arrive with JSON string keys (backend `dict[int, ...]`).
 */

import type { MarketMeta, MarketFiltersResponse } from "@/types/market-analytics";

export type AssessmentEvidenceClass =
  | "demonstrated"
  | "developing"
  | "not_demonstrated"
  | "insufficient_evidence";

export type StudentSkillGapClass =
  | "both"
  | "demonstrated"
  | "developing"
  | "not_demonstrated"
  | "reported_only"
  | "insufficient_evidence"
  | "no_evidence";

export type SkillGapStudentFilter =
  | "all"
  | StudentSkillGapClass;

export type SkillGapSort = "priority" | "demand" | "gap";
export type PriorityClass = "high" | "medium" | "low";

export interface SkillGapThresholds {
  min_graded_answers: number;
  demonstrated_min_pct: number;
  developing_min_pct: number;
  priority_weights: Record<string, number>;
  priority_class_thresholds: Record<string, number>;
}

export interface StudentEvidenceSource {
  assessment_title: string;
  attempts_used: number;
  questions_answered: number;
  correct_answers: number;
}

export interface SkillCompanyDemand {
  company_slug: string;
  company_name: string;
  posting_count: number;
  demand_pct: number;
}

export interface SkillJobFamilyDemand {
  job_family: string;
  posting_count: number;
  demand_pct: number;
}

export interface SkillYearDemand {
  year: number;
  posting_count: number;
  demand_pct: number;
  yoy_growth_pct: number | null;
}

export interface SkillGapEntry {
  skill_id: string;
  name: string;
  category: string | null;
  is_technical: boolean;
  // Industry demand (Market Insights dataset, filtered population).
  posting_count: number;
  demand_pct: number;
  demanding_company_count: number;
  demanding_job_family_count: number;
  yearly_counts: Record<string, number>;
  yearly_demand_pct: Record<string, number>;
  latest_growth_pct: number | null;
  growth_comparable: boolean;
  // Student evidence (aggregated over the whole student population).
  students_demonstrated: number;
  students_developing: number;
  students_not_demonstrated: number;
  students_insufficient_evidence: number;
  students_reported: number;
  students_reported_only: number;
  students_both: number;
  students_no_evidence: number;
  students_lacking_demonstrated: number;
  demonstrated_pct: number;
  reported_pct: number;
  gap_pct: number;
  // Gap result.
  priority_score: number;
  priority_class: PriorityClass;
  // Detail views (bounded).
  top_companies: SkillCompanyDemand[];
  top_job_families: SkillJobFamilyDemand[];
  years: SkillYearDemand[];
}

export interface MostDemandedMissingSkill {
  skill_id: string;
  name: string;
  posting_count: number;
  demand_pct: number;
}

export interface RisingDemandSkill {
  skill_id: string;
  name: string;
  latest_growth_pct: number;
  demand_pct: number;
  demonstrated_pct: number;
}

export interface SkillGapSummary {
  total_skills_analyzed: number;
  high_priority_gaps: number;
  student_population: number;
  students_lacking_demonstrated_skills: number;
  students_with_reported_skills: number;
  students_with_assessment_evidence: number;
  most_demanded_missing_skill: MostDemandedMissingSkill | null;
  rising_demand_skills: RisingDemandSkill[];
}

export interface SkillGapMeta {
  market: MarketMeta;
  thresholds: SkillGapThresholds;
  eligible_drive_count: number;
  eligible_assessment_count: number;
  submitted_eligible_attempt_count: number;
  unmapped_assessment_skill_tags: string[];
  unmapped_self_reported_skills: string[];
  notes: string[];
}

export interface SkillGapAnalysisResponse {
  meta: SkillGapMeta;
  summary: SkillGapSummary;
  skills: SkillGapEntry[];
}

export interface SkillGapStudentEntry {
  student_id: string;
  student_name: string;
  department: string | null;
  batch_year: number | null;
  self_reported: boolean;
  self_reported_via: string[];
  classification: StudentSkillGapClass;
  assessment_classification: AssessmentEvidenceClass | null;
  skill_accuracy_pct: number | null;
  questions_answered: number;
  correct_answers: number;
  assessment_evidence: StudentEvidenceSource[];
}

export interface SkillGapStudentsResponse {
  skill_id: string;
  skill_name: string;
  classification: SkillGapStudentFilter;
  student_population: number;
  total: number;
  page: number;
  limit: number;
  entries: SkillGapStudentEntry[];
}

/** Query parameters accepted by GET /api/v1/analytics/tpo/skill-gaps. */
export interface SkillGapParams {
  year_from?: number;
  year_to?: number;
  company?: string;
  job_family?: string;
  location?: string;
  skill_category?: string;
  technical_only?: boolean;
  sort?: SkillGapSort;
}

export type { MarketFiltersResponse as SkillGapFilterOptions };
