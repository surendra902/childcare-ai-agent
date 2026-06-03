"""Configuration management for ChildCareAI Admin Agent.

Loads settings from environment variables / .env file using pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./childcare_admin.db"

    # AI Provider
    ANTHROPIC_API_KEY: str = ""
    OPENROUTER_MODEL: str = "anthropic/claude-3.5-haiku"

    # Security
    ENCRYPTION_KEY: str = ""  # 32-byte base64-encoded key for field-level encryption
    JWT_SECRET: str = ""
    ALLOWED_ORIGINS: str = "https://genaimakers.com"

    # Session & Auth
    SESSION_EXPIRY_HOURS: int = 8
    APPROVAL_TOKEN_EXPIRY_MINUTES: int = 15

    # Compliance
    AUDIT_LOG_RETENTION_DAYS: int = 2555  # 7 years

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 30

    # Debug
    DEBUG: bool = False


settings = Settings()
