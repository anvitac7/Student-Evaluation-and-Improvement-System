export type DifficultyLevel = "easy" | "medium" | "hard";
export type QuestionType = "mcq" | "coding" | "descriptive";
export type AttemptStatus = "in_progress" | "submitted";
export type AssessmentType = "practice" | "drive";
export type CodingLanguage = "python" | "javascript";

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
  type?: AssessmentType;
}

export interface AssessmentResponse {
  id: string;
  title: string;
  category_ids: string[];
  question_pool_size: number;
  time_limit_sec: number;
  anti_cheat_config: AntiCheatConfig;
  type: AssessmentType;
  drive_id: string | null;
}

export interface QuestionStudentView {
  id: string;
  difficulty: DifficultyLevel;
  type: QuestionType;
  text: string;
  options: string[];
  marks: number;
  /** Coding-only. Only non-hidden test cases are exposed as samples. */
  language: CodingLanguage | null;
  starter_code: string | null;
  visible_test_cases: QuestionTestCase[];
}

/** One stdin/stdout test case attached to a coding question (admin view). */
export interface QuestionTestCase {
  name?: string | null;
  input: string;
  expected_output: string;
  is_hidden: boolean;
}

export interface CodeTestCaseResult {
  index: number;
  name: string | null;
  is_hidden: boolean;
  passed: boolean;
  status: string;
  input: string | null;
  expected_output: string | null;
  actual_output: string | null;
  stderr: string | null;
  runtime_ms: number | null;
}

export interface CodeRunSummary {
  passed: number;
  total: number;
  all_passed: boolean;
  status: string;
  results: CodeTestCaseResult[];
  error: string | null;
}

export interface StartAttemptResponse {
  attempt_id: string;
  session_token: string;
  time_limit_sec: number;
  time_remaining_sec: number;
  anti_cheat_config: AntiCheatConfig;
  next_question: QuestionStudentView | null;
}

export interface SubmitAnswerResponse {
  is_correct: boolean | null;
  marks_awarded: number;
  next_question: QuestionStudentView | null;
  attempt_status: AttemptStatus;
  code_result: CodeRunSummary | null;
}

export interface FinishAttemptResponse {
  attempt_id: string;
  status: AttemptStatus;
  questions_answered: number;
  total_marks: number;
  max_possible_marks: number;
  submitted_at: string | null;
}

export interface ViolationReportResponse {
  violation_count: number;
  max_violations: number;
  attempt_status: AttemptStatus;
  auto_submitted: boolean;
}

export interface AttemptAnswerDetail {
  question_id: string;
  type: QuestionType | null;
  text: string;
  response: string;
  is_correct: boolean | null;
  marks_awarded: number;
  max_marks: number;
  code_result: CodeRunSummary | null;
}

export interface AttemptResultResponse {
  attempt_id: string;
  status: AttemptStatus;
  total_marks: number;
  max_possible_marks: number;
  questions_answered: number;
  started_at: string;
  submitted_at: string | null;
  answers: AttemptAnswerDetail[];
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
