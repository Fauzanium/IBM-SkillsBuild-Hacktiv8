"""
config.py
─────────
Centralised application settings loaded from environment variables.
Uses pydantic-settings so every value is type-validated at startup.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """All runtime configuration in one place — no scattered os.getenv() calls."""

    # ── LLM ──────────────────────────────────────────────────────────────────
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_model: str = Field("gpt-4o-mini", description="Model identifier")
    openai_temperature: float = Field(0.0, ge=0.0, le=1.0)

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        "sqlite+aiosqlite:///./document_db.sqlite",
        description="Async SQLAlchemy connection string",
    )

    # ── System ────────────────────────────────────────────────────────────────
    log_level: str = Field("INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")
    max_retries: int = Field(3, ge=1, le=10)
    extraction_timeout: int = Field(60, ge=10)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Singleton — import this everywhere instead of re-instantiating
settings = Settings()
