import type { CodingLanguage, DifficultyLevel, QuestionTestCase, QuestionType } from "@/types/assessment";

export interface CategoryResponse {
  id: string;
  name: string;
  parent_category_id: string | null;
}

export interface CategoryCreateRequest {
  name: string;
  parent_category_id?: string;
}

export interface QuestionAdminResponse {
  id: string;
  category_id: string;
  skill_tags: string[];
  difficulty: DifficultyLevel;
  type: QuestionType;
  text: string;
  options: string[];
  correct_answer: string | null;
  language: CodingLanguage | null;
  starter_code: string | null;
  test_cases: QuestionTestCase[];
  marks: number;
  company_tags: string[];
}

export interface QuestionCreateRequest {
  category_id: string;
  skill_tags: string[];
  difficulty: DifficultyLevel;
  type: QuestionType;
  text: string;
  options: string[];
  correct_answer?: string;
  language?: CodingLanguage;
  starter_code?: string;
  test_cases?: QuestionTestCase[];
  company_tags: string[];
}

export interface QuestionUpdateRequest {
  category_id?: string;
  skill_tags?: string[];
  difficulty?: DifficultyLevel;
  type?: QuestionType;
  text?: string;
  options?: string[];
  correct_answer?: string;
  language?: CodingLanguage;
  starter_code?: string;
  test_cases?: QuestionTestCase[];
  company_tags?: string[];
}
