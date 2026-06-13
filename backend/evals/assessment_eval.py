"""Scenario evaluation for the assessment agent, through the real engine.

Runs the full staged pipeline (profile → classification → obligation mapping →
gaps → remediation → report) for every golden scenario, diffs the per-rule
verdicts against the scenario's expected verdicts, and aggregates into the A4
gates:

- ``verdict_accuracy`` — fraction of asserted (scenario, rule) verdicts the
  engine matched. The per-rule regression gate.
- ``blocker_recall`` — fraction of expected prohibited-practice (blocker)
  verdicts the engine caught. The hard safety gate: any miss fails CI.
- ``injection_resistance`` — ``verdict_accuracy`` restricted to scenarios whose
  description embeds a prompt-injection attempt; the engine must classify on
  the facts, not the injected instruction.

Per-rule accuracy is reported as a diagnostic, not gated: with ~1–2 scenarios
per rule its granularity is too coarse for a meaningful per-rule threshold, so
the aggregate gate plus the blocker hard gate are what protect quality.
"""

import asyncio
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessments.engine import run_assessment
from app.assessments.rulebook import load_rulebook
from app.assessments.schema import Rulebook
from app.core.config import get_settings
from app.db.models import Assessment, Tenant, User
from app.services.llm import ChatClient
from evals.scenarios import AssessmentScenario

log = structlog.get_logger()

# Each scenario is a full ~15–25-call pipeline; keep concurrency low so a run
# stays well under provider rate limits.
CONCURRENCY = 3
EVAL_TENANT = "eval-assessments"
EVAL_EMAIL = "assess-eval@reglens.local"


@dataclass
class ScenarioResult:
    scenario_id: str
    category: str
    status: str  # complete | failed
    expected: dict[str, str]
    actual: dict[str, str]
    mismatches: list[tuple[str, str, str]]  # (rule_id, expected, got)
    expected_blockers: list[str]
    missed_blockers: list[str]
    total_tokens: int = 0
    cost_usd: float = 0.0


def _blocker_ids(rulebook: Rulebook) -> set[str]:
    return {r.id for r in rulebook.rules if r.on_applies.severity == "blocker"}


async def _eval_identity(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessionmaker() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == EVAL_TENANT))
        if tenant is None:
            tenant = Tenant(name=EVAL_TENANT)
            session.add(tenant)
            await session.flush()
        user_id = uuid.uuid5(uuid.NAMESPACE_DNS, EVAL_EMAIL)
        if await session.get(User, user_id) is None:
            session.add(User(id=user_id, tenant_id=tenant.id, email=EVAL_EMAIL))
        await session.commit()
        return tenant.id, user_id


async def _eval_one(
    scenario: AssessmentScenario,
    sessionmaker: async_sessionmaker[AsyncSession],
    llm: ChatClient,
    blocker_llm: ChatClient,
    blocker_ids: set[str],
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    sem: asyncio.Semaphore,
) -> ScenarioResult:
    async with sem:
        expected: dict[str, str] = {k: str(v) for k, v in scenario.expected_verdicts.items()}
        expected_blockers = [r for r, v in expected.items() if v == "applies" and r in blocker_ids]
        actual: dict[str, str] = {}
        status = "complete"
        tokens = 0
        cost = 0.0
        try:
            async with sessionmaker() as session:
                assessment = Assessment(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    title=scenario.title,
                    description=scenario.description,
                )
                session.add(assessment)
                await session.commit()
                async for event in run_assessment(
                    session,
                    assessment,
                    llm_complete=llm.complete,
                    blocker_complete=blocker_llm.complete,
                    allow_clarification=False,
                ):
                    if event.event == "finding":
                        actual[str(event.data["rule_id"])] = str(event.data["verdict"])
                    elif event.event == "assessment_completed":
                        usage = event.data.get("usage")
                        if isinstance(usage, dict):
                            tokens = int(usage.get("total_tokens") or 0)
                        c = event.data.get("cost_usd")
                        cost = float(c) if isinstance(c, int | float) else 0.0
                    elif event.event == "error":
                        status = "failed"
        except Exception:
            log.exception("scenario_eval_failed", scenario=scenario.id)
            status = "failed"

        mismatches = [
            (rid, want, actual.get(rid, "<missing>"))
            for rid, want in sorted(expected.items())
            if actual.get(rid) != want
        ]
        missed = [b for b in expected_blockers if actual.get(b) != "applies"]
        return ScenarioResult(
            scenario_id=scenario.id,
            category=scenario.category,
            status=status,
            expected=expected,
            actual=actual,
            mismatches=mismatches,
            expected_blockers=expected_blockers,
            missed_blockers=missed,
            total_tokens=tokens,
            cost_usd=cost,
        )


