"""TPO skill gap analysis (Phase 8).

Answers one question: which industry-demanded skills do our students lack?

Three independent data sources, never mixed:

1. **Industry demand** — the existing Market Insights dataset
   (``job_market_postings`` + ``market_skill_catalog``), aggregated with the
   EXACT same filter semantics, projection and window math as the market
   dashboard (``market_analytics_service``). The dataset is mock data; every
   response embeds the shared ``MarketMeta`` disclaimer so that never hides.

2. **Assessment-demonstrated skills** — recomputed from attempts, NOT read
   from ``knowledge_states``. Knowledge tracing is updated for PRACTICE
   attempts too (see assessment_service.submit_answer), so mastery records
   cannot tell drive evidence from practice evidence. Instead, evidence is
   rebuilt per skill from submitted attempts via the only permitted chain:

       Placement Drive.required_assessment_id -> Attempt -> answers -> Question.skill_tags

   Only attempts on assessments referenced by a drive's
   ``required_assessment_id`` are ever fetched, and each attempt is kept only
   when its student applied to at least one drive linking that assessment
   (a drive assessment can only be started through an application, so in the
   normal case this changes nothing; it closes the two-drives-share-one-
   assessment hole the same way the per-drive analytics does). Practice
   assessments are structurally excluded: nothing that is not referenced by a
   ``required_assessment_id`` is ever queried. In-progress attempts are never
   fetched — only SUBMITTED attempts can demonstrate anything.

   Per student per skill: ``accuracy = correct / graded answers`` over ALL
   eligible attempts combined (retakes contribute every submitted attempt
   once — per attempt, deduped by attempt id, so two drives sharing one
   assessment never double-count one attempt). With fewer graded answers
   than ``MIN_GRADED_ANSWERS`` the evidence is ``insufficient`` — never
   classified, never claimed as proficiency. Thresholds mirror the knowledge
   tracing constants (75 strong / 50 weak) so "demonstrated" means the same
   thing everywhere in the app.

3. **Self-reported skills** — the structured student profile ``skills`` list
   plus the ACTIVE resume's extracted ``skill_set``. Normalized through the
   market skill catalog (name + aliases) with a fallback through the existing
   resume-parsing vocabulary normalizer. A self-reported skill is NEVER
   counted as demonstrated proficiency; both perspectives are always shown
   side by side (demonstrated gap vs reported gap).

Skill identity: catalog name when the skill is cataloged, otherwise the
posting skill name with a slugified id (same fallback rule as the market
dashboard). Question skill tags and self-reported skills that resolve to
neither are excluded from the gap rows and listed in the response metadata
(never silently dropped).

Priority score (transparent, NOT an industry standard):

    priority = 0.5 * demand_pct + 0.4 * gap_pct + 0.1 * growth_component
    growth_component = (clamp(growth, -100, +100) + 100) / 2   when comparable
    (no comparable growth) priority = (0.5*demand + 0.4*gap) / 0.9

    high >= 60, medium >= 40, else low.

Weights are demo-dataset assumptions and are exposed in the response meta so
the UI can label them as such.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.analytics import (
    AssessmentEvidenceClass,
    MostDemandedMissingSkill,
    PriorityClass,
    RisingDemandSkill,
    SkillCompanyDemand,
    SkillGapAnalysisResponse,
    SkillGapEntry,
    SkillGapMeta,
    SkillGapStudentsResponse,
    SkillGapStudentEntry,
    SkillGapSummary,
    SkillGapThresholds,
    SkillJobFamilyDemand,
    SkillYearDemand,
    StudentEvidenceSource,
)
from app.models.assessment import AttemptStatus
from app.models.market import MARKET_IS_PARTIAL_YEAR, MARKET_LATEST_YEAR
from app.ml.parsing.skill_normalizer import normalize_skill
from app.repositories.application_repository import ApplicationRepository
from app.repositories.attempt_repository import AttemptRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.job_posting_repository import (
    JobMarketPostingRepository,
    MarketSkillCatalogRepository,
)
from app.repositories.profile_repositories import StudentRepository
from app.repositories.question_repository import QuestionRepository
from app.repositories.resume_repository import ResumeRepository
from app.services.analytics_service import _ANALYTICS_FETCH_LIMIT, _name_search_regex
from app.services.market_analytics_service import (
    _MAX_CATALOG_ENTRIES,
    _MAX_POSTINGS,
    _POSTING_PROJECTION,
    MarketAnalyticsService,
    MarketQuery,
    _aggregate_postings,
    _build_meta,
    _growth_pct,
    _identity_for,
    _pct,
    _slugify,
    _window_count,
)

logger = logging.getLogger(__name__)

# --- Documented classification thresholds (mirrors knowledge tracing) ------
MIN_GRADED_ANSWERS = 3
DEMONSTRATED_MIN_PCT = 75.0
DEVELOPING_MIN_PCT = 50.0

# --- Documented priority weights -------------------------------------------
PRIORITY_WEIGHTS = {"demand": 0.5, "gap": 0.4, "growth": 0.1}
PRIORITY_CLASS_THRESHOLDS = {"high": 60.0, "medium": 40.0}

# Detail caps (bounded responses)
TOP_PER_SKILL = 10
MAX_UNMAPPED_LISTED = 25
RISING_DEMAND_LIMIT = 3

_NAME_SEARCH_STUDENT_CAP = 1000


class SkillGapError(Exception):
    """Raised by skill-gap endpoints; carries an HTTP status code."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class _Tally:
    answered: int = 0
    correct: int = 0

    def add(self, is_correct: bool) -> None:
        self.answered += 1
        if is_correct:
            self.correct += 1


