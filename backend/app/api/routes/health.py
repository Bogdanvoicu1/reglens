from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/v1/config")
async def public_config() -> dict[str, str]:
    """Runtime config the SPA needs before sign-in, so one frontend build works
    against any backend. Public values only — the Supabase anon key is meant to
    ship to browsers; the service_role key never appears here. An empty
    supabase_url tells the SPA to use the local dev-token sign-in."""
    settings = get_settings()
    return {
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
    }


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, str]:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "down"}
    return {"status": "ok", "database": "up"}
