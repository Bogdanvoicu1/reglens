import os
import time
import uuid

import httpx
import jwt
import pytest

# Must be set before any app import caches Settings.
os.environ.setdefault("REGLENS_SUPABASE_JWT_SECRET", "test-secret")

from app.core.config import get_settings  # noqa: E402
from app.core.security import get_verifier  # noqa: E402

get_settings.cache_clear()
get_verifier.cache_clear()

TEST_SECRET = os.environ["REGLENS_SUPABASE_JWT_SECRET"]


def mint_token(
    email: str = "test@reglens.local",
    *,
    secret: str = TEST_SECRET,
    expires_in: int = 3600,
    sub: str | None = None,
    audience: str = "authenticated",
) -> str:
    now = int(time.time())
    claims = {
        "sub": sub or str(uuid.uuid5(uuid.NAMESPACE_DNS, email)),
        "email": email,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def db_available():
    from sqlalchemy import text

    from app.db.session import get_engine

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres not available")


@pytest.fixture
async def redis_available():
    from app.services.redis import get_redis

    try:
        await get_redis().ping()
    except Exception:
        pytest.skip("Redis not available")
