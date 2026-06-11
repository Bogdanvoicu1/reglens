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

    # LLM provider — any OpenAI-compatible API; defaults target OpenRouter
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dim: int = 1536
    generation_model: str = "openai/gpt-4o-mini"
    judge_model: str = "openai/gpt-4o"

    # Rate limiting defaults (requests per minute per tenant)
    rate_limit_rpm: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
