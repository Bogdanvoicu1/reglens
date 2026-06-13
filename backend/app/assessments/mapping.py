"""Stage 3 — obligation mapping (deterministic, no LLM).

Turns the classification verdicts into the concrete duties that follow,
purely from the rulebook: each rule that `applies` contributes its
`on_applies.obligations`, an obligation's `audience` is intersected with the
organisation's established roles, and its severity is the strongest of the
rules that triggered it. Keeping this stage rule-driven (not a model call)
means the chain from "which rules applied" to "what you must do" is exact and
auditable; the model's judgement is reserved for gap analysis and remediation.
"""

from dataclasses import dataclass

from app.assessments.schema import Obligation, Rulebook, Severity

# Audience → the rule whose `applies` verdict establishes that role.
ROLE_RULES: dict[str, str] = {
    "provider": "aia-role-provider",
    "deployer": "aia-role-deployer",
    "controller": "gdpr-role-controller",
    "processor": "gdpr-role-processor",
}

SEVERITY_ORDER: dict[str, int] = {
    "informational": 0,
    "operational": 1,
    "pre-market": 2,
    "blocker": 3,
}


@dataclass
class MappedObligation:
    obligation: Obligation
    severity: Severity
    triggered_by: list[str]  # rule ids that applied and carry this obligation
    # False when the obligation's audience role was not confirmed (the role
    # rule returned needs_info / was not decided): the duty is conditional.
    audience_established: bool


def map_obligations(rulebook: Rulebook, verdicts: dict[str, str]) -> list[MappedObligation]:
    """Collect the obligations triggered by applied rules, filtered by role
    and ranked by severity (strongest first, then obligation id)."""
    triggers: dict[str, list[str]] = {}
    severities: dict[str, str] = {}
    for rule in rulebook.rules:
        if verdicts.get(rule.id) != "applies":
            continue
        for ob_id in rule.on_applies.obligations:
            triggers.setdefault(ob_id, []).append(rule.id)
            if ob_id not in severities or (
                SEVERITY_ORDER[rule.on_applies.severity] > SEVERITY_ORDER[severities[ob_id]]
            ):
                severities[ob_id] = rule.on_applies.severity

    mapped: list[MappedObligation] = []
    for ob_id, rule_ids in triggers.items():
        obligation = rulebook.obligation(ob_id)
        established = True
        if obligation.audience != "any":
            role_verdict = verdicts.get(ROLE_RULES[obligation.audience])
            if role_verdict == "does_not_apply":
                continue  # the duty falls on a role the organisation does not hold
            established = role_verdict == "applies"
        mapped.append(
            MappedObligation(
                obligation=obligation,
                severity=severities[ob_id],  # type: ignore[arg-type]
                triggered_by=sorted(rule_ids),
                audience_established=established,
            )
        )

    mapped.sort(key=lambda m: (-SEVERITY_ORDER[m.severity], m.obligation.id))
    return mapped
