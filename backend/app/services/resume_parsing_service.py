"""
PHASE B — app/services/resume_parsing_service.py (PATCHED)

Diff from the original: after the existing regex-based `parse_resume()`
call, skill_set is UPGRADED via the LLM-constrained extractor (falls back
to the regex result automatically if the LLM is down — see
llm_skill_extractor.extract_skills_llm). Everything else (contact
extraction, section parsing, storage read) is untouched, per the
"unchanged, deliberately" note in the workflow doc.
"""
import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ml.parsing.parser import parse_resume
from app.ml.parsing.llm_skill_extractor import extract_skills_llm
from app.repositories.resume_repository import ResumeRepository
from app.repositories.unmapped_skill_repository import UnmappedSkillRepository
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class ResumeParsingService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.resumes = ResumeRepository(db)
        self.unmapped_skills = UnmappedSkillRepository(db)
        self.storage = StorageService()

    async def parse_and_store(self, resume_id: str) -> bool:
        resume = await self.resumes.get_by_id(resume_id)
        if not resume:
            logger.error("parse_and_store called for missing resume_id=%s", resume_id)
            return False

        try:
            file_bytes = self._read_file(resume.file_url)
            parsed, text, _regex_skills, experience_years = parse_resume(file_bytes)
        except Exception:
            logger.exception("Resume parsing failed for resume_id=%s", resume_id)
            return False

        # --- Phase B upgrade: LLM-constrained skill extraction ----------
        # Still grounded in the same 50-term CANONICAL_SKILLS/ALIASES —
        # this call cannot invent new canonical categories, it can only
        # recognize phrasing variants of the existing vocabulary. Falls
        # back to `_regex_skills` automatically inside extract_skills_llm
        # if the LLM is unreachable, so there is no functionality
        # regression on LLM downtime.
        skills, unmapped = extract_skills_llm(text, source_id=resume_id, source_type="resume")
        if not skills:
            # Belt-and-suspenders: if the LLM path returned nothing at all
            # (e.g. malformed-but-not-raising edge case), don't silently
            # ship an empty skill set when regex already found something.
            skills = _regex_skills

        await self.unmapped_skills.add_many(unmapped)

        await self.resumes.update_by_id(
            resume_id,
            {
                "parsed": parsed.model_dump(),
                "resume_text": text,
                "skill_set": skills,
                "experience_years": experience_years,
                "resume_embedding": None,
            },
        )
        return True

    def _read_file(self, file_url: str) -> bytes:
        if file_url.startswith("local://"):
            return self.storage.read_local_file(file_url)

        import requests

        response = requests.get(file_url, timeout=15)
        response.raise_for_status()
        return response.content