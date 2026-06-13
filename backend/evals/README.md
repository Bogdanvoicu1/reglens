# `evals` — threshold-gated evaluation harness

Exercises the **real production pipeline** (not mocks) and exits non-zero on any
gate failure, so quality and safety regressions fail loudly. Runs persist to the
`eval_runs` table and write a full report to `reports/latest.json`.

```bash
uv run python -m evals.cli retrieval     # deterministic: recall@K, MRR (1 embedding call)
uv run python -m evals.cli generation    # full chat pipeline + LLM-as-judge
uv run python -m evals.cli assessment    # assessment agent over golden scenarios
```

## Suites

| Suite | Module | What it checks | Key gates |
|---|---|---|---|
| retrieval | `retrieval_eval.py` | Does hybrid retrieval surface the expected article refs? | recall@8 ≥ 0.85, MRR ≥ 0.60 |
| generation | `generation_eval.py` + `judge.py` | Real retrieve→generate→validate, then an LLM judge scores answerable cases; refusal-expected cases scored deterministically | faithfulness / citation precision / refusal accuracy ≥ 0.80, false-refusal ≤ 0.10 |
| assessment | `assessment_eval.py` | Runs the real assessment engine over 28 scenarios (incl. 3 prompt-injection red-team descriptions) | **blocker false-clear rate = 0** (hard), verdict accuracy / blocker recall / injection resistance |

## Datasets

- `dataset.json` — golden Q/A for chat, each mapped to expected source articles, including out-of-corpus and red-team (instruction-override, prompt-extraction) cases.
- `assessment_scenarios.json` — synthetic system descriptions with expected per-rule verdicts; `category: injection` marks adversarial descriptions. Coverage (each rule has a positive and a negative; each blocker has a dedicated positive) is enforced by `tests/test_scenarios.py`.

## The assessment safety gate

`assessment_eval.aggregate()` is a **pure** reduction (no DB/LLM) so the gate
arithmetic — especially blocker recall — is unit-tested deterministically in
`tests/test_assessment_eval.py`. The hard gate encodes the catastrophic-error
guarantee for a compliance tool: a prohibited practice is never silently cleared
as `does_not_apply`; an uncertain one degrades to `needs_info` (surfaced for
review), which does not trip the gate.

## CI

`.github/workflows/ci.yml` runs the deterministic checks on every PR.
`evals.yml` (`workflow_dispatch`) provisions Postgres, ingests the corpus, and
runs a chosen suite with the real LLM (needs the `OPENROUTER_API_KEY` secret).