def aggregate(results: list[ScenarioResult], rulebook: Rulebook) -> dict:
    """Pure reduction of per-scenario results into the A4 gate metrics.

    Kept free of DB/LLM so the gate arithmetic — especially blocker recall —
    is unit-tested deterministically.
    """
    blocker_ids = _blocker_ids(rulebook)
    total = matched = 0
    inj_total = inj_matched = 0
    blk_expected = blk_caught = blk_false_clear = 0
    per_rule: dict[str, list[int]] = {}  # rule_id -> [matched, total]

    for r in results:
        for rid, want in r.expected.items():
            ok = 1 if r.actual.get(rid) == want else 0
            total += 1
            matched += ok
            stat = per_rule.setdefault(rid, [0, 0])
            stat[0] += ok
            stat[1] += 1
            if r.category == "injection":
                inj_total += 1
                inj_matched += ok
            if want == "applies" and rid in blocker_ids:
                blk_expected += 1
                got = r.actual.get(rid)
                blk_caught += 1 if got == "applies" else 0
                # The catastrophic error: a prohibited practice silently cleared.
                # needs_info is a safe flag for review, not a false clear.
                blk_false_clear += 1 if got == "does_not_apply" else 0

    per_rule_acc = {rid: round(m / t, 3) for rid, (m, t) in per_rule.items()}
    worst = sorted(per_rule_acc.items(), key=lambda kv: kv[1])[:5]
    completed = [r for r in results if r.status == "complete"]

    return {
        "n_scenarios": len(results),
        "engine_failures": [r.scenario_id for r in results if r.status == "failed"],
        "verdict_accuracy": round(matched / total, 4) if total else None,
        # Hard safety gate: a prohibited practice is never cleared as
        # does_not_apply when it applies. Quality gate: positive-catch recall.
        "blocker_false_clear_rate": (
            round(blk_false_clear / blk_expected, 4) if blk_expected else 0.0
        ),
        "blocker_recall": round(blk_caught / blk_expected, 4) if blk_expected else 1.0,
        "blockers_expected": blk_expected,
        "blockers_caught": blk_caught,
        "blocker_false_clears": [
            {"scenario": r.scenario_id, "rule": b, "got": r.actual.get(b, "<missing>")}
            for r in results
            for b in r.expected_blockers
            if r.actual.get(b) == "does_not_apply"
        ],
        "missed_blockers": [
            {"scenario": r.scenario_id, "rule": b} for r in results for b in r.missed_blockers
        ],
        "injection_resistance": round(inj_matched / inj_total, 4) if inj_total else None,
        "injection_verdicts": inj_total,
        "verdict_mismatches": [
            {"scenario": r.scenario_id, "rule": rid, "expected": w, "got": g}
            for r in results
            for (rid, w, g) in r.mismatches
        ],
        "worst_rules": [{"rule": rid, "accuracy": acc} for rid, acc in worst],
        "avg_tokens": (
            round(sum(r.total_tokens for r in completed) / len(completed)) if completed else 0
        ),
        "total_cost_usd": round(sum(r.cost_usd for r in results), 4),
        "avg_cost_usd": (
            round(sum(r.cost_usd for r in completed) / len(completed), 5) if completed else 0.0
        ),
    }


async def run_assessment_eval(
    sessionmaker: async_sessionmaker[AsyncSession],
    scenarios: list[AssessmentScenario],
    *,
    generation_model: str | None = None,
) -> tuple[list[ScenarioResult], dict]:
    settings = get_settings()
    rulebook = load_rulebook()
    blocker_ids = _blocker_ids(rulebook)
    tenant_id, user_id = await _eval_identity(sessionmaker)
    llm = ChatClient(generation_model)
    blocker_llm = ChatClient(settings.assessment_blocker_model or settings.judge_model)
    sem = asyncio.Semaphore(CONCURRENCY)
    try:
        results = await asyncio.gather(
            *(
                _eval_one(s, sessionmaker, llm, blocker_llm, blocker_ids, tenant_id, user_id, sem)
                for s in scenarios
            )
        )
    finally:
        await llm.aclose()
        await blocker_llm.aclose()
    return list(results), aggregate(list(results), rulebook)
