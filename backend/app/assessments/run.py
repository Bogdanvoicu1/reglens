"""Development CLI for the assessment engine.

Usage:
    python -m app.assessments.run --scenario cv-screening-saas
    python -m app.assessments.run --file description.txt --title "My system"
    python -m app.assessments.run --list-scenarios

Runs the real pipeline (DB + LLM) under a local dev tenant. With --scenario,
the run's verdicts are diffed against the scenario's expected verdicts and
the process exits non-zero on any mismatch — the tight dev loop behind the
A4 per-rule eval gates.
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessments.engine import run_assessment
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Assessment, Tenant, User
from app.db.session import get_session
from app.services.llm import ChatClient
from evals.scenarios import load_scenarios

CLI_EMAIL = "cli@reglens.local"


async def _cli_identity(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = await session.scalar(select(Tenant).where(Tenant.name == "cli-dev"))
    if tenant is None:
        tenant = Tenant(name="cli-dev")
        session.add(tenant)
        await session.flush()
    user_id = uuid.uuid5(uuid.NAMESPACE_DNS, CLI_EMAIL)
    if await session.get(User, user_id) is None:
        session.add(User(id=user_id, tenant_id=tenant.id, email=CLI_EMAIL))
    await session.commit()
    return tenant.id, user_id


def _print_event(event: str, data: dict[str, Any]) -> None:
    if event == "stage_started":
        print(f"\n── {data['stage']} " + "─" * (56 - len(data["stage"])))
    elif event == "profile":
        print(f"profile: {data['profile']['summary']}")
        for unknown in data["unknowns"]:
            print(f"  ? {unknown}")
    elif event == "finding":
        confidence = f"{data['confidence']:.2f}" if data["confidence"] is not None else "  — "
        severity = f"  [{data['severity']}]" if data.get("severity") else ""
        print(f"{data['verdict']:>15}  {confidence}  {data['rule_id']}{severity}")
    elif event == "assessment_completed":
        usage = data.get("usage", {})
        print(
            f"\ncomplete: {data['verdict_counts']}  blockers={data['blockers']}"
            f"  tokens={usage.get('total_tokens', 0)}"
        )
    elif event == "error":
        print(f"\nERROR: {data['message']}", file=sys.stderr)


def _diff_expected(expected: dict[str, str], actual: dict[str, str]) -> int:
    mismatches = [
        (rule_id, want, actual.get(rule_id, "<missing>"))
        for rule_id, want in sorted(expected.items())
        if actual.get(rule_id) != want
    ]
    print(f"\nscenario check: {len(expected) - len(mismatches)}/{len(expected)} verdicts match")
    for rule_id, want, got in mismatches:
        print(f"  MISMATCH {rule_id}: expected {want}, got {got}")
    return len(mismatches)


async def _run(args: argparse.Namespace) -> int:
    expected: dict[str, str] | None = None
    if args.scenario:
        scenario = next((s for s in load_scenarios().scenarios if s.id == args.scenario), None)
        if scenario is None:
            print(f"unknown scenario: {args.scenario}", file=sys.stderr)
            return 2
        title, description = scenario.title, scenario.description
        expected = dict(scenario.expected_verdicts)
    else:
        description = Path(args.file).read_text().strip()
        title = args.title or description[:120]

    client = ChatClient(model=args.generation_model)
    failed = False
    actual: dict[str, str] = {}
    try:
        async for session in get_session():
            tenant_id, user_id = await _cli_identity(session)
            assessment = Assessment(
                tenant_id=tenant_id, user_id=user_id, title=title, description=description
            )
            session.add(assessment)
            await session.commit()
            print(f"assessment {assessment.id}: {title}")

            async for event in run_assessment(session, assessment, llm_complete=client.complete):
                _print_event(event.event, event.data)
                if event.event == "finding":
                    actual[str(event.data["rule_id"])] = str(event.data["verdict"])
                failed = failed or event.event == "error"
    finally:
        await client.aclose()

    if failed:
        return 1
    if expected is not None:
        return 1 if _diff_expected(expected, actual) else 0
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.assessments.run", description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scenario", help="run a scenario from evals/assessment_scenarios.json")
    source.add_argument("--file", help="path to a plain-text system description")
    source.add_argument("--list-scenarios", action="store_true")
    parser.add_argument("--title", default="", help="assessment title (with --file)")
    parser.add_argument("--generation-model", default=None, help="override the stage model")
    args = parser.parse_args()

    if args.list_scenarios:
        for s in load_scenarios().scenarios:
            print(f"{s.id:32} {s.title}")
        return

    configure_logging(get_settings().log_level)
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
