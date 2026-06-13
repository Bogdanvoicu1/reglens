# RegLens Assessments — Compliance Assessment Agent (v2 flagship)

Design and delivery plan for the next major capability: a user describes the
AI system they are building, and RegLens produces a **grounded compliance
readiness report** against the EU AI Act and GDPR — classification, applicable
obligations, gap analysis, remediation roadmap, checklists, and tradeoffs,
every claim cited to the article level.

> Positioning note: this is a *readiness assessment*, never a legality
> verdict. The output is explicitly framed as gap analysis grounded in the
> regulation text, with the existing not-legal-advice disclaimer. That framing
> is both legally necessary and what makes the feature technically defensible:
> nothing is asserted without a citation.

## 1. Why this feature (business analysis)

RegLens v1 is **reactive**: the user must already know which question to ask.
The money in compliance tooling is in being **proactive** — telling users
what applies to them and what to fix (compare: Vanta/Drata for SOC 2,
OneTrust for privacy). Candidate features considered:

| Feature | User value | Effort | Moat / notes |
|---|---|---|---|
| **Assessment agent** (this doc) | Replaces hours of consultant triage; output is a deliverable teams already pay for | High | Versioned rulebook + per-rule evals — hard to replicate with "just ask ChatGPT" |
| Regulatory change monitoring | Re-run affected assessments when corpus/guidance changes; retention driver | Medium | Builds on corpus versioning we already have |
| Audit binder export | Assessment + cited sources → PDF pack for procurement/auditors | Low-Med | Monetizable artifact; natural A5 follow-on |
| DPIA / FRIA generators | Guided Art. 35 GDPR / Art. 27 AI Act drafts | Medium | Reuses the same staged engine |
| More corpora (DSA, NIS2, DORA) | "EU digital compliance copilot" | Medium each | Horizontal scaling of the same engine + rulebook pattern |

