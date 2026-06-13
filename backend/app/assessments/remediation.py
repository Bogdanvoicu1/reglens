"""Stage 5 — remediation & tradeoffs.

Turns the blockers and the unmet obligations into an actionable roadmap:
each item says what to do, how urgent (priority), how big (effort), which
needs it addresses, and the real tradeoffs involved. The set of *needs* is
computed deterministically — every blocker plus every obligation whose gap
status is not "met" — and coverage is enforced: an item must address each
need. If the model's output cannot be validated, a deterministic item is
synthesised per uncovered need, so a blocker can never silently drop out of
the roadmap (the safety property the eval suite gates on).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from app.assessments.gaps import GapFinding
from app.assessments.llm_json import LLMComplete, StageOutputError, complete_json
from app.assessments.mapping import SEVERITY_ORDER, MappedObligation

log = structlog.get_logger()

Priority = Literal["blocker", "high", "medium", "low"]
Effort = Literal["S", "M", "L"]

# Severity of the driving need → default roadmap priority.
SEVERITY_PRIORITY: dict[str, Priority] = {
    "blocker": "blocker",
    "pre-market": "high",
    "operational": "medium",
    "informational": "low",
}

REMEDIATION_SYSTEM_PROMPT = """\
You produce a compliance remediation roadmap from a list of needs (blockers \
to resolve and obligations that are not yet met).

Rules:
1. Produce concrete, actionable items. Each item addresses one or more needs \
by their exact "key".
2. Together, the items must address EVERY need given — leave none uncovered. \
You may group related needs into one item.
3. "priority": use "blocker" ONLY for an item that addresses a need whose \
kind is "blocker" (a prohibited practice). Everything else is "high", \
"medium", or "low" by urgency (pre-market gaps → "high").
4. "effort": rough size — "S" (days), "M" (weeks), "L" (months).
5. "tradeoffs": the real cost, risk, or design tension the item introduces \
(1-2 sentences). If genuinely none, say so briefly.
6. "addresses": the list of need keys this item resolves; use keys EXACTLY \
as given.
7. Reply with ONLY a JSON object — no prose, no code fences:
{"items": [{"title": str, "description": str, "priority": str, "effort": \
str, "addresses": [str, ...], "tradeoffs": str}, ...]}"""


@dataclass
class RemediationNeed:
    key: str  # blocker rule_id or obligation_id
    kind: str  # "blocker" | "obligation"
    title: str
    detail: str
    severity: str


class RemediationItem(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=3000)
    priority: Priority
    effort: Effort
    addresses: list[str] = Field(min_length=1)
    tradeoffs: str = Field(min_length=1, max_length=2000)


class RemediationPlan(BaseModel):
    items: list[RemediationItem]


def collect_needs(
    blockers: list[tuple[str, str]],
    obligations: list[MappedObligation],
    gaps: list[GapFinding],
) -> list[RemediationNeed]:
    """Blockers first, then non-met obligations strongest-severity first."""
    needs: list[RemediationNeed] = [
        RemediationNeed(
            key=rule_id, kind="blocker", title=detail, detail=detail, severity="blocker"
        )
        for rule_id, detail in blockers
    ]
    gap_by_id = {g.obligation_id: g for g in gaps}
    for m in obligations:
        gap = gap_by_id.get(m.obligation.id)
        if gap is None or gap.status == "met":
            continue
        needs.append(
            RemediationNeed(
                key=m.obligation.id,
                kind="obligation",
                title=m.obligation.title,
                detail=f"[{gap.status}] {m.obligation.summary} — {gap.reasoning}",
                severity=m.severity,
            )
        )
    needs.sort(key=lambda n: -SEVERITY_ORDER[n.severity])
    return needs


def build_remediation_messages(needs: list[RemediationNeed]) -> list[dict[str, str]]:
    lines = [
        f"- key: {n.key}\n  kind: {n.kind}\n  severity: {n.severity}\n  detail: {n.detail}"
        for n in needs
    ]
    return [
        {"role": "system", "content": REMEDIATION_SYSTEM_PROMPT},
        {"role": "user", "content": "## Needs\n" + "\n".join(lines)},
    ]


def make_remediation_validator(need_keys: set[str]) -> Callable[[RemediationPlan], None]:
    def validate(plan: RemediationPlan) -> None:
        addressed = {key for item in plan.items for key in item.addresses}
        unknown = addressed - need_keys
        if unknown:
            raise ValueError(f"addresses reference unknown need keys: {sorted(unknown)}")
        uncovered = need_keys - addressed
        if uncovered:
            raise ValueError(f"these needs are not addressed by any item: {sorted(uncovered)}")

    return validate


def _synthesise_item(need: RemediationNeed) -> RemediationItem:
    if need.kind == "blocker":
        return RemediationItem(
            title=f"Resolve prohibited practice ({need.key})",
            description=(
                "This practice is prohibited under the EU AI Act and must be removed or "
                "fundamentally redesigned before the system can be placed on the EU market "
                "or put into service. Obtain legal review."
            ),
            priority="blocker",
            effort="L",
            addresses=[need.key],
            tradeoffs="May require dropping or re-architecting a core capability.",
        )
    return RemediationItem(
        title=f"Address: {need.title}",
        description=(f"Close this gap to satisfy the obligation. Current status — {need.detail}")[
            :3000
        ],
        priority=SEVERITY_PRIORITY[need.severity],
        effort="M",
        addresses=[need.key],
        tradeoffs="Requires process and/or engineering effort; scope with a specialist.",
    )


def _clamp_priorities(
    items: list[RemediationItem], blocker_keys: set[str]
) -> list[RemediationItem]:
    """Enforce the taxonomy: 'blocker' priority is reserved for items that
    actually address a prohibited-practice need, regardless of what the model
    chose."""
    for item in items:
        if item.priority == "blocker" and not (set(item.addresses) & blocker_keys):
            item.priority = "high"
    return items


async def plan_remediation(
    llm_complete: LLMComplete, needs: list[RemediationNeed]
) -> tuple[list[RemediationItem], dict[str, int]]:
    if not needs:
        return [], {}
    keys = {n.key for n in needs}
    blocker_keys = {n.key for n in needs if n.kind == "blocker"}
    messages = build_remediation_messages(needs)

    try:
        plan, usage = await complete_json(
            llm_complete,
            messages,
            RemediationPlan,
            validate=make_remediation_validator(keys),
            stage="remediation",
        )
        return _clamp_priorities(list(plan.items), blocker_keys), usage
    except StageOutputError:
        log.error("remediation_degraded", needs=sorted(keys))
        # Deterministic fallback: one item per need, guaranteeing coverage.
        return _clamp_priorities([_synthesise_item(n) for n in needs], blocker_keys), {}
