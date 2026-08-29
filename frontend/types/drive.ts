export type DriveStatus = "open" | "closed";
export type ApplicationStatus = "applied" | "shortlisted" | "rejected" | "selected";
export type AssessmentStatus = "not_required" | "pending" | "passed" | "failed" | "expired";

export type RejectionReason =
  | "low_match_score"
  | "skill_gap"
  | "low_assessment_score"
  | "assessment_not_attempted"
  | "eligibility"
  | "experience_gap"
  | "other";

export interface EligibilityCriteria {
  min_cgpa: number | null;
  departments: string[];
  batch_years: number[];
}

export interface CompanySummary {
  id: string;
  name: string;
  description: string | null;
  website: string | null;
  industry: string | null;
}

export interface DriveSummary {
  id: string;
  company: CompanySummary;
  job_title: string;
  package: string | null;
  location: string | null;
  deadline: string;
  status: DriveStatus;
  required_skills: string[];
}

export interface DriveDetail extends DriveSummary {
  description: string;
  jd_text: string;
  eligibility: EligibilityCriteria;
  selection_process: string[];
  experience_required_years: number;
  created_at: string;
  required_assessment_id?: string | null;
  assessment_min_score_pct?: number | null;
  assessment_deadline?: string | null;
}

export interface ApplicationResponse {
  id: string;
  drive_id: string;
  student_id: string;
  resume_id: string;
  status: ApplicationStatus;
  applied_at: string;
  eligibility_passed?: boolean | null;
  eligibility_reasons?: string[];
  final_score?: number | null;
  semantic_score?: number | null;
  skills_score?: number | null;
  experience_score?: number | null;
  matched_skills?: string[];
  missing_skills?: string[];
  assessment_attempt_id?: string | null;
  assessment_score_pct?: number | null;
  assessment_status?: AssessmentStatus;
  rejection_reasons?: string[];
  rejection_note?: string | null;
  decision_at?: string | null;
}

export interface ApplicationDetail extends ApplicationResponse {
  student_name: string;
  student_department: string | null;
  student_cgpa: number | null;
  resume_filename: string | null;
}

export interface DriveCreateRequest {
  company_name: string;
  company_description?: string;
  company_website?: string;
  company_industry?: string;
  job_title: string;
  description: string;
  jd_text: string;
  required_skills: string[];
  experience_required_years?: number;
  package?: string;
  location?: string;
  eligibility: EligibilityCriteria;
  deadline: string;
  selection_process: string[];
  required_assessment_id?: string | null;
  assessment_min_score_pct?: number | null;
  assessment_deadline?: string | null;
}

export interface DriveUpdateRequest {
  job_title?: string;
  description?: string;
  jd_text?: string;
  required_skills?: string[];
  experience_required_years?: number;
  package?: string;
  location?: string;
  eligibility?: EligibilityCriteria;
  deadline?: string;
  selection_process?: string[];
  status?: DriveStatus;
  required_assessment_id?: string | null;
  assessment_min_score_pct?: number | null;
  assessment_deadline?: string | null;
}

export interface BulkApplicationStatusRequest {
  application_ids: string[];
  status: ApplicationStatus;
  rejection_reasons?: string[];
  rejection_note?: string | null;
}

export interface BulkStatusResult {
  updated_count: number;
  failed_ids: string[];
  errors: string[];
}

export interface ScreeningSummary {
  total_applications: number;
  eligible: number;
  ineligible: number;
  assessment_pending: number;
  assessment_passed: number;
  assessment_failed: number;
  assessment_expired: number;
  assessment_not_required: number;
  shortlisted: number;
  rejected: number;
  selected: number;
  recommended_shortlist: number;
}
