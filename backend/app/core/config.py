"""
Centralized application configuration.

All values are read from environment variables (or a local .env file in dev).
Never hardcode secrets here — see .env.example for the expected keys.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    APP_NAME: str = "PLACER API"
    APP_ENV: str = "development"  # development | staging | production
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Security / JWT ---
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    BCRYPT_ROUNDS: int = 12

    # --- Database ---
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "placer_db"

    # --- CORS ---
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # --- Auth cookie ---
    REFRESH_TOKEN_COOKIE_NAME: str = "placer_refresh_token"
    COOKIE_SECURE: bool = False  # MUST be True in production (HTTPS only)
    COOKIE_DOMAIN: str | None = None

    # --- Google OAuth ("Sign in with Google") ---
    GOOGLE_CLIENT_ID: str = ""

    # --- File storage ---
    STORAGE_BACKEND: str = "local"  # local | cloudinary
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    LOCAL_STORAGE_PATH: str = "./storage"
    MAX_RESUME_SIZE_MB: int = 5

    # --- Rate limiting ---
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    # --- ML artifacts (wired in Phase 7) ---
    ML_ARTIFACTS_DIR: str = "./app/ml/matching/artifacts"

    # --- OCR (PaddleOCR PP-OCRv4) ---
    OCR_ENABLED: bool = True
    OCR_LANG: str = "en"
    OCR_USE_GPU: bool = False
    OCR_USE_ANGLE_CLS: bool = True
    OCR_CONFIDENCE_THRESHOLD: float = 0.5
    OCR_TRIGGER_MIN_CHARS: int = 50
    OCR_MIN_ALPHANUMERIC_RATIO: float = 0.5
    OCR_RENDER_DPI: int = 150
    OCR_PYTHON_PATH: str = "./.venv311/Scripts/python.exe"


    # --- LLM (Phase A) --------------------------------------------------
    # Primary / fallback are both wired through the SAME client interface.
    # Provider is just a config value — "ollama" | "nvidia_nim" | "openrouter".
    LLM_PRIMARY_PROVIDER: str = "nvidia_nim"
    LLM_PRIMARY_MODEL: str = "nvidia/nemotron-4-340b-instruct"
    LLM_PRIMARY_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    LLM_PRIMARY_API_KEY: str = ""  # must be set in .env — never hardcode API keys
    LLM_FALLBACK_PROVIDER: str = "nvidia_nim"
    LLM_FALLBACK_MODEL: str = "nvidia/nemotron-4-340b-instruct"
    LLM_FALLBACK_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    LLM_FALLBACK_API_KEY: str = ""  # must be set in .env — never hardcode API keys                     

    # Local dev option (no external calls at all) — Ollama running Qwen.
    LLM_USE_LOCAL_OLLAMA: bool = False
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:8b"

    # Qwen3 hybrid "thinking mode" — ON for narrative calls (gap analysis,
    # JD explanation), OFF for the skill-extraction JSON call. Nemotron
    # ignores this flag (its client branch just won't send it).
    LLM_THINKING_MODE_NARRATIVE: bool = True
    LLM_THINKING_MODE_EXTRACTION: bool = False

    # Timeouts / retries — every LLM call must fail SOFTLY (see
    # llm/exceptions.py). No call should hang the request thread forever.
    LLM_REQUEST_TIMEOUT_SECONDS: int = 30
    LLM_MAX_RETRIES: int = 1

    # --- Embeddings (separate small model — NOT Qwen/Nemotron) ----------
    EMBEDDING_PROVIDER: str = "ollama"                  # local, cheap, fast
    EMBEDDING_MODEL: str = "nomic-embed-text"           # or bge-small
    EMBEDDING_BASE_URL: str = "http://localhost:11434"
    EMBEDDING_DIM: int = 768                            # nomic-embed-text=768, bge-small=384

    # --- Knowledge-chunk store (Phase C/D) -------------------------------
    KNOWLEDGE_STORE_BACKEND: str = "mongodb_cosine"     # simple: cosine sim in Python
                                                          # over vectors stored in Mongo.
                                                          # swap to a real vector DB later
                                                          # without touching callers.


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — env is read once per process."""
    return Settings()


def validate_production_config(settings: Settings) -> None:
    """Startup guard — blocks unsafe defaults in production. Does NOT
    break local development (only fires when APP_ENV == 'production')."""
    import logging
    logger = logging.getLogger(__name__)

    if settings.APP_ENV != "production":
        return

    errors: list[str] = []

    if settings.DEBUG:
        errors.append("DEBUG must be False in production.")

    if settings.JWT_SECRET_KEY == "CHANGE_ME_IN_PRODUCTION":
        errors.append("JWT_SECRET_KEY must not use the default value in production.")

    if not settings.COOKIE_SECURE:
        errors.append("COOKIE_SECURE must be True in production (HTTPS only).")

    if "*" in settings.CORS_ORIGINS:
        errors.append("CORS_ORIGINS must not contain wildcard '*' with credentials in production.")

    if errors:
        for e in errors:
            logger.critical("PRODUCTION CONFIG ERROR: %s", e)
        raise SystemExit(
            "Production configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )