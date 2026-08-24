export interface StudentProfile {
  id: string;
  email: string;
  name: string;
  department: string | null;
  batch_year: number | null;
  cgpa: number | null;
  phone: string | null;
  linkedin_url: string | null;
  github_url: string | null;
  portfolio_url: string | null;
  skills: string[];
  achievements: string[];
  certificates: string[];
  active_resume_id: string | null;
  profile_completeness_pct: number;
}

export interface StudentProfileUpdate {
  name?: string;
  department?: string;
  batch_year?: number;
  cgpa?: number;
  phone?: string;
  linkedin_url?: string;
  github_url?: string;
  portfolio_url?: string;
  skills?: string[];
  achievements?: string[];
  certificates?: string[];
}

export interface AutofillSuggestion {
  patch: StudentProfileUpdate;
  education: Record<string, string>[];
  experience: Record<string, string>[];
}