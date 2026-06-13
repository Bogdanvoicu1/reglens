import os
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
