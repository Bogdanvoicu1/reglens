"""RAG-specific Prometheus metrics, recorded once per chat request."""

from prometheus_client import Counter, Histogram

CHAT_REQUESTS = Counter(
    "reglens_chat_requests_total",
    "Chat requests by outcome",
    ["outcome"],  # ok | cached | refused_pre | refusal | citation_error | no_citations | error
)
CHAT_LATENCY = Histogram(
    "reglens_chat_duration_seconds",
    "End-to-end chat latency",
    buckets=(0.05, 0.25, 0.5, 1, 2, 4, 8, 16, 30),
)
RETRIEVAL_TOP_SCORE = Histogram(
    "reglens_retrieval_top_score",
    "Fused RRF score of the best retrieved chunk",
    buckets=(0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05),
)
LLM_TOKENS = Counter(
    "reglens_llm_tokens_total",
    "LLM tokens consumed",
    ["kind"],  # prompt | completion
)
LLM_COST = Counter("reglens_llm_cost_usd_total", "LLM spend in USD (as reported by the provider)")
CACHE_EVENTS = Counter(
    "reglens_answer_cache_events_total",
    "Answer cache lookups",
    ["result"],  # hit | miss
)
ASSESSMENT_RUNS = Counter(
    "reglens_assessment_runs_total",
    "Assessment runs by terminal outcome",
    ["outcome"],  # complete | blocked | clarifying | failed
)
ASSESSMENT_COST = Histogram(
    "reglens_assessment_cost_usd",
    "Provider-reported USD cost per completed assessment run",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.15, 0.25, 0.5),
)
ASSESSMENT_TOKENS = Histogram(
    "reglens_assessment_tokens",
    "Total tokens per completed assessment run",
    buckets=(5_000, 10_000, 20_000, 40_000, 80_000, 160_000),
)


def record_chat(outcome: str, latency_s: float, usage: dict | None = None) -> None:
    CHAT_REQUESTS.labels(outcome).inc()
    CHAT_LATENCY.observe(latency_s)
    if usage:
        if usage.get("prompt_tokens"):
            LLM_TOKENS.labels("prompt").inc(usage["prompt_tokens"])
        if usage.get("completion_tokens"):
            LLM_TOKENS.labels("completion").inc(usage["completion_tokens"])
        # OpenRouter reports per-request cost; OpenAI-direct responses won't.
        if usage.get("cost"):
            LLM_COST.inc(float(usage["cost"]))


def record_assessment(
    outcome: str, *, usage: dict[str, int] | None = None, cost_usd: float = 0.0
) -> None:
    """Record one assessment run's terminal outcome and (when completed) its
    token/cost footprint. Token and cost totals also feed the shared LLM spend
    counters so dashboards reflect total spend across chat and assessments."""
    ASSESSMENT_RUNS.labels(outcome).inc()
    if usage:
        if usage.get("total_tokens"):
            ASSESSMENT_TOKENS.observe(usage["total_tokens"])
        if usage.get("prompt_tokens"):
            LLM_TOKENS.labels("prompt").inc(usage["prompt_tokens"])
        if usage.get("completion_tokens"):
            LLM_TOKENS.labels("completion").inc(usage["completion_tokens"])
    if cost_usd:
        ASSESSMENT_COST.observe(cost_usd)
        LLM_COST.inc(cost_usd)
