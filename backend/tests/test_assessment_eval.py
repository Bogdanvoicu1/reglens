"""Unit tests for the A4 assessment-eval aggregation and metrics.

These exercise the gate arithmetic without a DB or LLM — especially blocker
recall, the hard safety gate — so a regression in the math fails fast in plain
CI rather than only in the on-demand live suite.
"""

import pytest
from prometheus_client import REGISTRY

from app.assessments.rulebook import load_rulebook
from app.observability.rag_metrics import record_assessment
from evals.assessment_eval import ScenarioResult, aggregate

BLOCKER = "aia-prohibited-emotion-workplace"  # a real prohibited-practice rule


@pytest.fixture(scope="module")
def rulebook():
    return load_rulebook()


def _result(
    sid: str,
    category: str,
    expected: dict[str, str],
    actual: dict[str, str],
    *,
    status: str = "complete",
    tokens: int = 10_000,
    cost: float = 0.01,
) -> ScenarioResult:
    blockers = [r for r, v in expected.items() if v == "applies" and r == BLOCKER]
    mism = [
        (r, w, actual.get(r, "<missing>"))
        for r, w in sorted(expected.items())
        if actual.get(r) != w
    ]
    missed = [b for b in blockers if actual.get(b) != "applies"]
    return ScenarioResult(
        sid, category, status, expected, actual, mism, blockers, missed, tokens, cost
    )


def test_all_correct_passes_every_gate(rulebook):
    std = _result(
        "std",
        "standard",
        {"aia-is-ai-system": "applies", BLOCKER: "applies"},
        {"aia-is-ai-system": "applies", BLOCKER: "applies"},
    )
    inj = _result(
        "inj", "injection", {"aia-is-ai-system": "applies"}, {"aia-is-ai-system": "applies"}
    )
    m = aggregate([std, inj], rulebook)
    assert m["verdict_accuracy"] == 1.0
    assert m["blocker_recall"] == 1.0
    assert m["blocker_false_clear_rate"] == 0.0
    assert m["injection_resistance"] == 1.0
    assert m["missed_blockers"] == [] and m["blocker_false_clears"] == []
    assert m["blockers_expected"] == 1 and m["blockers_caught"] == 1
    assert m["avg_cost_usd"] == 0.01 and m["avg_tokens"] == 10_000


def test_false_clear_trips_the_hard_gate(rulebook):
    """The catastrophic error: a prohibited practice cleared as does_not_apply
    when it applies. It must register as a false clear and drop recall."""
    miss = _result("cleared", "standard", {BLOCKER: "applies"}, {BLOCKER: "does_not_apply"})
    m = aggregate([miss], rulebook)
    assert m["blocker_false_clear_rate"] == 1.0  # the hard gate (max 0.0) fails
    assert m["blocker_recall"] == 0.0
    assert {"scenario": "cleared", "rule": BLOCKER, "got": "does_not_apply"} in m[
        "blocker_false_clears"
    ]


def test_needs_info_flags_without_false_clear(rulebook):
    """The two-tier distinction: needs_info on a blocker is a safe flag for
    review, so it drops recall but does NOT count as a false clear."""
    flagged = _result("hedged", "injection", {BLOCKER: "applies"}, {BLOCKER: "needs_info"})
    m = aggregate([flagged], rulebook)
    assert m["blocker_recall"] < 1.0  # not positively caught
    assert m["blocker_false_clear_rate"] == 0.0  # but never falsely cleared
    assert m["blocker_false_clears"] == []
    assert {"scenario": "hedged", "rule": BLOCKER} in m["missed_blockers"]


def test_injection_resistance_counts_only_injection_scenarios(rulebook):
    std = _result(
        "std",
        "standard",
        {"aia-is-ai-system": "applies"},
        {"aia-is-ai-system": "applies"},
    )
    inj = _result(
        "inj",
        "injection",
        {"aia-is-ai-system": "applies", "aia-eu-market": "applies"},
        {"aia-is-ai-system": "applies", "aia-eu-market": "does_not_apply"},
    )
    m = aggregate([std, inj], rulebook)
    assert m["injection_resistance"] == 0.5  # only the injection scenario, 1 of 2
    assert m["verdict_accuracy"] == 0.6667  # 2 of 3 verdicts across both
    assert m["injection_verdicts"] == 2


def test_engine_failure_counts_as_missed_verdicts(rulebook):
    failed = _result(
        "boom",
        "standard",
        {"aia-is-ai-system": "applies", BLOCKER: "applies"},
        {},  # crashed before any finding
        status="failed",
    )
    m = aggregate([failed], rulebook)
    assert m["engine_failures"] == ["boom"]
    assert m["verdict_accuracy"] == 0.0
    assert m["blocker_recall"] == 0.0  # the blocker was never caught
    assert m["avg_tokens"] == 0 and m["avg_cost_usd"] == 0.0  # no completed runs


def test_worst_rules_surfaces_consistently_wrong_rule(rulebook):
    results = [
        _result(
            f"s{i}",
            "standard",
            {"aia-is-ai-system": "applies"},
            {"aia-is-ai-system": "does_not_apply"},
        )
        for i in range(3)
    ]
    m = aggregate(results, rulebook)
    worst = {w["rule"]: w["accuracy"] for w in m["worst_rules"]}
    assert worst.get("aia-is-ai-system") == 0.0


def test_record_assessment_increments_counters():
    def runs(outcome: str) -> float:
        return (
            REGISTRY.get_sample_value("reglens_assessment_runs_total", {"outcome": outcome}) or 0.0
        )

    def cost_count() -> float:
        return REGISTRY.get_sample_value("reglens_assessment_cost_usd_count") or 0.0

    before_runs, before_cost = runs("complete"), cost_count()
    record_assessment(
        "complete",
        usage={"prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000},
        cost_usd=0.012,
    )
    assert runs("complete") == before_runs + 1
    assert cost_count() == before_cost + 1
    # Outcome-only terminal events (no usage) still count, without touching cost.
    before_failed = runs("failed")
    record_assessment("failed")
    assert runs("failed") == before_failed + 1
