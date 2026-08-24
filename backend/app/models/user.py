"""
Users collection + per-role profile collections (Students/TPOs/Admins),
matching the Phase 1 schema design: Users holds auth-only fields, profile
collections hold everything role-specific, linked by user_id.
"""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.base import MongoBaseModel, PyObjectId


class UserRole(str, Enum):
    STUDENT = "student"
    TPO = "tpo"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Users collection (auth only — never holds profile data)
# ---------------------------------------------------------------------------
class UserInDB(MongoBaseModel):
    email: EmailStr
    password_hash: str | None = None  # None for accounts created via Google Sign-In
    role: UserRole
    auth_provider: str = "local"  # "local" | "google"
    google_sub: str | None = None  # Google's stable user ID, unique when set
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: datetime | None = None


class UserPublic(BaseModel):
    """What the frontend receives — never includes password_hash."""

    id: str
    email: EmailStr
    role: UserRole


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------
class StudentRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    department: str
    batch_year: int = Field(ge=2000, le=2100)


class TPORegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    department_scope: list[str] = Field(default_factory=list)


class AdminRegisterRequest(BaseModel):
    """No public route uses this — admin accounts are deliberately never
    self-service (see scripts/create_admin.py). Kept as a proper Pydantic
    model anyway so the CLI script gets the same validation (email format,
    password length) as every other registration path, rather than
    hand-rolling checks."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    credential: str  # the ID token JWT from Google Identity Services
    role: UserRole = UserRole.STUDENT  # only used if this creates a NEW account


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
    profile_incomplete: bool = False


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Profile collections
# ---------------------------------------------------------------------------
class StudentInDB(MongoBaseModel):
    user_id: PyObjectId
    name: str
    department: str | None = None
    batch_year: int | None = None
    cgpa: float | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    skills: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    certificates: list[str] = Field(default_factory=list)
    active_resume_id: PyObjectId | None = None
    profile_completeness_pct: float = 0.0

    # DEFENSIVE FIX: Field(default_factory=list) only fills in a MISSING
    # key — it does nothing if the key exists with an explicit `None`
    # (e.g. a document written by a crashed/partial insert, or edited by
    # hand in mongosh). Without this, one corrupted student document
    # 500s every endpoint that ever looks that student up — resume
    # upload, assessment start, knowledge-states, etc. — since
    # get_by_user_id() re-validates the raw Mongo doc on every call.
    @field_validator("achievements", "certificates", "skills", mode="before")
    @classmethod
    def _coerce_none_list_to_empty(cls, v):
        return [] if v is None else v

    # `name` has no safe empty default (a blank name would break the UI
    # elsewhere), but coercing None -> a visible placeholder at least
    # keeps the API from 500ing — the student/admin can then fix it via
    # a normal profile update instead of needing a direct DB patch.
    @field_validator("name", mode="before")
    @classmethod
    def _coerce_none_name(cls, v):
        return v if v else "(name not set)"


class TPOInDB(MongoBaseModel):
    user_id: PyObjectId
    name: str
    department_scope: list[str] = Field(default_factory=list)


class AdminInDB(MongoBaseModel):
    user_id: PyObjectId
    name: str


# ---------------------------------------------------------------------------
# Student profile request/response schemas (Phase 12)
# ---------------------------------------------------------------------------
class StudentProfileResponse(BaseModel):
    id: str
    email: EmailStr
    name: str
    department: str | None
    batch_year: int | None
    cgpa: float | None
    phone: str | None
    linkedin_url: str | None
    github_url: str | None
    portfolio_url: str | None
    skills: list[str]
    achievements: list[str]
    certificates: list[str]
    active_resume_id: str | None
    profile_completeness_pct: float


class StudentProfileUpdateRequest(BaseModel):
    """
    All fields optional — this is a partial update (PATCH semantics on a
    PUT route, matching the pattern already used by DriveUpdateRequest).
    Only fields explicitly present in the request body are changed.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    department: str | None = None
    batch_year: int | None = Field(default=None, ge=2000, le=2100)
    cgpa: float | None = Field(default=None, ge=0, le=10)
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    skills: list[str] | None = None
    achievements: list[str] | None = None
    certificates: list[str] | None = None


# ---------------------------------------------------------------------------
# Refresh tokens & password resets
# ---------------------------------------------------------------------------
class RefreshTokenInDB(MongoBaseModel):
    user_id: PyObjectId
    token_hash: str
    expires_at: datetime
    revoked: bool = False
    device_info: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PasswordResetTokenInDB(MongoBaseModel):
    user_id: PyObjectId
    token_hash: str
    expires_at: datetime
    used: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)