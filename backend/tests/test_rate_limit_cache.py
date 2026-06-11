import uuid

from app.services.answer_cache import cache_key, normalize_question
from app.services.rate_limit import SlidingWindowLimiter


class TestRateLimiter:
    async def test_sliding_window_admits_then_blocks(self, redis_available):
        limiter = SlidingWindowLimiter(limit=3, window_ms=60_000)
        key = f"test:{uuid.uuid4().hex}"
        decisions = [await limiter.check(key) for _ in range(4)]
        assert [d.allowed for d in decisions] == [True, True, True, False]
        assert decisions[0].remaining == 2
        assert decisions[3].retry_after_ms > 0

    async def test_keys_are_isolated(self, redis_available):
        limiter = SlidingWindowLimiter(limit=1, window_ms=60_000)
        a, b = f"test:{uuid.uuid4().hex}", f"test:{uuid.uuid4().hex}"
        assert (await limiter.check(a)).allowed
        assert (await limiter.check(b)).allowed
        assert not (await limiter.check(a)).allowed


class TestAnswerCache:
    def test_normalization(self):
        assert normalize_question("  What IS  Art. 6?\n") == "what is art. 6?"

    def test_key_binds_question_and_fingerprint(self):
        k1 = cache_key("What is Art. 6?", "gdpr@v1", 8)
        assert k1 == cache_key("what is   art. 6?", "gdpr@v1", 8)
        assert k1 != cache_key("What is Art. 6?", "gdpr@v2", 8)
        assert k1 != cache_key("What is Art. 6?", "gdpr@v1", 5)

    async def test_roundtrip(self, redis_available):
        from app.services.answer_cache import get_cached_answer, set_cached_answer

        key = f"ans:test-{uuid.uuid4().hex}"
        assert await get_cached_answer(key) is None
        await set_cached_answer(key, {"answer": "x", "sources": [], "citations": {"cited": []}})
        cached = await get_cached_answer(key)
        assert cached is not None and cached["answer"] == "x"
