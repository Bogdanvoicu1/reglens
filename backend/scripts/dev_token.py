"""Mint a local development JWT (HS256) compatible with the API's auth layer.

Requires REGLENS_SUPABASE_JWT_SECRET in the environment / .env. The subject is
derived deterministically from the email, so repeated runs map to the same
user and tenant.

Usage:
    uv run python scripts/dev_token.py [--email you@example.com] [--hours 24]
"""

import argparse
import time
import uuid

import jwt

from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="dev@reglens.local")
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.supabase_jwt_secret:
        raise SystemExit("Set REGLENS_SUPABASE_JWT_SECRET in backend/.env first")

    now = int(time.time())
    claims = {
        "sub": str(uuid.uuid5(uuid.NAMESPACE_DNS, args.email)),
        "email": args.email,
        "aud": settings.supabase_audience,
        "iat": now,
        "exp": now + args.hours * 3600,
        "role": "authenticated",
    }
    if settings.supabase_issuer:
        claims["iss"] = settings.supabase_issuer
    print(jwt.encode(claims, settings.supabase_jwt_secret, algorithm="HS256"))


if __name__ == "__main__":
    main()
