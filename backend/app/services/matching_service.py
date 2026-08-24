"""
Phase 7 (single-pair resume-scoring) and Phase 9 (semantic matching /
ranking) service.

Text templates and the hybrid formula below are a direct, deliberate port
of PLACER_RoBERTa_Training_NEW.ipynb (cells 5, 6, and 16 in particular) —
not a reinterpretation. See PROJECT_PROGRESS.md's Phase 7/9 section for
the full reasoning behind every deviation from a literal 1:1 port (the two
that matter: `domain` is omitted from both templates since neither Resume
nor Drive has a domain field in this app's data model, and skill
canonicalization uses `app/ml/matching/skill_ontology.py`'s explicit
alias table rather than the notebook's full ~800-term file, which is
behaviorally equivalent for anything that actually needed normalizing).
"""
import numpy as np
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ml.matching.inference import MatchingEngine, MatchingModelsUnavailable
from app.ml.matching.skill_ontology import to_skill_set
from app.models.drive import PlacementDriveInDB
from app.models.resume import ResumeInDB
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.resume_repository import ResumeRepository

# Matches the notebook's retriever_pool default in evaluate_resume_pretty
# (cell 16) — how many bi-encoder-retrieved candidates get passed to the
# (much more expensive) cross-encoder reranking stage. PLACER's real corpus
# size (a single college's open drives, or applicants to one drive) is
# nowhere near large enough to need this ceiling in practice, but it's
# still the right architectural shape: cheap retrieval narrows a
# potentially large candidate set before the expensive rerank, exactly as
# designed and trained.
DEFAULT_RETRIEVER_POOL = 100


class MatchingUnavailableError(Exception):
    """Raised (and expected to be caught by routers) when the model
    artifacts aren't present in this deployment — see MatchingModelsUnavailable."""


def build_resume_text(skills: list[str], experience_years: float | None) -> str:
    """Domain is deliberately omitted — see module docstring."""
    skills_str = ", ".join(sorted(skills)) if skills else ""
    years = experience_years if experience_years is not None else 0.0
    return f"Technical skills: {skills_str}. Experience years: {years:.1f}"


def build_jd_text(
    job_title: str,
    company_name: str,
    description: str,
    skills: list[str],
    experience_required_years: float,
) -> str:
    skills_str = ", ".join(sorted(skills)) if skills else ""
    return (
        f"Job title: {job_title}. Company: {company_name}. Description: {description}. "
        f"Required skills: {skills_str}. Experience required: {experience_required_years:.1f}"
    )


def exp_fit(resume_years: float, jd_years: float) -> float:
    """Exact port of the notebook's exp_fit()."""
    if jd_years <= 0:
        return 1.0
    return max(0.0, min(1.0, resume_years / jd_years))


def compute_final_score(
    semantic: float,
    skills_score: float,
    experience_score: float,
    assessment_score_pct: float | None = None,
    has_assessment: bool = False,
) -> float:
    """Canonical scoring formula — the SINGLE source of truth for final
    score calculation. Every code path (matching, screening, ranking,
    analytics) MUST use this function. No frontend, no other backend
    module should reimplement this formula.

    Formula: 0.40 × semantic + 0.30 × skills + 0.20 × experience + 0.10 × assessment

    If the drive has no required assessment, the assessment component is
    treated as 1.0 so the candidate is not unfairly penalized.
    """
    if has_assessment and assessment_score_pct is not None:
        assessment_normalized = assessment_score_pct / 100.0
    else:
        # No assessment required or not yet scored — full credit
        assessment_normalized = 1.0

    return (
        0.40 * float(semantic)
        + 0.30 * skills_score
        + 0.20 * experience_score
        + 0.10 * assessment_normalized
    )


