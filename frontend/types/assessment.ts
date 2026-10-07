export type DifficultyLevel = "easy" | "medium" | "hard";
export type QuestionType = "mcq" | "coding" | "descriptive";
export type AttemptStatus = "in_progress" | "submitted";

export interface AntiCheatConfig {
  max_violations?: number;
  require_fullscreen?: boolean;
  [key: string]: unknown;
}

export interface AssessmentCreateRequest {
  title: string;
  category_ids: string[];
  question_pool_size: number;
  time_limit_sec: number;
  max_violations: number;
  require_fullscreen: boolean;
}

export interface AssessmentResponse {
  id: string;
  title: string;
  category_ids: string[];
  question_pool_size: number;
  time_limit_sec: number;
  anti_cheat_config: AntiCheatConfig;
}

export interface QuestionStudentView {
  id: string;
  difficulty: DifficultyLevel;
  type: QuestionType;
  text: string;
  options: string[];
  marks: number;
}

export interface StartAttemptResponse {
  attempt_id: string;
  session_token: string;
  time_limit_sec: number;
  anti_cheat_config: AntiCheatConfig;
  next_question: QuestionStudentView | null;
}

export interface SubmitAnswerResponse {
  is_correct: boolean | null;
  marks_awarded: number;
  next_question: QuestionStudentView | null;
  attempt_status: AttemptStatus;
}

export interface ViolationReportResponse {
  violation_count: number;
  max_violations: number;
  attempt_status: AttemptStatus;
  auto_submitted: boolean;
}

export interface AttemptResultResponse {
  attempt_id: string;
  status: AttemptStatus;
  total_marks: number;
  max_possible_marks: number;
  questions_answered: number;
  started_at: string;
  submitted_at: string | null;
}

export interface KnowledgeStateResponse {
  skill_tag: string;
  mastery_pct: number;
  confidence: number;
  attempts_count: number;
}

/** One skill's standing across the student's whole assessment history. */
export interface SkillFocus {
  skill: string;
  mastery_pct: number;
  wrong_count: number;
  attempts_touched: number;
  times_seen: number;
  priority_score: number;
  severity: "critical" | "weak" | "watch" | "ok";
  trend: "improving" | "declining" | "steady" | "unknown";
  last_missed_at: string | null;
}

/** One concrete revision item — a question the student actually got wrong. */
export interface StudyGuideItem {
  question_id: string;
  skill: string;
  difficulty: string;
  question_type: string;
  text: string;
  your_answer: string | null;
  correct_answer: string | null;
  missed_count: number;
}

export interface StudentInsightsResponse {
  total_attempts: number;
  total_questions_answered: number;
  overall_accuracy_pct: number;
  average_mastery_pct: number | null;
  focus_areas: SkillFocus[];
  strengths: SkillFocus[];
  study_guide: StudyGuideItem[];
  /** Null when no LLM provider is configured — the rest of the payload is
   *  fully usable without it. */
  narrative: string | null;
}
