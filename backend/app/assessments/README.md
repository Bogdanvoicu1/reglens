# `app/assessments` — Compliance Assessment Agent

Turns a free-text description of an AI system into a **grounded compliance
readiness report** against the EU AI Act and GDPR: risk classification,
applicable obligations, gap analysis, and a remediation roadmap — every
conclusion cited to the article. It is a *readiness assessment*, never a
legality verdict.

## Design stance: a typed staged pipeline, not a free-form agent

Compliance output must be auditable, reproducible, and evaluable, so this is a
fixed DAG of typed stages (a state machine) with one bounded clarification
loop — not an open-ended ReAct agent. Every stage is a Pydantic-validated step;
classification verdicts never leave their enum; citations are validated against
the corpus exactly like chat answers. Stage outputs persist to Postgres, so a
run is resumable, diffable across corpus versions, and individually testable.

```
description → profile → (clarify?) → classify → map obligations → gaps → remediation → report
```

## The rulebook is the moat (`rulebook.yaml`, `schema.py`, `rulebook.py`)

Classification logic lives in a **versioned YAML rulebook**, not in prompts:
31 rules + a 35-entry obligation registry. Each rule has a yes/no `question`,
the `expected_sources` it must be grounded in, a `requires` DAG (gating), and an
`on_applies` outcome (severity + obligations). `schema.py` validates integrity
(unique ids, referential integrity, acyclic `requires`, no orphans); a test
cross-checks every cited ref against the parsed corpus. New regulations are
added as data, and each rule is independently eval-tested.

## Files

| File | Role |
|---|---|
| `schema.py` | Pydantic models for the rulebook (Rule, Obligation, SourceRef, RuleOutcome) + integrity validation |
| `rulebook.yaml` / `rulebook.py` | The rulebook data + a cached loader |
| `llm_json.py` | Validated-JSON stage completions: parse → validate → one corrective retry → `StageOutputError` (with lenient JSON repair) |
| `profile.py` | Stage 1 — extract a typed `SystemProfile` from the (untrusted) description; propose ≤3 clarifying questions |
| `classify.py` | Stage 2 — classify rules in topological waves, batched per group, grounded in verbatim provisions; citation normalization; per-item salvage → `needs_info` degradation |
| `mapping.py` | Stage 3 — deterministic obligation mapping (audience × established role, severity = strongest triggering rule) |
| `gaps.py` | Stage 4 — gap analysis per obligation (met / partial / missing / unknown) |
| `remediation.py` | Stage 5 — remediation roadmap with priority/effort/tradeoffs and a deterministic blocker-coverage guarantee |
| `report.py` | Stage 6 — typed `AssessmentReport` + executive summary + markdown export |
| `engine.py` | Orchestrates the stages, emits persistence-first SSE events, accumulates token/cost usage |
| `run.py` | Dev CLI: `python -m app.assessments.run --scenario <id>` runs the real pipeline and diffs verdicts |

## Safety

Prohibited-practice ("blocker") detection is the safety-critical path. It is
classified by the stronger (judge-tier) model, and the eval enforces a two-tier
gate: a hard gate that a prohibited practice is **never cleared** as
`does_not_apply` when it applies (`needs_info` is a safe flag for review), plus
quality gates for accuracy, recall, and prompt-injection resistance. See
[`evals/`](../../evals/README.md) and
[`docs/ASSESSMENT_AGENT.md`](../../../docs/ASSESSMENT_AGENT.md).
