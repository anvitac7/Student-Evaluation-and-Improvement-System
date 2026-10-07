"""
Student Insights — cross-attempt focus areas + a study guide, aggregated over
a student's ENTIRE assessment history rather than a single attempt.

Why this exists alongside gap_analysis_service.py
-------------------------------------------------
`GapAnalysisService` answers "why did I score badly on THIS attempt" and is
correctly scoped to one attempt_id. But a student asking "where should I
focus?" is asking a different question — one that needs every attempt, every
weak skill, and the trend between them. Re-running gap analysis per attempt
and stitching the results in the frontend would mean N round-trips and a
duplicated aggregation on the client, so it's done here once, server-side.

Everything in the deterministic path is derived from data this project
already owns: AssessmentAttemptInDB.answers (is_correct, difficulty_at_time)
and KnowledgeStateInDB (mastery_pct, confidence, attempts_count, history).
No new data model, no new collection.

The LLM layer is strictly optional and additive
----------------------------------------------
`narrative` is the ONLY field that touches an LLM. If no provider is
configured (or the call fails), it is None and the endpoint still returns
the full deterministic payload. That is deliberate: the numbers must never
be hostage to an API key being present, and an LLM must never be able to
influence which skills get recommended — only how they're described. The
prompt is given pre-computed facts and is explicitly forbidden from
recomputing or contradicting them, matching the pattern already used in
gap_analysis_service.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.models.assessment import AttemptStatus
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ml.llm.client import llm_client
from app.ml.llm.exceptions import LLMUnavailableError
from app.ml.rag.knowledge_store import KnowledgeStore
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.attempt_repository import AttemptRepository
from app.repositories.knowledge_state_repository import KnowledgeStateRepository
from app.repositories.profile_repositories import StudentRepository
from app.repositories.question_repository import QuestionRepository

logger = logging.getLogger(__name__)

# A skill counts as a "focus area" below this mastery percentage. Matches
# gap_analysis_service.WEAK_MASTERY_THRESHOLD so a student doesn't see one
# threshold on the results page and a different one here.
WEAK_MASTERY_THRESHOLD = 50.0

# Below this, a skill is critical rather than merely weak.
CRITICAL_MASTERY_THRESHOLD = 35.0

# Cap on how many questions the study guide surfaces. Long enough to be a
# real revision plan, short enough to be finishable in one sitting.
STUDY_GUIDE_MAX_ITEMS = 10

# Highest mistake-count-per-attempt first, so a skill missed three times
# across three attempts outranks one missed once.
_FOCUS_WEIGHT_ERROR_RATE = 2.0
_FOCUS_WEIGHT_MASTERY = 1.0

_SYSTEM_PROMPT = (
    "You are an academic coach writing a personalised revision plan for a "
    "student, based on their adaptive assessment history. You will be given "
    "already-computed facts: per skill, their mastery percentage (computed "
    "by the knowledge-tracing system — do NOT recompute, round, or contradict "
    "it), how many times they got questions on it wrong, and the most "
    "recently missed questions verbatim.\n\n"
    "Write 150-220 words covering, in order: (1) the single highest-priority "
    "skill to fix and why it's first, (2) the next one or two, (3) a concrete "
    "study routine they can follow this week.\n\n"
    "Rules: never invent a skill, question, or fact that is not in the data "
    "given to you; never state a mastery number different from the one "
    "provided; be specific and encouraging, not generic advice. If a fact "
    "says a skill has high mastery, do not list it as needing work."
)

_FALLBACK_SYSTEM_PROMPT = (
    "You are an academic coach writing a short revision plan for a student "
    "based on their assessment history. Given per-skill mastery percentages "
    "and their most-missed questions, write 120-180 words on what to focus "
    "on first and a concrete study routine. Only use facts provided; never "
    "invent skills or numbers."
)


@dataclass
class SkillFocus:
    """One skill's standing across the student's whole history."""

    skill: str
    mastery_pct: float
    wrong_count: int
    attempts_touched: int          # how many attempts had a question on this skill
    times_seen: int                # total questions seen on this skill
    priority_score: float          # higher = study this sooner
    severity: str                  # "critical" | "weak" | "watch" | "ok"
    trend: str                     # "improving" | "declining" | "steady" | "unknown"
    last_missed_at: datetime | None = None
    example_question_ids: list[str] = field(default_factory=list)


@dataclass
class StudyGuideItem:
    """One concrete revision item — a question the student actually got wrong."""

    question_id: str
    skill: str
    difficulty: str
    question_type: str
    text: str
    your_answer: str | None
    correct_answer: str | None
    missed_count: int              # how many separate times they got this wrong


@dataclass
class InsightsResult:
    total_attempts: int
    total_questions_answered: int
    overall_accuracy_pct: float
    average_mastery_pct: float | None
    focus_areas: list[SkillFocus]
    strengths: list[SkillFocus]
    study_guide: list[StudyGuideItem]
    narrative: str | None = None   # None whenever the LLM is unavailable


class StudentInsightsService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.attempts = AttemptRepository(db)
        self.assessments = AssessmentRepository(db)
        self.knowledge_states = KnowledgeStateRepository(db)
        self.knowledge_store = KnowledgeStore(db)
        self.students = StudentRepository(db)
        self.questions = QuestionRepository(db)

    async def _resolve_student_id(self, student_user_id: str) -> str:
        """Attempts and knowledge states are keyed by the STUDENT PROFILE's
        own _id, never the auth user id from the JWT — the same ID-space
        convention every other student-referencing collection follows. See
        AssessmentService._resolve_student_id and the bug this caused once
        already (documented in PROJECT_PROGRESS.md, Phase 10)."""
        student = await self.students.get_by_user_id(student_user_id)
        if not student:
            raise ValueError("Student profile not found for this user")
        return str(student.id)

    # ------------------------------------------------------------------
    # aggregation
    # ------------------------------------------------------------------
    async def build(self, student_user_id: str) -> InsightsResult:
        student_id = await self._resolve_student_id(student_user_id)

        # Only SUBMITTED attempts count toward trends. An in-progress attempt
        # has a partial answer set, so including it would understate accuracy
        # and invent mastery movement for skills they haven't finished yet.
        raw_attempts = await self.attempts.get_for_student(student_id)
        submitted = [a for a in raw_attempts if a.status == AttemptStatus.SUBMITTED]

        states = await self.knowledge_states.get_all_for_student(student_id)
        mastery_by_skill = {s.skill_tag: s for s in states}

        # Per-skill tallies across every submitted attempt.
        wrong_by_skill: dict[str, int] = {}
        seen_by_skill: dict[str, int] = {}
        attempts_touched: dict[str, set[str]] = {}
        last_missed_at: dict[str, datetime] = {}

        # question_id -> how many separate times it was answered wrong, plus
        # the most recent wrong response. Keying on question_id (not skill)
        # is what lets the study guide surface the actual specific questions
        # rather than a vague "review Python".
        miss_count_by_question: dict[str, int] = {}
        latest_wrong_response: dict[str, str] = {}
        latest_wrong_at: dict[str, datetime] = {}

        total_answered = 0
        graded_correct = 0

        for attempt in submitted:
            for answer in attempt.answers:
                question = await self.questions.get_by_id(answer.question_id)
                if not question:
                    continue

                for tag in question.skill_tags:
                    seen_by_skill[tag] = seen_by_skill.get(tag, 0) + 1
                    attempts_touched.setdefault(tag, set()).add(str(attempt.id))

                    if answer.is_correct is False:
                        wrong_by_skill[tag] = wrong_by_skill.get(tag, 0) + 1
                        prior = last_missed_at.get(tag)
                        if prior is None or attempt.started_at > prior:
                            last_missed_at[tag] = attempt.started_at

                # Only an explicit False counts as wrong. None means an
                # ungraded descriptive answer — neither right nor wrong, so
                # it must not drag accuracy down.
                if answer.is_correct is None:
                    continue

                total_answered += 1
                if answer.is_correct:
                    graded_correct += 1
                    continue

                qid = answer.question_id
                miss_count_by_question[qid] = miss_count_by_question.get(qid, 0) + 1
                latest_wrong_response[qid] = answer.response
                if qid not in latest_wrong_at or attempt.started_at > latest_wrong_at[qid]:
                    latest_wrong_at[qid] = attempt.started_at

        focus_areas, strengths = await self._rank_skills(
            mastery_by_skill=mastery_by_skill,
            wrong_by_skill=wrong_by_skill,
            seen_by_skill=seen_by_skill,
            attempts_touched=attempts_touched,
            last_missed_at=last_missed_at,
        )

        study_guide = await self._build_study_guide(
            miss_count_by_question=miss_count_by_question,
            latest_wrong_response=latest_wrong_response,
            focus_skill_order=[f.skill for f in focus_areas],
        )

        average_mastery = (
            round(sum(s.mastery_pct for s in states) / len(states), 1) if states else None
        )
        overall_accuracy = (
            round(100 * graded_correct / total_answered, 1) if total_answered else 0.0
        )

        result = InsightsResult(
            total_attempts=len(submitted),
            total_questions_answered=total_answered,
            overall_accuracy_pct=overall_accuracy,
            average_mastery_pct=average_mastery,
            focus_areas=focus_areas,
            strengths=strengths,
            study_guide=study_guide,
        )

        result.narrative = await self._maybe_narrate(result)
        return result

    async def _rank_skills(
        self,
        *,
        mastery_by_skill: dict,
        wrong_by_skill: dict[str, int],
        seen_by_skill: dict[str, int],
        attempts_touched: dict[str, set[str]],
        last_missed_at: dict[str, datetime],
    ) -> tuple[list[SkillFocus], list[SkillFocus]]:
        # Union of both sources: a skill can appear in knowledge states
        # without being missed in any attempt the question bank still
        # holds, and vice versa.
        all_skills = set(mastery_by_skill) | set(seen_by_skill)

        focus: list[SkillFocus] = []
        strengths: list[SkillFocus] = []

        for skill in all_skills:
            state = mastery_by_skill.get(skill)
            mastery = state.mastery_pct if state else 50.0  # neutral default, same as knowledge tracing's
            wrong = wrong_by_skill.get(skill, 0)
            seen = seen_by_skill.get(skill, 0)

            error_rate = (wrong / seen) if seen else 0.0
            # Priority blends how often they're wrong with how low mastery
            # is. Mastery deficit dominates; error rate breaks ties.
            priority = (100 - mastery) + (_FOCUS_WEIGHT_ERROR_RATE * 100 * error_rate)

            item = SkillFocus(
                skill=skill,
                mastery_pct=round(mastery, 1),
                wrong_count=wrong,
                attempts_touched=len(attempts_touched.get(skill, set())),
                times_seen=seen,
                priority_score=round(priority, 1),
                severity=self._severity(mastery, wrong, seen),
                trend=self._trend(state),
                last_missed_at=last_missed_at.get(skill),
            )

            if mastery < WEAK_MASTERY_THRESHOLD:
                focus.append(item)
            elif mastery >= 70 and wrong == 0 and seen > 0:
                strengths.append(item)

        focus.sort(key=lambda s: s.priority_score, reverse=True)
        strengths.sort(key=lambda s: s.mastery_pct, reverse=True)
        return focus, strengths

    @staticmethod
    def _severity(mastery: float, wrong: int, seen: int) -> str:
        if mastery < CRITICAL_MASTERY_THRESHOLD and wrong > 0:
            return "critical"
        if mastery < WEAK_MASTERY_THRESHOLD:
            return "weak"
        if wrong > 0:
            return "watch"
        return "ok"

    @staticmethod
    def _trend(state) -> str:
        """Direction over the knowledge-state history the tracer has been
        appending. Fewer than 2 points means there's no trend to claim —
        reporting "steady" there would be inventing information."""
        history = list(getattr(state, "history", []) or []) if state else []
        if len(history) < 2:
            return "unknown"

        points = [
            h.get("mastery_pct") if isinstance(h, dict) else getattr(h, "mastery_pct", None)
            for h in history
        ]
        points = [p for p in points if isinstance(p, (int, float))]
        if len(points) < 2:
            return "unknown"

        delta = points[-1] - points[0]
        # 5 points is noise on a percentage scale, not a real trend.
        if delta > 5:
            return "improving"
        if delta < -5:
            return "declining"
        return "steady"

    async def _build_study_guide(
        self,
        *,
        miss_count_by_question: dict[str, int],
        latest_wrong_response: dict[str, str],
        focus_skill_order: list[str],
    ) -> list[StudyGuideItem]:
        if not miss_count_by_question:
            return []

        valid_ids = [ObjectId(qid) for qid in miss_count_by_question if _is_objectid(qid)]
        if not valid_ids:
            return []

        questions = await self.questions.find_many(
            {"_id": {"$in": valid_ids}}, limit=STUDY_GUIDE_MAX_ITEMS * 3
        )
        by_id = {str(q.id): q for q in questions}

        items: list[StudyGuideItem] = []
        for qid, miss_count in miss_count_by_question.items():
            question = by_id.get(qid)
            if not question:
                continue
            items.append(
                StudyGuideItem(
                    question_id=qid,
                    skill=(question.skill_tags or ["Untagged"])[0],
                    difficulty=str(getattr(question.difficulty, "value", question.difficulty)),
                    question_type=str(getattr(question.type, "value", question.type)),
                    text=question.text,
                    your_answer=latest_wrong_response.get(qid) or None,
                    correct_answer=question.correct_answer,
                    missed_count=miss_count,
                )
            )

        # Order by the focus-area ranking so the guide leads with the skill
        # the page itself is telling them to fix first, then by how often
        # they missed it.
        rank = {skill: i for i, skill in enumerate(focus_skill_order)}
        items.sort(key=lambda i: (rank.get(i.skill, len(rank)), -i.missed_count))
        return items[:STUDY_GUIDE_MAX_ITEMS]

    # ------------------------------------------------------------------
    # optional LLM narrative
    # ------------------------------------------------------------------
    async def _maybe_narrate(self, result: InsightsResult) -> str | None:
        """Best-effort narrative. Returns None on ANY failure — a missing
        API key, a provider outage, a malformed response. The deterministic
        payload is already complete without this, so there is nothing to
        surface as an error to the caller."""
        if not result.focus_areas and not result.study_guide:
            return None  # nothing to say; don't spend a call saying nothing

        # Prefer RAG grounding when embeddings are available; fall back to
        # facts-only when they aren't (currently always the case locally,
        # since Ollama isn't installed — see PROJECT_PROGRESS.md).
        chunks = []
        try:
            chunks = await self.knowledge_store.retrieve(
                query_skills=[f.skill for f in result.focus_areas[:5]],
                chunk_types=["syllabus_note", "question_explanation"],
                top_k=5,
            )
        except Exception:  # noqa: BLE001 - retrieval is strictly optional
            logger.warning("RAG retrieval failed for student insights — continuing without it.", exc_info=True)

        facts = {
            "overall_accuracy_pct": result.overall_accuracy_pct,
            "attempts_completed": result.total_attempts,
            "average_mastery_pct": result.average_mastery_pct,
            "focus_areas": [
                {
                    "skill": f.skill,
                    "mastery_pct": f.mastery_pct,
                    "wrong_count": f.wrong_count,
                    "trend": f.trend,
                }
                for f in result.focus_areas[:6]
            ],
            "recently_missed_questions": [
                {"skill": i.skill, "question": i.text[:220], "times_missed": i.missed_count}
                for i in result.study_guide[:6]
            ],
            "reference_material": [c.text for c in chunks],
        }

        system_prompt = _SYSTEM_PROMPT if chunks else _FALLBACK_SYSTEM_PROMPT
        try:
            return await llm_client.generate_text_async(system_prompt, str(facts), thinking=True)
        except LLMUnavailableError:
            logger.info("LLM unavailable for student insights — returning deterministic payload only.")
            return None


def _is_objectid(value: str) -> bool:
    try:
        ObjectId(value)
        return True
    except Exception:  # noqa: BLE001
        return False