@dataclass
class _StudentEvidence:
    skills: dict[str, _Tally] = field(default_factory=dict)
    # skill -> assessment_title -> [answered, correct, attempts_used]
    assessments: dict[str, dict[str, list[int]]] = field(default_factory=dict)
    submitted_attempts_used: int = 0


@dataclass
class _CatalogResolver:
    """Maps free-form question skill tags and self-reported skills onto the
    demand rows' skill names (catalog name, or posting skill name when the
    skill is not cataloged). Unresolvable tags are reported, never guessed."""

    by_name: dict[str, str]
    by_alias: dict[str, str]
    posting_names: set[str]

    def resolve(self, raw: str) -> str | None:
        candidates = (raw.strip(), normalize_skill(raw.strip()))
        for candidate in candidates:
            if not candidate:
                continue
            key = candidate.casefold()
            name = self.by_name.get(key) or self.by_alias.get(key)
            if name is not None:
                return name
            for posting_name in self.posting_names:
                if posting_name.casefold() == key:
                    return posting_name
        return None


def _classify_accuracy(accuracy_pct: float) -> AssessmentEvidenceClass:
    """Documented thresholds (see module docstring). Requires
    ``MIN_GRADED_ANSWERS`` graded answers — enforced by the caller."""
    if accuracy_pct >= DEMONSTRATED_MIN_PCT:
        return "demonstrated"
    if accuracy_pct >= DEVELOPING_MIN_PCT:
        return "developing"
    return "not_demonstrated"


def _priority_score(
    demand_pct: float, gap_pct: float, comparable: bool, growth_pct: float | None
) -> float:
    if comparable and growth_pct is not None:
        clamped = max(-100.0, min(100.0, growth_pct))
        growth_component = (clamped + 100.0) / 2.0
        return round(
            PRIORITY_WEIGHTS["demand"] * demand_pct
            + PRIORITY_WEIGHTS["gap"] * gap_pct
            + PRIORITY_WEIGHTS["growth"] * growth_component,
            1,
        )
    # No comparable historical growth: re-weight the available dimensions
    # instead of pretending the growth term is zero.
    weights = PRIORITY_WEIGHTS["demand"] + PRIORITY_WEIGHTS["gap"]
    return round(
        (PRIORITY_WEIGHTS["demand"] * demand_pct + PRIORITY_WEIGHTS["gap"] * gap_pct) / weights,
        1,
    )


