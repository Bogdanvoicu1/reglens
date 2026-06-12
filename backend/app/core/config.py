from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REGLENS_", env_file=".env", extra="ignore")

    env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://reglens:reglens@localhost:5432/reglens"
    redis_url: str = "redis://localhost:6379/0"

    # Auth — set EITHER the legacy Supabase JWT secret (HS256) OR a JWKS URL
    # (new Supabase projects: https://<ref>.supabase.co/auth/v1/.well-known/jwks.json)
    supabase_jwt_secret: str = ""
    supabase_jwks_url: str = ""
    supabase_issuer: str = ""  # optional; verified when set
    supabase_audience: str = "authenticated"

    cors_origins: list[str] = ["http://localhost:5173"]
    answer_cache_ttl_seconds: int = 86400
    max_request_bytes: int = 65536

    # Langfuse LLM tracing — disabled unless both keys are set
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # LLM provider — any OpenAI-compatible API; defaults target OpenRouter
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dim: int = 1536
    generation_model: str = "openai/gpt-4o-mini"
    judge_model: str = "openai/gpt-4o"
    # Hard cap on completion length: bounds cost per request and limits damage
    # from runaway generations. Cited answers fit comfortably under this.
    generation_max_tokens: int = 1024
    # When false, user questions are logged/traced as a hash, not plaintext.
    log_question_text: bool = False

    # Rate limiting defaults (requests per minute per tenant)
    rate_limit_rpm: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
