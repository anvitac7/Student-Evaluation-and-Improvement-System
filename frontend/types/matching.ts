export interface MatchScoreBreakdown {
  final_score: number;
  semantic_score: number;
  skills_score: number;
  experience_score: number;
  matched_skills: string[];
  missing_skills: string[];
}

export interface DriveMatchScore extends MatchScoreBreakdown {
  drive_id: string;
}

export interface RecommendedDrive extends MatchScoreBreakdown {
  drive_id: string;
  job_title: string;
  company_name: string;
  location: string | null;
  package: string | null;
}

export interface RankedApplicant extends MatchScoreBreakdown {
  application_id: string;
  student_id: string;
  student_name: string;
  student_department?: string | null;
  student_cgpa?: number | null;
  resume_id: string;
  resume_filename?: string | null;
  status: string;
  eligibility_passed?: boolean | null;
  eligibility_reasons?: string[];
  assessment_status?: string;
  assessment_score_pct?: number | null;
  rejection_reasons?: string[];
  rejection_note?: string | null;
  decision_at?: string | null;
  applied_at?: string | null;
}
