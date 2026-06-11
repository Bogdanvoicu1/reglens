from prometheus_client import REGISTRY

from app.observability.rag_metrics import record_chat
from app.observability.tracing import ChatTrace, get_langfuse


class TestSecurityHeaders:
    async def test_headers_present(self, client):
        resp = await client.get("/healthz")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "no-referrer"


class TestBodyLimit:
    async def test_oversized_body_rejected(self, client):
        resp = await client.post(
            "/api/v1/chat",
            content=b"x" * 70_000,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413
        assert resp.headers["content-type"] == "application/problem+json"


class TestProblemJson:
    async def test_404_problem_shape(self, client):
        resp = await client.get("/api/v1/nope")
        assert resp.status_code == 404
        body = resp.json()
        assert {"type", "title", "status", "detail", "request_id"} <= set(body)

    async def test_422_includes_field_location(self, client, db_available):
        from tests.conftest import mint_token

        resp = await client.post(
            "/api/v1/chat",
            json={"question": "x"},
            headers={"Authorization": f"Bearer {mint_token()}"},
        )
        assert resp.status_code == 422
        assert "question" in resp.json()["detail"]

    async def test_429_keeps_retry_after_header(self, client, db_available, redis_available):
        # Exhaust the limiter for a dedicated tenant.
        import app.services.rate_limit as rl
        from tests.conftest import mint_token

        original = rl._limiter
        rl._limiter = rl.SlidingWindowLimiter(limit=1, window_ms=60_000)
        try:
            headers = {"Authorization": f"Bearer {mint_token('ratelimit@reglens.local')}"}
            await client.post("/api/v1/chat", json={"question": "first"}, headers=headers)
            resp = await client.post("/api/v1/chat", json={"question": "second"}, headers=headers)
            assert resp.status_code == 429
            assert "retry-after" in resp.headers
            assert resp.json()["title"] == "Too Many Requests"
        finally:
            rl._limiter = original


def _counter_value(name: str, labels: dict) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestRagMetrics:
    def test_record_chat_increments_counters(self):
        before = _counter_value("reglens_chat_requests_total", {"outcome": "ok"})
        tokens_before = _counter_value("reglens_llm_tokens_total", {"kind": "prompt"})
        record_chat("ok", 1.5, {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0005})
        assert _counter_value("reglens_chat_requests_total", {"outcome": "ok"}) == before + 1
        assert _counter_value("reglens_llm_tokens_total", {"kind": "prompt"}) == tokens_before + 100
        assert _counter_value("reglens_llm_cost_usd_total", {}) > 0


class TestTracingFlag:
    def test_disabled_without_keys(self):
        get_langfuse.cache_clear()
        assert get_langfuse() is None

    def test_chat_trace_is_noop_when_disabled(self):
        trace = ChatTrace("q", "u", "t")
        span = trace.retrieval("q")
        span.end([{"ref": "Art. 6"}])
        gen = trace.generation("model", [])
        gen.end("answer", {"prompt_tokens": 1})
        trace.end({"status": "ok"})  # nothing raises
