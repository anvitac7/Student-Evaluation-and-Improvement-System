"""
Auth business logic. Routers stay thin — they just parse the request,
call this service, and shape the HTTP response (including cookie setting).
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.google_oauth import verify_google_token
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.user import (
    AdminInDB,
    AdminRegisterRequest,
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    StudentInDB,
    StudentRegisterRequest,
    TPOInDB,
    TPORegisterRequest,
    UserInDB,
    UserPublic,
    UserRole,
)
from app.repositories.profile_repositories import AdminRepository, StudentRepository, TPORepository
from app.repositories.token_repositories import PasswordResetTokenRepository, RefreshTokenRepository
from app.repositories.user_repository import UserRepository


class AuthError(Exception):
    """Raised for any auth failure; routers map this to an HTTP 4xx."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AuthService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.users = UserRepository(db)
        self.students = StudentRepository(db)
        self.tpos = TPORepository(db)
        self.admins = AdminRepository(db)
        self.refresh_tokens = RefreshTokenRepository(db)
        self.reset_tokens = PasswordResetTokenRepository(db)

    # -----------------------------------------------------------------
    # Registration
    # -----------------------------------------------------------------
    async def register_student(self, payload: StudentRegisterRequest) -> UserInDB:
        existing = await self.users.get_by_email(payload.email)
        if existing:
            raise AuthError("An account with this email already exists.", 409)

        user = await self.users.create(
            {
                "email": payload.email.lower(),
                "password_hash": hash_password(payload.password),
                "role": UserRole.STUDENT.value,
                "is_active": True,
                "created_at": datetime.utcnow(),
                "last_login": None,
            }
        )
        # FIX: this used to be two separate, non-atomic inserts — if the
        # process crashed/restarted between them (which is exactly what
        # was happening during earlier bcrypt failures), you'd end up
        # with a `users` row and no matching `students` row at all, or a
        # `students` doc with missing/null fields from a retried request
        # hitting a half-created state. If the student-profile insert
        # fails for any reason, roll back the orphaned user instead of
        # leaving a broken half-account behind.
        try:
            await self.students.create(
                {
                    "user_id": user.id,
                    "name": payload.name,
                    "department": payload.department,
                    "batch_year": payload.batch_year,
                    "skills": [],
                    "achievements": [],
                    "certificates": [],
                    "profile_completeness_pct": 0.0,
                }
            )
        except Exception:
            await self.users.delete_by_id(str(user.id))
            raise
        return user

    async def register_tpo(self, payload: TPORegisterRequest) -> UserInDB:
        existing = await self.users.get_by_email(payload.email)
        if existing:
            raise AuthError("An account with this email already exists.", 409)

        user = await self.users.create(
            {
                "email": payload.email.lower(),
                "password_hash": hash_password(payload.password),
                "role": UserRole.TPO.value,
                "is_active": True,
                "created_at": datetime.utcnow(),
                "last_login": None,
            }
        )
        await self.tpos.create(
            {
                "user_id": user.id,
                "name": payload.name,
                "department_scope": payload.department_scope,
            }
        )
        return user

    async def register_admin(self, payload: AdminRegisterRequest) -> UserInDB:
        """No router calls this — see scripts/create_admin.py. Kept in the
        service layer anyway, same as register_student/register_tpo, so the
        CLI script doesn't have to duplicate the user+profile document
        creation logic (and so a future 'admin invites another admin'
        endpoint, if ever needed, has this ready to call)."""
        existing = await self.users.get_by_email(payload.email)
        if existing:
            raise AuthError("An account with this email already exists.", 409)

        user = await self.users.create(
            {
                "email": payload.email.lower(),
                "password_hash": hash_password(payload.password),
                "role": UserRole.ADMIN.value,
                "is_active": True,
                "created_at": datetime.utcnow(),
                "last_login": None,
            }
        )
        await self.admins.create(
            {
                "user_id": user.id,
                "name": payload.name,
            }
        )
        return user

    # -----------------------------------------------------------------
    # Login / logout
    # -----------------------------------------------------------------
    async def authenticate(self, payload: LoginRequest) -> UserInDB:
        user = await self.users.get_by_email(payload.email)
        if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
            # Same message whether the account doesn't exist, has no
            # password (Google-only), or the password is wrong — do not
            # leak which one it was (prevents email enumeration).
            raise AuthError("Invalid email or password.", 401)
        if not user.is_active:
            raise AuthError("This account has been deactivated. Contact your administrator.", 403)

        await self.users.update_by_id(user.id, {"last_login": datetime.utcnow()})
        return user

    async def authenticate_with_google(
        self, credential: str, requested_role: UserRole
    ) -> tuple[UserInDB, bool]:
        """
        Verifies a Google ID token and either logs in an existing account
        or creates a new one. Returns (user, is_new_account).

        `requested_role` is only consulted when creating a brand-new
        account — for an existing account we always use its stored role,
        so a returning user can't escalate/change role by passing a
        different value on a later Google sign-in.
        """
        payload = verify_google_token(credential)
        if not payload.email_verified:
            raise AuthError("Your Google account's email is not verified.", 401)

        user = await self.users.get_by_google_sub(payload.sub)
        if not user:
            user = await self.users.get_by_email(payload.email)
            if user and user.auth_provider == "local":
                raise AuthError(
                    "An account with this email already exists. Please sign in with your password instead.",
                    409,
                )

        is_new = False
        if not user:
            if requested_role not in (UserRole.STUDENT, UserRole.TPO):
                raise AuthError("Google sign-up is only available for students and TPOs.", 400)

            is_new = True
            display_name = payload.name or payload.email.split("@")[0]
            user = await self.users.create(
                {
                    "email": payload.email.lower(),
                    "password_hash": None,
                    "role": requested_role.value,
                    "auth_provider": "google",
                    "google_sub": payload.sub,
                    "is_active": True,
                    "created_at": datetime.utcnow(),
                    "last_login": None,
                }
            )
            if requested_role == UserRole.STUDENT:
                # department/batch_year are unknown from Google — left null
                # and collected via a "complete your profile" prompt
                # (frontend redirects here on profile_incomplete=true).
                await self.students.create(
                    {
                        "user_id": user.id,
                        "name": display_name,
                        "department": None,
                        "batch_year": None,
                        "skills": [],
                        "achievements": [],
                        "certificates": [],
                        "profile_completeness_pct": 0.0,
                    }
                )
            else:
                await self.tpos.create(
                    {"user_id": user.id, "name": display_name, "department_scope": []}
                )
        else:
            if not user.is_active:
                raise AuthError("This account has been deactivated. Contact your administrator.", 403)
            await self.users.update_by_id(user.id, {"last_login": datetime.utcnow()})

        return user, is_new

    async def issue_tokens(self, user: UserInDB) -> tuple[str, str, datetime]:
        """Returns (access_token, raw_refresh_token, refresh_expires_at)."""
        access_token = create_access_token(subject=user.id, role=user.role.value)
        raw_refresh, token_hash, expires_at = generate_refresh_token()
        await self.refresh_tokens.create(
            {
                "user_id": user.id,
                "token_hash": token_hash,
                "expires_at": expires_at,
                "revoked": False,
                "created_at": datetime.utcnow(),
            }
        )
        return access_token, raw_refresh, expires_at

    async def refresh_access_token(self, raw_refresh_token: str) -> tuple[str, str, datetime]:
        """
        Validates + ROTATES the refresh token (old one is revoked, a new one
        issued) so a stolen-and-reused token is detectable/limited, and
        returns a new access token plus the new raw refresh token to set
        as the cookie.
        """
        token_hash = hash_refresh_token(raw_refresh_token)
        token_doc = await self.refresh_tokens.get_valid_by_hash(token_hash)
        if not token_doc:
            raise AuthError("Session expired. Please sign in again.", 401)
        if token_doc.expires_at < datetime.utcnow():
            await self.refresh_tokens.revoke(token_doc.id)
            raise AuthError("Session expired. Please sign in again.", 401)

        user = await self.users.get_by_id(token_doc.user_id)
        if not user or not user.is_active:
            raise AuthError("Account unavailable.", 403)

        # Rotate: revoke the used token, issue a fresh pair.
        await self.refresh_tokens.revoke(token_doc.id)
        access_token, raw_refresh, expires_at = await self.issue_tokens(user)
        return access_token, raw_refresh, expires_at

    async def logout(self, raw_refresh_token: str | None) -> None:
        if not raw_refresh_token:
            return
        token_hash = hash_refresh_token(raw_refresh_token)
        token_doc = await self.refresh_tokens.get_valid_by_hash(token_hash)
        if token_doc:
            await self.refresh_tokens.revoke(token_doc.id)

    # -----------------------------------------------------------------
    # Password reset
    # -----------------------------------------------------------------
    async def request_password_reset(self, payload: ForgotPasswordRequest) -> str | None:
        """
        Returns the raw reset token ONLY so the caller (router) can decide
        whether to email it or — in dev, with no email provider configured
        yet — log/return it directly. Always returns None to the HTTP
        response regardless of whether the email existed, to avoid account
        enumeration.
        """
        user = await self.users.get_by_email(payload.email)
        if not user:
            return None

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        await self.reset_tokens.create(
            {
                "user_id": user.id,
                "token_hash": token_hash,
                "expires_at": datetime.utcnow() + timedelta(hours=1),
                "used": False,
                "created_at": datetime.utcnow(),
            }
        )
        return raw_token

    async def reset_password(self, token: str, new_password: str) -> None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        token_doc = await self.reset_tokens.get_valid_by_hash(token_hash)
        if not token_doc or token_doc.expires_at < datetime.utcnow():
            raise AuthError("This reset link is invalid or has expired.", 400)

        await self.users.update_by_id(token_doc.user_id, {"password_hash": hash_password(new_password)})
        await self.reset_tokens.mark_used(token_doc.id)
        # Force re-login on every device after a password reset.
        await self.refresh_tokens.revoke_all_for_user(token_doc.user_id)

    # -----------------------------------------------------------------
    # Public projection
    # -----------------------------------------------------------------
    @staticmethod
    def to_public(user: UserInDB) -> UserPublic:
        return UserPublic(id=user.id, email=user.email, role=user.role)