def _priority_class(score: float) -> PriorityClass:
    if score >= PRIORITY_CLASS_THRESHOLDS["high"]:
        return "high"
    if score >= PRIORITY_CLASS_THRESHOLDS["medium"]:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Aggregation context (built once per request, reused by both endpoints)
# ---------------------------------------------------------------------------


@dataclass
class _Context:
    students: list
    resolver: _CatalogResolver
    reported: dict[str, dict[str, set[str]]]  # student_id -> skill -> {"profile"|"resume"}
    evidence: dict[str, _StudentEvidence]  # student_id -> assessment evidence
    eligible_drive_count: int
    eligible_assessment_count: int
    submitted_attempt_count: int
    unmapped_tags: set[str]
    unmapped_self_reported: set[str]


class SkillGapService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.drives = PlacementDriveRepository(db)
        self.applications = ApplicationRepository(db)
        self.assessments = AssessmentRepository(db)
        self.attempts = AttemptRepository(db)
        self.questions = QuestionRepository(db)
        self.students = StudentRepository(db)
        self.resumes = ResumeRepository(db)
        self.postings = JobMarketPostingRepository(db)
        self.catalog = MarketSkillCatalogRepository(db)
        self.market = MarketAnalyticsService(db)

    # -- Data loading -------------------------------------------------------

    async def _build_context(
        self,
        year_from: int | None,
        year_to: int | None,
        company: str | None,
        job_family: str | None,
        location: str | None,
        skill_category: str | None,
        technical_only: bool,
    ) -> tuple[_Context, dict[str, Any]]:
        """Load + aggregate everything both endpoints need.

        The market aggregate is part of the context (instead of a separate
        call) so the students endpoint can resolve ANY skill id the dashboard
        rows can produce — including skills that appear in postings but not
        in the catalog.
        """
        # --- 1. Industry demand (Market Insights dataset only) ---
        mongo_query = await self.market.build_posting_query(
            year_from, year_to, company, job_family, location
        )
        posting_rows = await self.postings.find_projected(
            mongo_query, _POSTING_PROJECTION, limit=_MAX_POSTINGS
        )
        catalog_docs = await self.catalog.find_many(limit=_MAX_CATALOG_ENTRIES)
        catalog_by_name = {doc.name: doc for doc in catalog_docs}
        agg = _aggregate_postings(
            posting_rows,
            catalog_by_name,
            MarketQuery(skill_category=skill_category, technical_only=technical_only),
        )

        # --- 2. Skill identity resolver (catalog + posting skill names) ---
        posting_names = set(agg.skill_totals.keys())
        by_name: dict[str, str] = {}
        by_alias: dict[str, str] = {}
        for doc in catalog_docs:
            by_name[doc.name.casefold()] = doc.name
            for alias in doc.aliases:
                by_alias.setdefault(alias.casefold(), doc.name)
        resolver = _CatalogResolver(by_name=by_name, by_alias=by_alias, posting_names=posting_names)

        # --- 3. Student population + self-reported skills ---
        students = await self.students.find_many({}, limit=_ANALYTICS_FETCH_LIMIT)
        reported: dict[str, dict[str, set[str]]] = {}
        unmapped_self_reported: set[str] = set()
        for student in students:
            via: dict[str, set[str]] = {}
            for raw_skill in student.skills or []:
                name = resolver.resolve(raw_skill)
                if name is None:
                    unmapped_self_reported.add(raw_skill)
                    continue
                via.setdefault(name, set()).add("profile")
            for raw_skill in await self._active_resume_skills(student.id):
                name = resolver.resolve(raw_skill)
                if name is None:
                    unmapped_self_reported.add(raw_skill)
                    continue
                via.setdefault(name, set()).add("resume")
            if via:
                reported[student.id] = via

        # --- 4. Eligible assessment evidence (drive chain only) ---
        drives = await self.drives.find_many({}, limit=_ANALYTICS_FETCH_LIMIT)
        applications = await self.applications.find_many({}, limit=_ANALYTICS_FETCH_LIMIT)
        applicant_ids_by_drive: dict[str, set[str]] = {}
        for application in applications:
            applicant_ids_by_drive.setdefault(str(application.drive_id), set()).add(
                application.student_id
            )

        # assessment_id -> every student who applied to a drive requiring it
        link_applicants: dict[str, set[str]] = {}
        eligible_drive_count = 0
        for drive in drives:
            if not drive.required_assessment_id:
                continue
            eligible_drive_count += 1
            assessment_key = str(drive.required_assessment_id)
            link_applicants.setdefault(assessment_key, set()).update(
                applicant_ids_by_drive.get(drive.id, set())
            )

        evidence: dict[str, _StudentEvidence] = {}
        submitted_attempt_count = 0
        eligible_assessment_count = len(link_applicants)
        unmapped_tags: set[str] = set()

        if link_applicants:
            attempts = await self.attempts.find_many(
                {"assessment_id": {"$in": sorted(link_applicants)}, "status": "submitted"},
                limit=_ANALYTICS_FETCH_LIMIT,
            )
            # One attempt belongs to one assessment; it may satisfy several
            # drive links (shared assessments) — dedupe by attempt id so a
            # single attempt's answers are never counted twice.
            unique_attempts = {attempt.id: attempt for attempt in attempts}
            question_ids = {
                answer.question_id
                for attempt in unique_attempts.values()
                for answer in attempt.answers
                if answer.question_id and ObjectId.is_valid(answer.question_id)
            }
            questions = await self.questions.find_many(
                {"_id": {"$in": [ObjectId(qid) for qid in question_ids]}},
                limit=_ANALYTICS_FETCH_LIMIT,
            ) if question_ids else []
            questions_by_id = {q.id: q for q in questions}

            assessment_docs = await self.assessments.find_many(
                {"_id": {"$in": [ObjectId(aid) for aid in link_applicants]}},
                limit=_ANALYTICS_FETCH_LIMIT,
            ) if link_applicants else []
            titles = {doc.id: doc.title for doc in assessment_docs}

            for attempt in unique_attempts.values():
                # Keep the attempt only when its student applied to at least
                # one drive linking THIS assessment (cross-drive isolation).
                allowed = link_applicants.get(str(attempt.assessment_id), set())
                if attempt.student_id not in allowed:
                    continue
                assessment_title = titles.get(str(attempt.assessment_id), "Drive assessment")
                student_evidence = evidence.setdefault(attempt.student_id, _StudentEvidence())
                student_evidence.submitted_attempts_used += 1
                submitted_attempt_count += 1
                # Collect this attempt's per-skill contribution first, then
                # merge it once per touched skill — attempts_used must count
                # ATTEMPTS, not individual answers.
                touched: dict[str, list[int]] = {}
                for answer in attempt.answers:
                    # Descriptive answers are ungraded (is_correct is None) —
                    # they can neither demonstrate nor refute a skill.
                    if answer.is_correct is None:
                        continue
                    question = questions_by_id.get(answer.question_id)
                    if not question or not question.skill_tags:
                        continue
                    for tag in question.skill_tags:
                        name = resolver.resolve(tag)
                        if name is None:
                            unmapped_tags.add(tag)
                            continue
                        tally = student_evidence.skills.setdefault(name, _Tally())
                        tally.add(bool(answer.is_correct))
                        bucket = touched.setdefault(name, [0, 0])
                        bucket[0] += 1
                        if answer.is_correct:
                            bucket[1] += 1
                for name, (answered, correct) in touched.items():
                    per_assessment = student_evidence.assessments.setdefault(
                        name, {}
                    ).setdefault(assessment_title, [0, 0, 0])
                    per_assessment[0] += answered
                    per_assessment[1] += correct
                    per_assessment[2] += 1

        context = _Context(
            students=students,
            resolver=resolver,
            reported=reported,
            evidence=evidence,
            eligible_drive_count=eligible_drive_count,
            eligible_assessment_count=eligible_assessment_count,
            submitted_attempt_count=submitted_attempt_count,
            unmapped_tags=unmapped_tags,
            unmapped_self_reported=unmapped_self_reported,
        )
        market_ctx = {
            "rows": posting_rows,
            "catalog_by_name": catalog_by_name,
            "agg": agg,
        }
        return context, market_ctx

    async def _active_resume_skills(self, student_id: str) -> list[str]:
        """The ACTIVE resume's extracted skill_set for one student — part of
        the per-student loop, but one indexed query each; students without a
        resume simply return nothing (never an error)."""
        resume = await self.resumes.get_active_for_student(student_id)
        if not resume:
            return []
        return resume.skill_set or []

    # -- Main dashboard endpoint --------------------------------------------

    async def get_skill_gaps(
        self,
        year_from: int | None,
        year_to: int | None,
        company: str | None,
        job_family: str | None,
        location: str | None,
        skill_category: str | None,
        technical_only: bool,
        sort: str,
    ) -> SkillGapAnalysisResponse:
        context, market_ctx = await self._build_context(
            year_from, year_to, company, job_family, location, skill_category, technical_only
        )
        agg = market_ctx["agg"]
        catalog_by_name = market_ctx["catalog_by_name"]
        posting_rows = market_ctx["rows"]
        population = len(context.students)

        # Per-student flags used by the summary.
        demonstrated_any: set[str] = set()
        assessed_any: set[str] = set()

        entries: list[SkillGapEntry] = []
        for name in agg.skill_totals:
            entry, skill_demonstrated, skill_attempted = self._build_entry(
                name, agg, catalog_by_name, context, population
            )
            entries.append(entry)
            demonstrated_any |= skill_demonstrated
            assessed_any |= skill_attempted

        if sort == "demand":
            entries.sort(key=lambda e: (-e.demand_pct, -e.posting_count, e.name))
        elif sort == "gap":
            entries.sort(key=lambda e: (-e.gap_pct, -e.demand_pct, e.name))
        else:  # "priority"
            entries.sort(key=lambda e: (-e.priority_score, -e.demand_pct, e.name))

        students_with_reported = sum(1 for via in context.reported.values() if via)

        most_demanded_missing: MostDemandedMissingSkill | None = None
        missing = [e for e in entries if e.students_demonstrated == 0]
        if missing:
            best = min(missing, key=lambda e: (-e.demand_pct, -e.posting_count, e.name))
            most_demanded_missing = MostDemandedMissingSkill(
                skill_id=best.skill_id,
                name=best.name,
                posting_count=best.posting_count,
                demand_pct=best.demand_pct,
            )

        rising = [
            RisingDemandSkill(
                skill_id=e.skill_id,
                name=e.name,
                latest_growth_pct=e.latest_growth_pct,
                demand_pct=e.demand_pct,
                demonstrated_pct=e.demonstrated_pct,
            )
            for e in entries
            if e.growth_comparable and e.latest_growth_pct is not None and e.latest_growth_pct > 0
        ]
        rising.sort(key=lambda r: (-r.latest_growth_pct, -r.demand_pct, r.name))
        rising = rising[:RISING_DEMAND_LIMIT]

        summary = SkillGapSummary(
            total_skills_analyzed=len(entries),
            high_priority_gaps=sum(1 for e in entries if e.priority_class == "high"),
            student_population=population,
            students_lacking_demonstrated_skills=population - len(demonstrated_any),
            students_with_reported_skills=students_with_reported,
            students_with_assessment_evidence=len(assessed_any),
            most_demanded_missing_skill=most_demanded_missing,
            rising_demand_skills=rising,
        )

        source = posting_rows[0]["source"] if posting_rows else "mock"
        dataset_version = (
            posting_rows[0].get("dataset_version", "2026.11")
            if posting_rows
            else "2026.11"
        )
        market_meta = _build_meta(agg, source, dataset_version)

        meta = SkillGapMeta(
            market=market_meta,
            thresholds=SkillGapThresholds(
                min_graded_answers=MIN_GRADED_ANSWERS,
                demonstrated_min_pct=DEMONSTRATED_MIN_PCT,
                developing_min_pct=DEVELOPING_MIN_PCT,
                priority_weights=dict(PRIORITY_WEIGHTS),
                priority_class_thresholds=dict(PRIORITY_CLASS_THRESHOLDS),
            ),
            eligible_drive_count=context.eligible_drive_count,
            eligible_assessment_count=context.eligible_assessment_count,
            submitted_eligible_attempt_count=context.submitted_attempt_count,
            unmapped_assessment_skill_tags=sorted(context.unmapped_tags)[:MAX_UNMAPPED_LISTED],
            unmapped_self_reported_skills=sorted(context.unmapped_self_reported)[
                :MAX_UNMAPPED_LISTED
            ],
            notes=[
                "Assessment evidence uses SUBMITTED attempts on placement drives' required "
                "assessments only; practice and standalone assessments are structurally "
                "excluded, and in-progress attempts never count.",
                "The knowledge_states collection is deliberately not used: it is also updated "
                "by practice attempts, so skill evidence is recomputed from eligible attempts.",
                f"A student needs at least {MIN_GRADED_ANSWERS} graded answers on a skill "
                f"(across all eligible attempts) to be classified; below that the evidence is "
                f"'insufficient'. Thresholds: demonstrated >= {DEMONSTRATED_MIN_PCT}%, "
                f"developing >= {DEVELOPING_MIN_PCT}% (mirrors the app's knowledge-tracing "
                "thresholds).",
                "Self-reported skills (profile + active resume) are kept strictly separate "
                "from assessment evidence and never counted as demonstrated proficiency.",
                "The priority score is a transparent demo weighting (see thresholds), not an "
                "established industry standard.",
            ],
        )

        return SkillGapAnalysisResponse(meta=meta, summary=summary, skills=entries)

    def _build_entry(
        self,
        name: str,
        agg: Any,
        catalog_by_name: dict[str, Any],
        context: _Context,
        population: int,
    ) -> tuple[SkillGapEntry, set[str], set[str]]:
        """Builds one skill's gap row. Also returns the sets of students who
        demonstrated / were assessed on ANY skill processed so far feed the
        summary — accumulated by the caller across entries."""
        slug, category, is_technical = _identity_for(name, catalog_by_name)
        full = agg.skill_yearly[name]
        jan_oct = agg.skill_yearly_jan_oct[name]
        partial = agg.current_window[1] != 12
        current = _window_count(full, jan_oct, agg.latest_year, partial)
        previous = _window_count(full, jan_oct, agg.latest_year - 1, partial)
        latest_growth_pct = _growth_pct(current, previous)

        # Company / job-family demand for this skill (inverted from the same
        # aggregate pass — no extra queries).
        company_rows = []
        for company_slug, company in agg.companies.items():
            count = company["skills"].get(name, 0)
            if count:
                company_rows.append(
                    SkillCompanyDemand(
                        company_slug=company_slug,
                        company_name=company["name"],
                        posting_count=count,
                        demand_pct=_pct(count, company["count"]),
                    )
                )
        company_rows.sort(key=lambda c: (-c.posting_count, c.company_name))
        family_rows = []
        for family_name, family in agg.families.items():
            count = family["skills"].get(name, 0)
            if count:
                family_rows.append(
                    SkillJobFamilyDemand(
                        job_family=family_name,
                        posting_count=count,
                        demand_pct=_pct(count, family["count"]),
                    )
                )
        family_rows.sort(key=lambda f: (-f.posting_count, f.job_family))

        # --- Student evidence for this skill ---
        demonstrated_ids: set[str] = set()
        developing_ids: set[str] = set()
        not_demonstrated_ids: set[str] = set()
        insufficient_ids: set[str] = set()
        for student_id, student_evidence in context.evidence.items():
            tally = student_evidence.skills.get(name)
            if not tally or tally.answered == 0:
                continue
            accuracy = 100.0 * tally.correct / tally.answered
            if tally.answered < MIN_GRADED_ANSWERS:
                insufficient_ids.add(student_id)
            elif accuracy >= DEMONSTRATED_MIN_PCT:
                demonstrated_ids.add(student_id)
            elif accuracy >= DEVELOPING_MIN_PCT:
                developing_ids.add(student_id)
            else:
                not_demonstrated_ids.add(student_id)

        reported_ids = {
            student_id for student_id, via in context.reported.items() if name in via
        }
        assessed_ids = demonstrated_ids | developing_ids | not_demonstrated_ids
        both_ids = reported_ids & assessed_ids
        reported_only_ids = reported_ids - assessed_ids - insufficient_ids
        # No evidence = neither self-reported nor any graded answer on this skill.
        no_evidence_count = population - len(
            reported_ids | assessed_ids | insufficient_ids
        )

        students_demonstrated = len(demonstrated_ids)
        students_lacking = population - students_demonstrated

        demand_pct = _pct(agg.skill_totals[name], agg.total_postings)
        gap_pct = _pct(students_lacking, population)
        score = _priority_score(demand_pct, gap_pct, agg.comparable, latest_growth_pct)

        entry = SkillGapEntry(
            skill_id=_slugify(name),
            name=name,
            category=category,
            is_technical=is_technical,
            posting_count=agg.skill_totals[name],
            demand_pct=demand_pct,
            demanding_company_count=len(company_rows),
            demanding_job_family_count=len(family_rows),
            yearly_counts={year: full.get(year, 0) for year in agg.years},
            yearly_demand_pct={
                year: _pct(full.get(year, 0), agg.yearly_totals.get(year, 0))
                for year in agg.years
            },
            latest_growth_pct=latest_growth_pct,
            growth_comparable=agg.comparable,
            students_demonstrated=students_demonstrated,
            students_developing=len(developing_ids),
            students_not_demonstrated=len(not_demonstrated_ids),
            students_insufficient_evidence=len(insufficient_ids),
            students_reported=len(reported_ids),
            students_reported_only=len(reported_only_ids),
            students_both=len(both_ids),
            students_no_evidence=no_evidence_count,
            students_lacking_demonstrated=students_lacking,
            demonstrated_pct=_pct(students_demonstrated, population),
            reported_pct=_pct(len(reported_ids), population),
            gap_pct=gap_pct,
            priority_score=score,
            priority_class=_priority_class(score),
            top_companies=company_rows[:TOP_PER_SKILL],
            top_job_families=family_rows[:TOP_PER_SKILL],
            years=[
                SkillYearDemand(
                    year=year,
                    posting_count=full.get(year, 0),
                    demand_pct=_pct(full.get(year, 0), agg.yearly_totals.get(year, 0)),
                    yoy_growth_pct=self._year_growth(full, jan_oct, year),
                )
                for year in agg.years
            ],
        )
        return entry, demonstrated_ids, assessed_ids | insufficient_ids

    @staticmethod
    def _year_growth(full: Any, jan_oct: Any, year: int) -> float | None:
        """Comparable-window growth for one year of the display series
        (calendar counts are shown; growth never mixes partial windows)."""
        partial = year == MARKET_LATEST_YEAR and MARKET_IS_PARTIAL_YEAR
        current = _window_count(full, jan_oct, year, partial)
        previous = _window_count(full, jan_oct, year - 1, partial)
        return _growth_pct(current, previous)

    # -- Student-level endpoint ----------------------------------------------

    async def get_skill_students(
        self,
        skill_id: str,
        page: int,
        limit: int,
        search: str | None,
        classification: str,
    ) -> SkillGapStudentsResponse:
        """Students associated with ONE demanded skill (no posting filters —
        skill association does not depend on the market filters)."""
        # The unfiltered demand aggregation is needed to resolve the skill id
        # the same way the dashboard rows built it (catalog slug or slugified
        # posting name), so a skill selected in the dashboard always resolves.
        context, market_ctx = await self._build_context(
            year_from=None,
            year_to=None,
            company=None,
            job_family=None,
            location=None,
            skill_category=None,
            technical_only=False,
        )
        posting_names = set(market_ctx["agg"].skill_totals.keys())
        skill_name = self._resolve_skill_id(
            skill_id, market_ctx["catalog_by_name"], posting_names
        )
        if skill_name is None:
            raise SkillGapError(f"Unknown skill '{skill_id}'.", 404)

        rows_out: list[SkillGapStudentEntry] = []
        for student in context.students:
            entry = self._student_entry(student, skill_name, context)
            if classification != "all" and entry.classification != classification:
                continue
            if search and not _name_search_regex(search).search(student.name or ""):
                continue
            rows_out.append(entry)

        rows_out.sort(
            key=lambda e: (
                _CLASSIFICATION_RANK[e.classification],
                e.student_name.casefold(),
                e.student_id,
            )
        )
        total = len(rows_out)
        start = (page - 1) * limit
        page_rows = rows_out[start : start + limit]

        return SkillGapStudentsResponse(
            skill_id=_slugify(skill_name),
            skill_name=skill_name,
            classification=classification,  # type: ignore[arg-type]
            student_population=len(context.students),
            total=total,
            page=page,
            limit=limit,
            entries=page_rows,
        )

    @staticmethod
    def _resolve_skill_id(
        skill_id: str, catalog_by_name: dict[str, Any], posting_names: set[str]
    ) -> str | None:
        """skill_id -> canonical skill name, matching how the dashboard rows
        built their ids (catalog slug, else slugified posting name)."""
        wanted = skill_id.strip().casefold()
        for name in catalog_by_name:
            doc = catalog_by_name[name]
            if doc.slug.casefold() == wanted:
                return doc.name
        for name in posting_names:
            if _slugify(name).casefold() == wanted:
                return name
        return None

    def _student_entry(
        self, student: Any, skill_name: str, context: _Context
    ) -> SkillGapStudentEntry:
        via = context.reported.get(student.id, {}).get(skill_name)
        reported = via is not None
        student_evidence = context.evidence.get(student.id)
        tally = student_evidence.skills.get(skill_name) if student_evidence else None

        accuracy: float | None = None
        assessment_classification: AssessmentEvidenceClass | None = None
        questions_answered = tally.answered if tally else 0
        correct_answers = tally.correct if tally else 0

        if tally and tally.answered > 0:
            accuracy = round(100.0 * tally.correct / tally.answered, 1)
            if tally.answered < MIN_GRADED_ANSWERS:
                assessment_classification = "insufficient_evidence"
            else:
                assessment_classification = _classify_accuracy(accuracy)

        if assessment_classification in ("demonstrated", "developing", "not_demonstrated"):
            classification = "both" if reported else assessment_classification
        elif reported:
            classification = "reported_only"
        elif questions_answered > 0:
            classification = "insufficient_evidence"
        else:
            classification = "no_evidence"

        evidence_list: list[StudentEvidenceSource] = []
        if student_evidence:
            per_assessment = student_evidence.assessments.get(skill_name, {})
            for title, (answered, correct, attempts_used) in sorted(per_assessment.items()):
                evidence_list.append(
                    StudentEvidenceSource(
                        assessment_title=title,
                        attempts_used=attempts_used,
                        questions_answered=answered,
                        correct_answers=correct,
                    )
                )

        return SkillGapStudentEntry(
            student_id=student.id,
            student_name=student.name,
            department=student.department,
            batch_year=student.batch_year,
            self_reported=reported,
            self_reported_via=sorted(via) if via else [],
            classification=classification,  # type: ignore[arg-type]
            assessment_classification=assessment_classification,
            skill_accuracy_pct=accuracy,
            questions_answered=questions_answered,
            correct_answers=correct_answers,
            assessment_evidence=evidence_list,
        )


_CLASSIFICATION_RANK: dict[str, int] = {
    "both": 0,
    "demonstrated": 1,
    "developing": 2,
    "not_demonstrated": 3,
    "reported_only": 4,
    "insufficient_evidence": 5,
    "no_evidence": 6,
}
