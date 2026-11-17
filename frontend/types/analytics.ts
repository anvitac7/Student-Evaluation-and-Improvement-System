export interface ApplicationStatusBreakdown {
  applied: number;
  shortlisted: number;
  rejected: number;
  selected: number;
}

export interface DriveFunnel {
  drive_id: string;
  job_title: string;
  company_name: string;
  status: string;
  total_applications: number;
  breakdown: ApplicationStatusBreakdown;
  /** Assessment linkage + per-drive participation (backend-computed). */
  required_assessment_id: string | null;
  assessment_title: string | null;
  /** Unique students who started the drive assessment. */
  participant_count: number;
  /** Unique students with a submitted attempt. */
  submitted_participant_count: number;
}

export interface DriveAssessmentRankingEntry {
  rank: number;
  student_id: string;
  student_name: string;
  department: string | null;
  cgpa: number | null;
  score_pct: number;
  submitted_at: string;
}

export interface DriveAssessmentRanking {
  drive_id: string;
  job_title: string;
  company_name: string;
  assessment_id: string;
  assessment_title: string;
  entries: DriveAssessmentRankingEntry[];
}

export interface TpoAnalytics {
  total_drives: number;
  open_drives: number;
  closed_drives: number;
  total_applications: number;
  breakdown: ApplicationStatusBreakdown;
  selection_rate_pct: number;
  drives: DriveFunnel[];
}

export interface DriveApplicantEntry {
  application_id: string;
  student_id: string;
  student_name: string;
  department: string | null;
  batch_year: number | null;
  /** Application status: applied | shortlisted | rejected | selected. */
  status: string;
  applied_at: string;
}

export interface DriveApplicantsResponse {
  drive_id: string;
  job_title: string;
  company_name: string;
  total: number;
  page: number;
  limit: number;
  entries: DriveApplicantEntry[];
}

export interface DriveParticipantEntry {
  student_id: string;
  student_name: string;
  department: string | null;
  batch_year: number | null;
  attempt_id: string;
  /** "in_progress" | "submitted" — one row per student, best attempt shown. */
  attempt_status: string;
  /** null for an in-progress attempt. */
  score_pct: number | null;
  started_at: string;
  submitted_at: string | null;
}

export interface DriveParticipantsResponse {
  drive_id: string;
  job_title: string;
  company_name: string;
  assessment_id: string | null;
  assessment_title: string | null;
  total: number;
  page: number;
  limit: number;
  entries: DriveParticipantEntry[];
}

export interface SkillMasteryOverview {
  skill_tag: string;
  avg_mastery_pct: number;
  student_count: number;
}

export interface AdminAnalytics {
  total_students: number;
  total_tpos: number;
  total_drives: number;
  open_drives: number;
  closed_drives: number;
  total_applications: number;
  application_breakdown: ApplicationStatusBreakdown;
  placed_students: number;
  placement_rate_pct: number;
  total_categories: number;
  total_questions: number;
  total_assessments: number;
  total_attempts: number;
  submitted_attempts: number;
  average_score_pct: number;
  skill_mastery_overview: SkillMasteryOverview[];
}
