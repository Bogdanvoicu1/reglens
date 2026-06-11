from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REGLENS_", env_file=".env", extra="ignore")

    env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://reglens:reglens@localhost:5432/reglens"
    redis_url: str = "redis://localhost:6379/0"

    # Supabase JWT verification (M3)
    supabase_jwks_url: str = ""
    supabase_issuer: str = ""

    # LLM providers (M2)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    generation_model: str = "gpt-4o-mini"

    # Rate limiting defaults (requests per minute per tenant)
    rate_limit_rpm: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
