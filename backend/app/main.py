"""
Application entrypoint.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings, validate_production_config
from app.core.database import close_mongo_connection, connect_to_mongo, ensure_indexes
from app.core.limiter import limiter
from app.routers import (
    analytics,
    applications,
    assessments,
    auth,
    drives,
    gap_analysis,
    health,
    jd_explanation,
    matching,
    questions,
    resumes,
    students,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    validate_production_config(settings)
    await connect_to_mongo()
    await ensure_indexes()
    logger.info("%s started in '%s' mode.", settings.APP_NAME, settings.APP_ENV)
    yield
    # --- Shutdown ---
    await close_mongo_connection()
    logger.info("%s shut down cleanly.", settings.APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="AI-Powered Campus Recruitment & Placement Assistance System — REST API",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # --- Rate limiting ---
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Global exception handler (never leak stack traces to clients) ---
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred. Please try again later."},
        )

    # --- Routers ---
    app.include_router(health.router, prefix=settings.API_V1_PREFIX)
    app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["Auth"])
    app.include_router(resumes.router, prefix=f"{settings.API_V1_PREFIX}/resumes", tags=["Resumes"])
    app.include_router(students.router, prefix=f"{settings.API_V1_PREFIX}/students", tags=["Student Profile"])
    app.include_router(drives.router, prefix=f"{settings.API_V1_PREFIX}/drives", tags=["Placement Drives"])
    app.include_router(questions.router, prefix=f"{settings.API_V1_PREFIX}/questions", tags=["Question Bank"])
    app.include_router(assessments.router, prefix=f"{settings.API_V1_PREFIX}/assessments", tags=["Assessments"])
    app.include_router(analytics.router, prefix=f"{settings.API_V1_PREFIX}/analytics", tags=["Analytics"])
    app.include_router(matching.router, prefix=f"{settings.API_V1_PREFIX}/matching", tags=["Matching"])
    app.include_router(applications.router, prefix=f"{settings.API_V1_PREFIX}/applications", tags=["Applications"])
    app.include_router(gap_analysis.router, prefix=settings.API_V1_PREFIX)
    app.include_router(jd_explanation.router, prefix=settings.API_V1_PREFIX)
    # Phase 11+: anti-cheat additions to assessments, admin routers

    return app


app = create_app()