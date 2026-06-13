"""Authentication: Supabase-compatible JWT verification + JIT tenant provisioning.

Two verifier strategies, chosen by configuration:
- HS256 with the project's JWT secret (legacy Supabase, also local dev tokens)
- JWKS with asymmetric keys (new Supabase projects); keys are fetched and
  cached by PyJWKClient

On a user's first authenticated request we provision a personal tenant and a
user row keyed by the token's `sub`. A `tenant_id` in `app_metadata` (set via
Supabase admin) overrides this and attaches the user to an existing tenant.
"""

import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status
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


class HS256Verifier:
    def __init__(self, secret: str, issuer: str, audience: str) -> None:
        self._secret = secret
        self._issuer = issuer or None
        self._audience = audience

    def verify(self, token: str) -> dict[str, Any]:
        return jwt.decode(
            token,
            self._secret,
            algorithms=["HS256"],
            audience=self._audience,
            issuer=self._issuer,
            leeway=_LEEWAY_SECONDS,
            options={"require": ["exp", "sub"], "verify_iss": bool(self._issuer)},
        )


class JWKSVerifier:
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


class MultiVerifier:
    """Routes a token to the right verifier by its declared algorithm, so an
    HS256 secret (legacy projects, local dev tokens) and a JWKS endpoint (new
    Supabase projects signing RS256/ES256) can both be configured at once.
    Routing is by the unverified `alg` header only; each verifier still pins its
    own algorithms and key, so this does not enable an algorithm-confusion
    downgrade."""

    def __init__(self, hs256: "HS256Verifier | None", jwks: "JWKSVerifier | None") -> None:
        self._hs256 = hs256
        self._jwks = jwks

    def verify(self, token: str) -> dict[str, Any]:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256" and self._hs256 is not None:
            return self._hs256.verify(token)
        if alg in ("RS256", "ES256") and self._jwks is not None:
            return self._jwks.verify(token)
        raise jwt.InvalidAlgorithmError(f"no verifier configured for token alg {alg!r}")


@lru_cache
def get_verifier() -> HS256Verifier | JWKSVerifier | MultiVerifier:
    settings: Settings = get_settings()
    hs256 = (
        HS256Verifier(
            settings.supabase_jwt_secret, settings.supabase_issuer, settings.supabase_audience
        )
        if settings.supabase_jwt_secret
        else None
    )
    jwks = (
        JWKSVerifier(
            settings.supabase_jwks_url, settings.supabase_issuer, settings.supabase_audience
        )
        if settings.supabase_jwks_url
        else None
    )
    if hs256 and jwks:
        return MultiVerifier(hs256, jwks)
    if hs256:
        return hs256
    if jwks:
        return jwks
    raise AuthConfigurationError(
        "Set REGLENS_SUPABASE_JWT_SECRET or REGLENS_SUPABASE_JWKS_URL to enable auth"
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

    email = claims.get("email")
    user = await session.get(User, user_id)
    if user is None:
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
        await session.commit()
        log.info("user_provisioned", user_id=str(user_id), tenant_id=str(tenant_id))
    return AuthContext(user_id=user.id, tenant_id=user.tenant_id, email=user.email, role=user.role)


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
