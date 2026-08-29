export interface ApplicationExplanation {
  application_id: string;
  status: string;
  eligibility_passed: boolean | null;
  eligibility_reasons: string[];
  final_score: number | null;
  semantic_score: number | null;
  skills_score: number | null;
  experience_score: number | null;
  matched_skills: string[];
  missing_skills: string[];
  assessment_status: string;
  assessment_score_pct: number | null;
  rejection_reasons: string[];
  rejection_note: string | null;
  narrative: string | null;
}

