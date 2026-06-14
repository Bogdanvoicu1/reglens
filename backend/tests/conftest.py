import asyncio
import os
import re
import time
import uuid
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

# Configure auth BEFORE any app import caches Settings. Supabase signs JWTs with
# asymmetric keys; tests mirror that with a locally-generated RSA keypair rather
# than a live JWKS endpoint. The verifier is pointed at a dummy JWKS URL, and
# PyJWKClient is patched (below) to hand back our public key — so verification
# runs the real code path with zero network. Pin the rest of the Supabase
# surface so a developer's real .env (issuer, audience) can't leak in and reject
# the test tokens.
os.environ["REGLENS_SUPABASE_JWKS_URL"] = "https://test.invalid/jwks.json"
os.environ["REGLENS_SUPABASE_ISSUER"] = ""
os.environ["REGLENS_SUPABASE_AUDIENCE"] = "authenticated"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
# A second, untrusted key for the wrong-signature test.
WRONG_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-key"


class _FakeSigningKey:
    key = _PUBLIC_KEY


def _fake_signing_key(self: Any, token: str) -> _FakeSigningKey:
    return _FakeSigningKey()


# Every JWKSVerifier instance resolves to our public key without any network I/O.
jwt.PyJWKClient.get_signing_key_from_jwt = _fake_signing_key  # type: ignore[method-assign]

from app.core.config import get_settings  # noqa: E402
from app.core.security import get_verifier  # noqa: E402

# Route the suite at throwaway stores so a test run can never mutate a
# developer's real data — a destructive ingestion test once wiped the dev
# corpus by sharing the dev database. The DB name is the configured one
# suffixed with `_test` (override via REGLENS_TEST_DATABASE_URL); Redis uses a
# separate logical db. Must happen before any app import caches the engine.
_configured = get_settings()
TEST_DATABASE_URL = os.environ.get("REGLENS_TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    from sqlalchemy import make_url

    _u = make_url(_configured.database_url)
    TEST_DATABASE_URL = _u.set(database=f"{_u.database or 'reglens'}_test").render_as_string(
        hide_password=False
    )
os.environ["REGLENS_DATABASE_URL"] = TEST_DATABASE_URL
_redis = _configured.redis_url
os.environ["REGLENS_REDIS_URL"] = (
    re.sub(r"/\d+$", "/15", _redis) if re.search(r"/\d+$", _redis) else _redis.rstrip("/") + "/15"
)

get_settings.cache_clear()
get_verifier.cache_clear()


def mint_token(
    email: str = "test@reglens.local",
    *,
    key: rsa.RSAPrivateKey = _PRIVATE_KEY,
    expires_in: int = 3600,
    sub: str | None = None,
    audience: str = "authenticated",
    app_metadata: dict[str, Any] | None = None,
) -> str:
    """Mint an RS256 JWT shaped like a Supabase access token, signed by the
    trusted test key (override `key` to forge a bad signature)."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub or str(uuid.uuid5(uuid.NAMESPACE_DNS, email)),
        "email": email,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
    }
    if app_metadata is not None:
        claims["app_metadata"] = app_metadata
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": _KID})


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


@pytest.fixture(scope="session", autouse=True)
def _provision_test_database():
    """Create and migrate the throwaway test database once per session.

    Creates it via the maintenance ``postgres`` db if absent, then applies all
    migrations (which also installs pgvector and the HNSW index). Synchronous so
    Alembic's own ``asyncio.run`` has no running loop to clash with. If Postgres
    is unreachable, do nothing and let db-dependent tests skip via
    ``db_available``.
    """
    from sqlalchemy import make_url, text
    from sqlalchemy.ext.asyncio import create_async_engine

    test_url = make_url(TEST_DATABASE_URL)

    async def _ensure_db() -> None:
        admin = create_async_engine(
            test_url.set(database="postgres").render_as_string(hide_password=False),
            isolation_level="AUTOCOMMIT",
        )
        try:
            async with admin.connect() as conn:
                exists = await conn.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"),
                    {"n": test_url.database},
                )
                if not exists:
                    await conn.execute(text(f'CREATE DATABASE "{test_url.database}"'))
        finally:
            await admin.dispose()

    try:
        asyncio.run(_ensure_db())
    except Exception:
        return  # Postgres down — db-dependent tests skip via db_available.

    from alembic.config import Config

    from alembic import command

    command.upgrade(Config("alembic.ini"), "head")