class MatchCandidate:
    """One side of a match — either a resume or a JD, reduced to exactly
    what the scoring function needs. Keeps score_batch() below symmetric
    regardless of which direction the pipeline is running (student
    browsing drives vs. TPO reviewing applicants)."""

    __slots__ = ("id", "text", "skills", "experience_years", "embedding")

    def __init__(self, id: str, text: str, skills: set[str], experience_years: float, embedding: np.ndarray | None):
        self.id = id
        self.text = text
        self.skills = skills
        self.experience_years = experience_years
        self.embedding = embedding


class MatchingService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.resumes = ResumeRepository(db)
        self.drives = PlacementDriveRepository(db)

    def _engine(self) -> MatchingEngine:
        try:
            return MatchingEngine.get()
        except MatchingModelsUnavailable as exc:
            raise MatchingUnavailableError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Embedding cache — persisted on the resume/drive document itself
    # (resume_embedding / jd_embedding fields) so repeat matches don't
    # re-run the bi-encoder for text that hasn't changed. Invalidated by
    # resume_parsing_service.py and drive_service.py whenever the
    # underlying text-affecting fields change (see those files).
    # ------------------------------------------------------------------
    async def _get_resume_candidate(self, resume: ResumeInDB) -> MatchCandidate:
        skills = to_skill_set(resume.skill_set)
        text = build_resume_text(sorted(skills), resume.experience_years)

        if resume.resume_embedding is not None:
            embedding = np.array(resume.resume_embedding, dtype=np.float32)
        else:
            embedding = self._engine().embed_texts([text])[0]
            await self.resumes.update_by_id(resume.id, {"resume_embedding": embedding.tolist()})

        return MatchCandidate(
            id=resume.id, text=text, skills=skills, experience_years=resume.experience_years or 0.0, embedding=embedding
        )

    async def _get_drive_candidate(self, drive: PlacementDriveInDB, company_name: str) -> MatchCandidate:
        skills = to_skill_set(drive.required_skills)
        text = build_jd_text(drive.job_title, company_name, drive.description, sorted(skills), drive.experience_required_years)

        if drive.jd_embedding is not None:
            embedding = np.array(drive.jd_embedding, dtype=np.float32)
        else:
            embedding = self._engine().embed_texts([text])[0]
            await self.drives.update_by_id(drive.id, {"jd_embedding": embedding.tolist()})

        return MatchCandidate(
            id=drive.id, text=text, skills=skills, experience_years=drive.experience_required_years, embedding=embedding
        )

    # ------------------------------------------------------------------
    # Core scoring — exact port of compute_hybrid_scores_batch (notebook
    # cell 15). The formula is NOT symmetric between resume and JD:
    # skills_score's denominator is always the JD's required-skill count,
    # and experience_score is always resume_years / jd_years — so unlike a
    # generic "anchor vs candidates" scorer, resume and JD roles must stay
    # fixed regardless of which side is being ranked. Two thin, explicitly
    # oriented wrappers below rather than one generic function that could
    # silently be called in the wrong direction.
    # ------------------------------------------------------------------
    def _cross_score_pairs(self, pairs: list[tuple[str, str]]) -> np.ndarray:
        engine = self._engine()
        return engine.calibrate(engine.cross_score(pairs))

    def _score_one_resume_vs_many_jds(self, resume: MatchCandidate, jds: list[MatchCandidate]) -> list[dict]:
        if not jds:
            return []
        calibrated = self._cross_score_pairs([(resume.text, jd.text) for jd in jds])

        results = []
        for jd, sem in zip(jds, calibrated):
            matched = resume.skills & jd.skills
            missing = jd.skills - resume.skills
            skills_score = len(matched) / max(1, len(jd.skills))
            experience_score = exp_fit(resume.experience_years, jd.experience_years)
            final_score = compute_final_score(float(sem), skills_score, experience_score)
            results.append(
                {
                    "candidate_id": jd.id,
                    "final_score": final_score,
                    "semantic_score": float(sem),
                    "skills_score": skills_score,
                    "experience_score": experience_score,
                    "matched_skills": sorted(matched),
                    "missing_skills": sorted(missing),
                }
            )
        return results

    def _score_one_jd_vs_many_resumes(self, jd: MatchCandidate, resumes: list[MatchCandidate]) -> list[dict]:
        if not resumes:
            return []
        calibrated = self._cross_score_pairs([(resume.text, jd.text) for resume in resumes])

        results = []
        for resume, sem in zip(resumes, calibrated):
            matched = resume.skills & jd.skills
            missing = jd.skills - resume.skills
            skills_score = len(matched) / max(1, len(jd.skills))  # denominator is always the JD's skill count
            experience_score = exp_fit(resume.experience_years, jd.experience_years)
            final_score = compute_final_score(float(sem), skills_score, experience_score)
            results.append(
                {
                    "candidate_id": resume.id,
                    "final_score": final_score,
                    "semantic_score": float(sem),
                    "skills_score": skills_score,
                    "experience_score": experience_score,
                    "matched_skills": sorted(matched),
                    "missing_skills": sorted(missing),
                }
            )
        return results

    def _retrieve_top_k(self, anchor: MatchCandidate, candidates: list[MatchCandidate], k: int) -> list[MatchCandidate]:
        """Bi-encoder retrieval stage — cosine similarity over cached
        embeddings, cheap enough to run over the full candidate set before
        the expensive cross-encoder rerank narrows to just the top k. Pure
        cosine similarity has no resume/JD asymmetry, unlike the hybrid
        formula below, so this one can stay generic."""
        if len(candidates) <= k:
            return candidates
        engine = self._engine()
        candidate_matrix = np.stack([c.embedding for c in candidates])
        sims = engine.cosine_similarity(anchor.embedding, candidate_matrix)
        top_indices = np.argsort(-sims)[:k]
        return [candidates[i] for i in top_indices]

    # ------------------------------------------------------------------
    # Phase 7: single resume x single drive — the foundational
    # "resume-scoring endpoint" the handoff described.
    # ------------------------------------------------------------------
    async def score_resume_against_drive(
        self, resume: ResumeInDB, drive: PlacementDriveInDB, company_name: str
    ) -> dict:
        resume_candidate = await self._get_resume_candidate(resume)
        drive_candidate = await self._get_drive_candidate(drive, company_name)
        return self._score_one_resume_vs_many_jds(resume_candidate, [drive_candidate])[0]

    # ------------------------------------------------------------------
    # Phase 9: rank many drives for one resume ("recommended for you"),
    # or many resumes for one drive ("ranked applicants") — same
    # retrieve-then-rerank shape either direction, formula orientation
    # kept correct by using the two explicitly-oriented scorers above.
    # ------------------------------------------------------------------
    async def rank_drives_for_resume(
        self,
        resume: ResumeInDB,
        drives_with_companies: list[tuple[PlacementDriveInDB, str]],
        retriever_pool: int = DEFAULT_RETRIEVER_POOL,
    ) -> list[dict]:
        resume_candidate = await self._get_resume_candidate(resume)
        drive_candidates = [await self._get_drive_candidate(d, name) for d, name in drives_with_companies]

        retrieved = self._retrieve_top_k(resume_candidate, drive_candidates, retriever_pool)
        results = self._score_one_resume_vs_many_jds(resume_candidate, retrieved)
        return sorted(results, key=lambda r: r["final_score"], reverse=True)

    async def rank_resumes_for_drive(
        self,
        drive: PlacementDriveInDB,
        company_name: str,
        resumes: list[ResumeInDB],
        retriever_pool: int = DEFAULT_RETRIEVER_POOL,
    ) -> list[dict]:
        drive_candidate = await self._get_drive_candidate(drive, company_name)
        resume_candidates = [await self._get_resume_candidate(r) for r in resumes]

        retrieved = self._retrieve_top_k(drive_candidate, resume_candidates, retriever_pool)
        results = self._score_one_jd_vs_many_resumes(drive_candidate, retrieved)
        return sorted(results, key=lambda r: r["final_score"], reverse=True)
