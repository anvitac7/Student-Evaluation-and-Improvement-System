"""
Resume storage model.

`parsed`, `resume_text`, `skill_set`, and `experience_years` are placeholders
populated by Phase 6 (Resume Parsing) and Phase 7 (PLACER scoring
integration) — left null/empty here since Phase 5 only covers upload,
validation, versioning, and storage, not extraction.
"""
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.base import MongoBaseModel, PyObjectId


class ParsedResumeData(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    department: str | None = None
    batch_year: int | None = None
    cgpa: float | None = None
    education: list[dict] = Field(default_factory=list)
    experience: list[dict] = Field(default_factory=list)
    projects: list[dict] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    parsing_metadata: dict | None = None


class ResumeInDB(MongoBaseModel):
    student_id: PyObjectId
    version: int
    original_filename: str
    file_url: str
    file_hash: str
    file_size_bytes: int
    parsed: ParsedResumeData | None = None
    resume_text: str | None = None
    skill_set: list[str] = Field(default_factory=list)
    experience_years: float | None = None
    resume_embedding: list[float] | None = None  # Phase 9: bi-encoder embedding cache, see matching_service
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


class ResumeUploadResponse(BaseModel):
    id: str
    version: int
    original_filename: str
    file_size_bytes: int
    uploaded_at: datetime
    is_active: bool


class ResumeSummary(BaseModel):
    id: str
    version: int
    original_filename: str
    uploaded_at: datetime
    is_active: bool


class ResumeDetail(BaseModel):
    id: str
    version: int
    original_filename: str
    uploaded_at: datetime
    is_active: bool
    parsed: ParsedResumeData | None
    skill_set: list[str]
    experience_years: float | None
