"""Per-tenant sliding-window rate limiting on Redis.

A single atomic Lua script keeps the window (a ZSET of request timestamps)
consistent under concurrency: prune expired entries, count, then either admit
and record the request or compute when the oldest entry leaves the window.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.config import get_settings
from app.core.security import AuthContext, get_current_user
from app.services.redis import get_redis

_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, window)
  return {1, limit - count - 1, 0}
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
return {0, 0, tonumber(oldest[2]) + window - now}
"""


@dataclass
class RateDecision:
    allowed: bool
    remaining: int
    retry_after_ms: int


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_ms: int = 60_000) -> None:
        self.limit = limit
        self.window_ms = window_ms
        self._script = get_redis().register_script(_SLIDING_WINDOW_LUA)

    async def check(self, key: str) -> RateDecision:
        now_ms = time.time_ns() // 1_000_000
        allowed, remaining, retry_after = await self._script(
            keys=[f"rl:{key}"],
            args=[now_ms, self.window_ms, self.limit, f"{now_ms}:{uuid.uuid4().hex[:8]}"],
        )
        return RateDecision(bool(allowed), int(remaining), int(retry_after))


_limiter: SlidingWindowLimiter | None = None


def _get_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowLimiter(limit=get_settings().rate_limit_rpm)
    return _limiter


async def rate_limited_user(
    auth: Annotated[AuthContext, Depends(get_current_user)],
) -> AuthContext:
    """Auth + rate limit in one dependency; returns the auth context when admitted."""
    limiter = _get_limiter()
    decision = await limiter.check(str(auth.tenant_id))
    if not decision.allowed:
        retry_s = max(1, decision.retry_after_ms // 1000)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this workspace",
            headers={
                "Retry-After": str(retry_s),
                "X-RateLimit-Limit": str(limiter.limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    return auth