The assessment agent is the flagship because every other feature compounds on
it. Target users, concretely: AI startups pre-enterprise-sale (procurement
questionnaires), product/eng leads doing design reviews ("compliance by
design"), and consultancies using it as analyst leverage.

## 2. Agent architecture

### Design stance: typed pipeline, not free-form agent

A compliance assessment must be **auditable, reproducible, and evaluable**.
So: a fixed DAG of typed stages (state machine) with one bounded
clarification loop — not an open-ended ReAct loop. Each stage is an LLM call
(or batch) with structured output validated by Pydantic, grounded by
retrieval, with citations validated against the corpus exactly like chat
answers. Stage outputs persist to Postgres, so runs are resumable, diffable
across corpus versions, and individually testable. (Conceptually a LangGraph
graph; implemented with plain asyncio + typed stages, consistent with the
rest of the codebase.)

```
Intake (form + free text)
   │
   ▼
[1] Profile extraction ──── low confidence on critical fields ──▶ Clarification
   │            ▲                                                  questions to
   │            └────────────── user answers (max 1 round v1) ◀────── user
   ▼
[2] Classification over RULEBOOK        (per rule: retrieval → verdict)
   │     AI Act: AI-system definition · prohibited practices · high-risk
   │     (Annex III mapping / Art. 6) · transparency (Art. 50) · GPAI role
   │     GDPR: controller/processor · lawful basis candidates · Art. 9 ·
   │     Art. 22 ADM · DPIA trigger (Art. 35) · transfers (Ch. V)
   ▼
[3] Obligation mapping                  (classifications → concrete duties)
   ▼
[4] Gap analysis                        (duties vs what the profile shows:
   │                                     met / partial / missing / unknown)
   ▼
[5] Remediation & tradeoffs             (blockers → pre-market → operational;
   │                                     S/M/L effort; real tradeoffs)
   ▼
[6] Report assembly                     (typed AssessmentReport → UI + export)
```

### The rulebook (the moat)

Classification logic lives in a **versioned YAML rulebook**, not in prompts:

```yaml
- id: aia-prohibited-emotion-workplace
  group: ai-act/prohibited
  question: >
    Does the system infer emotions of natural persons in workplace or
    education settings (outside medical/safety use)?
  retrieval_queries: ["emotion recognition workplace education prohibited"]
  expected_sources: [{corpus: ai-act, ref: "Art. 5"}]
  on_applies:
    severity: blocker
    obligations: [aia-art5-cease]
- id: gdpr-dpia-required
  group: gdpr/accountability
  question: >
    Is processing likely to result in high risk (systematic evaluation,
    large-scale special categories, public monitoring)?
  retrieval_queries: ["data protection impact assessment required Article 35"]
  expected_sources: [{corpus: gdpr, ref: "Art. 35"}]
  on_applies:
    severity: pre-market
    obligations: [gdpr-art35-dpia]
```

Per rule, the engine retrieves the cited provisions and asks the model for a
typed verdict: `applies | does_not_apply | needs_info` + confidence +
reasoning + citations (validated). Rules are batched per group to control
cost. **Why this beats a single mega-prompt:** each rule is independently
testable (eval scenarios assert per-rule verdicts), the rulebook is
reviewable by a domain expert without reading prompts, new regulations are
added as data not code, and verdicts never leave the enum.

v1 rulebook scope (shipped in A0 as `app/assessments/rulebook.yaml`): 31
rules + a 35-entry obligation registry (AI Act: definition, EU-market scope,
8 prohibited-practice rules, Annex III mapping, Annex I product-safety
route, Art. 6(3) derogation, provider/deployer roles, 4 Art. 50
transparency rules, GPAI + systemic risk; GDPR: scope, roles, lawful basis,
Art. 8/9/22, DPIA, DPO, transfers). Loader validation: unique ids,
referential integrity (obligations, `requires` DAG, no cycles), and a test
that cross-checks every cited ref against the parsed corpora.

### Prerequisite: annex ingestion (A0) — done

High-risk classification hinges on **Annex III** (use-case list) and Annex I
(harmonisation legislation) — previously a parser scope cut. The EUR-Lex
parser now handles all 13 `anx_*` containers (sections, restarting point
numbers, nested lettered points, enumeration divs, dash lists); the AI Act
corpus re-ingested at 306 documents / 900 chunks, and golden dataset v3
gates annex retrieval (recall@8 = 1.0 incl. annex questions).

### Data model

```
assessments(id, tenant_id, user_id, title, status
            [draft|clarifying|running|complete|failed],
            system_profile jsonb, corpus_fingerprint, rulebook_version,
            created_at, completed_at)
assessment_findings(id, assessment_id FK, stage, rule_id, verdict,
            confidence, reasoning, citations jsonb, ord)
assessment_reports(id, assessment_id FK, version, report jsonb,
            markdown text, created_at)
```

`corpus_fingerprint` + `rulebook_version` make every report reproducible and
enable "regulation changed → re-assess" later.

### API

- `POST /api/v1/assessments` — intake `{title, description, profile_hints}`;
  returns SSE stream of stage events (`stage_started`, `finding`,
  `clarification_needed`, `report_ready`) — reuses the chat SSE
  infrastructure; state persists every stage so a dropped connection resumes
  via `GET`.
- `POST /api/v1/assessments/{id}/answers` — clarification round.
- `GET /api/v1/assessments`, `GET /{id}`, `GET /{id}/report.md` (export).
- Separate, stricter rate limit (e.g. 5 assessments/day/tenant): a run is
  ~15–25 LLM calls ≈ $0.05–0.15 (4o-mini class for stages; one stronger-model
  pass for the executive summary is a tunable).

### Security & privacy specifics

- System descriptions are **user-controlled content entering prompts** → same
  defenses as chat (data-not-instructions framing, structured outputs), plus:
  rule verdicts constrained to enums, citations validated server-side, no
  model output ever executed. Red-team scenarios (injection inside a system
  description) join the eval suite.
- Descriptions are confidential business information: question-redaction
  defaults already apply to logs/traces; add assessment deletion endpoint
  (data lifecycle) in A2.

### Evaluation strategy (extends the existing harness)

1. **Scenario suite** (~15–20 synthetic system descriptions with expected
   outcomes), e.g.:
   - CV-screening SaaS for EU employers → high-risk (Annex III 4(a)), GDPR
     Art. 22 applies, DPIA required
   - Workplace emotion recognition → **prohibited** (Art. 5(1)(f)) — blocker
   - Recipe chatbot → Art. 50 transparency only; no DPIA trigger
   - Credit scoring model → high-risk + Art. 22 + DPIA
   - Non-AI SaaS with EU customer data → AI Act n/a; GDPR core only
2. **Per-rule regression**: every rulebook rule has ≥1 positive and ≥1
   negative scenario; gate on per-rule accuracy (target ≥0.9) and zero missed
   prohibited-practice detections (hard gate: 1.0 recall on blockers).
3. **Report quality judge**: groundedness of obligation paragraphs,
   actionability of remediation items, citation precision — same LLM-judge
   pattern and thresholds style as chat evals.

## 3. Delivery plan

| Milestone | Scope | Est. effort |
|---|---|---|
| **A0 — Foundations** ✅ | Annex parsing (all 13 annexes), rulebook schema + loader + v1 rulebook (31 rules, 35 obligations), scenario dataset v1 (25 scenarios, full per-rule pos/neg coverage), migration for assessment tables | done |
| **A1 — Engine core** ✅ | Profile extraction stage, classification over the rulebook in topological waves batched per group (grounded in verbatim provisions, typed verdicts, citation normalization, retry → per-item salvage → needs_info degradation), persistence-first SSE events, tenant-scoped API, CLI runner with scenario diff (`python -m app.assessments.run --scenario <id>`). Live-verified: 57/57 expected verdicts across 4 scenarios, blocker detection confirmed, ~$0.01/assessment | done |
| **A2 — Full pipeline** ✅ | Deterministic obligation mapping (audience × role, severity max), gap analysis (met/partial/missing/unknown, salvage), remediation roadmap with priority/effort/tradeoffs + deterministic blocker-coverage guarantee, typed report + executive summary + markdown export (`GET /report.md`), one-round clarification (`POST /{id}/answers`), deletion endpoint, per-tenant daily assessment rate limit. Live-verified end-to-end (CV-screening, workplace-emotion blocker, bank-deployer); report renders with correct priority taxonomy | done |
| **A3 — Frontend** | Intake wizard, live progress view (stage timeline), report view: classification cards, obligation checklists, gap table, roadmap, citations drill-down; assessments list | 3 days |
| **A4 — Evals & hardening** | Scenario suite in `evals/`, per-rule gates + blocker-recall hard gate, injection red-team scenarios, Grafana panel (assessments by outcome, cost/assessment), docs | 2 days |
| **A5 — Later** | PDF/audit-binder export, DPIA/FRIA draft generators, corpus-change re-assessment triggers, multi-round clarification | backlog |

Known limitations to state in the UI/docs from day one: not legal advice; EU
regulations only (no national implementing acts); output quality bounded by
description quality; rulebook v1 covers core obligations, not sector-specific
guidance.

## 4. What this demonstrates (portfolio lens)

Typed multi-stage agent with deterministic control flow and HITL
clarification; versioned rule registry evaluated by grounded LLM calls;
hard safety gates in CI (blocker recall = 1.0); cost-bounded long-running
SSE workflows; reproducible, auditable outputs. This is the difference
between "calls an LLM" and "engineered an LLM system".
