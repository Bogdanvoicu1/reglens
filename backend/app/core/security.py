"""Authentication: Supabase JWT verification (JWKS) + JIT tenant provisioning.

Supabase signs each project's JWTs with asymmetric keys; we verify them locally
against the project's JWKS endpoint (keys fetched and cached by PyJWKClient), so
there is no per-request round-trip to Supabase. On a user's first authenticated
request we provision a personal tenant and a user row keyed by the token's `sub`.
A `tenant_id` in `app_metadata` (set via Supabase admin) instead attaches the
user to an existing tenant.
"""

import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Tenant, User
from app.db.session import get_session

log = structlog.get_logger()

_LEEWAY_SECONDS = 30


class AuthConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthContext:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str | None
    role: str


class JWKSVerifier:
    """Verifies a Supabase JWT against the project's JWKS endpoint. Algorithms
    are pinned to the asymmetric set, so a symmetric (HS256) token can never be
    accepted by passing a public key as a shared secret."""

    def __init__(self, jwks_url: str, issuer: str, audience: str) -> None:
        self._jwk_client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300)
        self._issuer = issuer or None
        self._audience = audience

    def verify(self, token: str) -> dict[str, Any]:
        key = self._jwk_client.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256", "ES256"],
            audience=self._audience,
            issuer=self._issuer,
            leeway=_LEEWAY_SECONDS,
            options={"require": ["exp", "sub"], "verify_iss": bool(self._issuer)},
        )


@lru_cache
def get_verifier() -> JWKSVerifier:
    settings: Settings = get_settings()
    if not settings.supabase_jwks_url:
        raise AuthConfigurationError(
            "Set REGLENS_SUPABASE_JWKS_URL to enable auth "
            "(https://<ref>.supabase.co/auth/v1/.well-known/jwks.json)"
        )
    return JWKSVerifier(
        settings.supabase_jwks_url, settings.supabase_issuer, settings.supabase_audience
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _provision(session: AsyncSession, claims: dict[str, Any]) -> AuthContext:
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise _unauthorized("Token subject is not a valid user id") from exc

    user = await session.get(User, user_id)
    if user is None:
        user = await _provision_user(session, user_id, claims)
    return AuthContext(user_id=user.id, tenant_id=user.tenant_id, email=user.email, role=user.role)


async def _provision_user(
    session: AsyncSession, user_id: uuid.UUID, claims: dict[str, Any]
) -> User:
    """Create the user row (and a personal tenant unless the token names one).

    A brand-new user's first page load fires several authenticated requests at
    once; they all see no user and race to insert the same row, so one wins and
    the rest hit a duplicate-key error. Recover by rolling back and adopting the
    row that landed, so every concurrent request still succeeds.
    """
    email = claims.get("email")
    app_meta = claims.get("app_metadata") or {}
    tenant_id = None
    if app_meta.get("tenant_id"):
        tenant_id = uuid.UUID(str(app_meta["tenant_id"]))
        if await session.get(Tenant, tenant_id) is None:
            raise _unauthorized("Token references an unknown tenant")
    if tenant_id is None:
        tenant = Tenant(name=email or f"workspace-{str(user_id)[:8]}")
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id
    user = User(id=user_id, tenant_id=tenant_id, email=email)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.get(User, user_id)
        if existing is None:
            raise
        return existing
    log.info("user_provisioned", user_id=str(user_id), tenant_id=str(tenant_id))
    return user


async def get_current_user(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> AuthContext:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Missing bearer token")
    try:
        claims = get_verifier().verify(token.strip())
    except AuthConfigurationError:
        raise HTTPException(status_code=501, detail="Authentication is not configured") from None
    except jwt.PyJWTError as exc:
        raise _unauthorized(f"Invalid token: {type(exc).__name__}") from exc
    return await _provision(session, claims)
