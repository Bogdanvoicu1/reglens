"""Typed schema for the versioned assessment rulebook.

The rulebook is data, not prompts: every classification the assessment agent
makes corresponds to a `Rule`, and every duty it reports corresponds to an
`Obligation`. Per rule, the engine retrieves the expected provisions and asks
the model for a verdict constrained to `Verdict`; rule semantics never live
inside free-form prompt text. This keeps classification logic reviewable by a
domain expert, independently testable per rule, and extensible to new
regulations without code changes.

Gating: a rule with `requires` is evaluated only when every listed rule
returned `applies` (e.g. prohibited-practice rules only run for systems that
meet the AI-system definition); otherwise it is recorded as skipped.

Obligation audiences: a rule attaches every obligation it can trigger; the
obligation-mapping stage later intersects each obligation's `audience` with
the roles established for the organisation (provider/deployer under the AI
Act, controller/processor under the GDPR), so e.g. an Annex III hit only
yields Art. 26 duties for deployers.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.rag.ingestion.registry import CORPORA

Severity = Literal["blocker", "pre-market", "operational", "informational"]
Verdict = Literal["applies", "does_not_apply", "needs_info"]
Audience = Literal["provider", "deployer", "controller", "processor", "any"]

VERDICTS: tuple[str, ...] = ("applies", "does_not_apply", "needs_info")


class SourceRef(BaseModel, frozen=True):
    corpus: str
    ref: str  # document-level ref as ingested, e.g. "Art. 5", "Annex III"

    @model_validator(mode="after")
    def _known_corpus(self) -> "SourceRef":
        if self.corpus not in CORPORA:
            raise ValueError(f"Unknown corpus slug: {self.corpus!r}")
        return self


class Obligation(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=5)
    summary: str = Field(min_length=10)
    audience: Audience
    citations: list[SourceRef] = Field(min_length=1)


class RuleOutcome(BaseModel):
    severity: Severity
    obligations: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    group: str = Field(pattern=r"^[a-z-]+/[a-z-]+$")  # "<corpus-slug>/<topic>"
    question: str = Field(min_length=20)
    retrieval_queries: list[str] = Field(min_length=1)
    expected_sources: list[SourceRef] = Field(min_length=1)
    requires: list[str] = Field(default_factory=list)
    on_applies: RuleOutcome

    @model_validator(mode="after")
    def _group_corpus_known(self) -> "Rule":
        corpus = self.group.split("/", 1)[0]
        if corpus not in CORPORA:
            raise ValueError(f"{self.id}: group corpus {corpus!r} is not a known corpus")
        return self


class Rulebook(BaseModel):
    version: str
    obligations: list[Obligation]
    rules: list[Rule]

    @model_validator(mode="after")
    def _integrity(self) -> "Rulebook":
        rule_ids = [r.id for r in self.rules]
        obligation_ids = [o.id for o in self.obligations]
        for name, ids in (("rule", rule_ids), ("obligation", obligation_ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            if dupes:
                raise ValueError(f"Duplicate {name} ids: {dupes}")

        known_obligations = set(obligation_ids)
        known_rules = set(rule_ids)
        for rule in self.rules:
            missing = [o for o in rule.on_applies.obligations if o not in known_obligations]
            if missing:
                raise ValueError(f"{rule.id}: unknown obligations {missing}")
            bad_requires = [r for r in rule.requires if r not in known_rules or r == rule.id]
            if bad_requires:
                raise ValueError(f"{rule.id}: invalid requires {bad_requires}")

        unreferenced = known_obligations - {o for r in self.rules for o in r.on_applies.obligations}
        if unreferenced:
            raise ValueError(f"Obligations never referenced by any rule: {sorted(unreferenced)}")

        self._check_requires_acyclic()
        return self

    def _check_requires_acyclic(self) -> None:
        graph = {r.id: r.requires for r in self.rules}
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(node: str, path: list[str]) -> None:
            if node in done:
                return
            if node in visiting:
                raise ValueError(f"requires cycle: {' -> '.join([*path, node])}")
            visiting.add(node)
            for dep in graph[node]:
                visit(dep, [*path, node])
            visiting.discard(node)
            done.add(node)

        for rule_id in graph:
            visit(rule_id, [])

    def rule(self, rule_id: str) -> Rule:
        return next(r for r in self.rules if r.id == rule_id)

    def obligation(self, obligation_id: str) -> Obligation:
        return next(o for o in self.obligations if o.id == obligation_id)
