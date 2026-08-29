"""
Auth endpoints. Cookie handling (setting/clearing the httpOnly refresh
token) lives here, not in the service, since it's an HTTP concern.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import get_settings
from app.core.database import get_database
from app.core.deps import CurrentUser, get_current_user
from app.core.limiter import limiter
from app.models.user import (
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    ResetPasswordRequest,
    StudentRegisterRequest,
    TPORegisterRequest,
    UserPublic,
)
from app.services.auth_service import AuthError, AuthService

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="strict",
        domain=settings.COOKIE_DOMAIN,
        # IMPORTANT: this must be "/" — NOT "/api/v1/auth".
        # The frontend never calls this FastAPI origin directly; it goes
        # through the Next.js rewrite proxy at /api/backend/* (see
        # next.config.mjs), so every request the browser actually makes is
        # to a path like "/api/backend/auth/refresh". A cookie scoped to
        # "/api/v1/auth" only gets attached by the browser when the
        # REQUEST path starts with "/api/v1/auth" — which it never does
        # through the proxy — so the refresh cookie was silently never
        # sent back, making /auth/refresh always fail with 401 on reload.
        # That was the root cause of "refresh logs the user out."
        path="/",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        # Must match the path used in _set_refresh_cookie exactly, or the
        # browser treats this as clearing a different cookie and the old
        # one lingers.
        path="/",
    )


@router.post("/register/student", response_model=UserPublic, status_code=201)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register_student(
    request: Request, payload: StudentRegisterRequest, db: AsyncIOMotorDatabase = Depends(get_database)
):
    service = AuthService(db)
    try:
        user = await service.register_student(payload)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return service.to_public(user)


@router.post("/register/tpo", response_model=UserPublic, status_code=201)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register_tpo(
    request: Request, payload: TPORegisterRequest, db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    TPO registration. In production environment, you can optionally configure
    invitation code or admin authorization. In development/staging, allows
    registration for testing.
    """
    service = AuthService(db)
    try:
        user = await service.register_tpo(payload)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return service.to_public(user)


@router.post("/login", response_model=LoginResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    request: Request, payload: LoginRequest, response: Response, db: AsyncIOMotorDatabase = Depends(get_database)
):
    service = AuthService(db)
    try:
        user = await service.authenticate(payload)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    access_token, raw_refresh, _ = await service.issue_tokens(user)
    _set_refresh_cookie(response, raw_refresh)

    return LoginResponse(access_token=access_token, user=service.to_public(user))


@router.post("/google", response_model=LoginResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def google_auth(
    request: Request, payload: GoogleAuthRequest, response: Response, db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Signs in with Google, creating a new account on first use. `role` in
    the payload is only honored when creating a brand-new account.
    """
    service = AuthService(db)
    try:
        user, is_new = await service.authenticate_with_google(payload.credential, payload.role)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except ValueError as exc:
        # GOOGLE_CLIENT_ID not configured — a server misconfiguration, not
        # a client error.
        logger.error("Google auth misconfigured: %s", exc)
        raise HTTPException(status_code=500, detail="Google Sign-In is not available right now.") from exc

    access_token, raw_refresh, _ = await service.issue_tokens(user)
    _set_refresh_cookie(response, raw_refresh)

    profile_incomplete = is_new and user.role.value == "student"
    return LoginResponse(access_token=access_token, user=service.to_public(user), profile_incomplete=profile_incomplete)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(request: Request, response: Response, db: AsyncIOMotorDatabase = Depends(get_database)):
    raw_refresh = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if not raw_refresh:
        raise HTTPException(status_code=401, detail="No active session.")

    service = AuthService(db)
    try:
        access_token, new_raw_refresh, _ = await service.refresh_access_token(raw_refresh)
    except AuthError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    _set_refresh_cookie(response, new_raw_refresh)
    return RefreshResponse(access_token=access_token)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncIOMotorDatabase = Depends(get_database)):
    raw_refresh = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    service = AuthService(db)
    await service.logout(raw_refresh)
    _clear_refresh_cookie(response)


@router.post("/forgot-password", status_code=202)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def forgot_password(
    request: Request, payload: ForgotPasswordRequest, db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Always returns 202 regardless of whether the email exists, to avoid
    account enumeration. No email provider is wired yet (free-tier SMTP/
    Resend integration is a follow-up) — in APP_ENV=development the raw
    token is logged server-side so you can test the reset flow manually.
    """
    service = AuthService(db)
    raw_token = await service.request_password_reset(payload)
    if raw_token and settings.APP_ENV == "development":
        logger.info("[DEV ONLY] Password reset token for %s: %s", payload.email, raw_token)
    return {"detail": "If that email exists, a reset link has been sent."}


@router.post("/reset-password", status_code=204)
async def reset_password(payload: ResetPasswordRequest, db: AsyncIOMotorDatabase = Depends(get_database)):
    service = AuthService(db)
    try:
        await service.reset_password(payload.token, payload.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/me", response_model=UserPublic)
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    return UserPublic(id=current_user.id, email=current_user.email, role=current_user.role)
