import base64
import json
import uuid

import jwt as pyjwt
import pytest
from sqlalchemy import delete, select

from app.core.security import HS256Verifier, MultiVerifier
from app.db.models import Tenant, User
from app.db.session import get_sessionmaker
from tests.conftest import TEST_SECRET, mint_token


def _token_with_alg(alg: str) -> str:
    """A syntactically-valid JWT whose header advertises `alg` (for routing)."""
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': alg, 'typ': 'JWT'})}.{enc({'sub': 'x'})}.sig"


class TestMultiVerifier:
    """Algorithm-aware routing so HS256 dev tokens and an RS256/ES256 Supabase
    project can both be configured at once."""

    def test_routes_hs256_to_the_secret_verifier(self):
        mv = MultiVerifier(HS256Verifier(TEST_SECRET, "", "authenticated"), jwks=None)
        claims = mv.verify(mint_token("multi@reglens.local"))
        assert claims["email"] == "multi@reglens.local"

    def test_asymmetric_alg_without_jwks_is_rejected(self):
        mv = MultiVerifier(HS256Verifier(TEST_SECRET, "", "authenticated"), jwks=None)
        with pytest.raises(pyjwt.InvalidAlgorithmError):
            mv.verify(_token_with_alg("RS256"))

    def test_unknown_alg_is_rejected(self):
        mv = MultiVerifier(HS256Verifier(TEST_SECRET, "", "authenticated"), jwks=None)
        with pytest.raises(pyjwt.InvalidAlgorithmError):
            mv.verify(_token_with_alg("none"))


async def _cleanup_user(email: str) -> None:
    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user:
            await session.execute(delete(Tenant).where(Tenant.id == user.tenant_id))
            await session.commit()


class TestAuthRejection:
    async def test_missing_token(self, client):
        resp = await client.get("/api/v1/conversations")
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"

    async def test_garbage_token(self, client):
        resp = await client.get(
            "/api/v1/conversations", headers={"Authorization": "Bearer not.a.jwt"}
        )
        assert resp.status_code == 401

    async def test_expired_token(self, client):
        token = mint_token(expires_in=-3600)
        resp = await client.get(
            "/api/v1/conversations", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401
        assert "ExpiredSignature" in resp.json()["detail"]

    async def test_wrong_signature(self, client):
        token = mint_token(secret="wrong-secret")
        resp = await client.get(
            "/api/v1/conversations", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401

    async def test_wrong_audience(self, client):
        token = mint_token(audience="other-app")
        resp = await client.get(
            "/api/v1/conversations", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401

    async def test_chat_requires_auth(self, client):
        resp = await client.post("/api/v1/chat", json={"question": "What is Art. 6?"})
        assert resp.status_code == 401


class TestProvisioning:
    async def test_first_request_provisions_user_and_tenant(self, client, db_available):
        email = f"jit-{uuid.uuid4().hex[:8]}@reglens.local"
        headers = {"Authorization": f"Bearer {mint_token(email)}"}
        try:
            resp = await client.get("/api/v1/conversations", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == []

            async with get_sessionmaker()() as session:
                user = await session.scalar(select(User).where(User.email == email))
                assert user is not None
                tenant = await session.get(Tenant, user.tenant_id)
                assert tenant is not None and tenant.name == email

            # Second request must reuse the same identity, not re-provision.
            resp2 = await client.get("/api/v1/conversations", headers=headers)
            assert resp2.status_code == 200
            async with get_sessionmaker()() as session:
                users = (await session.scalars(select(User).where(User.email == email))).all()
                assert len(users) == 1
        finally:
            await _cleanup_user(email)

    async def test_unknown_tenant_claim_rejected(self, client, db_available):
        import jwt as pyjwt

        from tests.conftest import TEST_SECRET

        claims = {
            "sub": str(uuid.uuid4()),
            "email": "tenantclaim@reglens.local",
            "aud": "authenticated",
            "exp": 4102444800,
            "app_metadata": {"tenant_id": str(uuid.uuid4())},
        }
        token = pyjwt.encode(claims, TEST_SECRET, algorithm="HS256")
        resp = await client.get(
            "/api/v1/conversations", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401
        assert "unknown tenant" in resp.json()["detail"]


class TestTenantIsolation:
    async def test_conversation_not_visible_across_tenants(self, client, db_available):
        email_a = f"iso-a-{uuid.uuid4().hex[:8]}@reglens.local"
        email_b = f"iso-b-{uuid.uuid4().hex[:8]}@reglens.local"
        headers_a = {"Authorization": f"Bearer {mint_token(email_a)}"}
        headers_b = {"Authorization": f"Bearer {mint_token(email_b)}"}
        try:
            # Provision both users, then create a conversation for tenant A directly.
            await client.get("/api/v1/conversations", headers=headers_a)
            await client.get("/api/v1/conversations", headers=headers_b)
            from app.db.models import Conversation

            async with get_sessionmaker()() as session:
                user_a = await session.scalar(select(User).where(User.email == email_a))
                conv = Conversation(tenant_id=user_a.tenant_id, user_id=user_a.id, title="secret")
                session.add(conv)
                await session.commit()
                conv_id = conv.id

            resp_a = await client.get(f"/api/v1/conversations/{conv_id}", headers=headers_a)
            assert resp_a.status_code == 200
            resp_b = await client.get(f"/api/v1/conversations/{conv_id}", headers=headers_b)
            assert resp_b.status_code == 404
        finally:
            await _cleanup_user(email_a)
            await _cleanup_user(email_b)
