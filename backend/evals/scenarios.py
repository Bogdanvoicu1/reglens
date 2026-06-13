"""Golden scenarios for the assessment agent (rulebook classification).

Each scenario is a synthetic system description with sparse expected
verdicts: a scenario only asserts rules whose `requires` gates it also
asserts as applying, so every assertion is evaluable by the engine.
Coverage (at least one `applies` and one `does_not_apply` per rulebook
rule) is enforced by tests/test_scenarios.py.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SCENARIOS_PATH = Path(__file__).parent / "assessment_scenarios.json"

ExpectedVerdict = Literal["applies", "does_not_apply"]
# "injection" scenarios embed a prompt-injection attempt inside the system
# description; their expected verdicts are the *correct* classification, so a
# derailed engine fails the diff. Tracked separately as an injection-resistance
# metric in the A4 eval.
ScenarioCategory = Literal["standard", "injection"]


class AssessmentScenario(BaseModel):
    id: str
    title: str
    description: str = Field(min_length=200)
    category: ScenarioCategory = "standard"
    expected_verdicts: dict[str, ExpectedVerdict] = Field(min_length=1)


class ScenarioDataset(BaseModel):
    version: str
    scenarios: list[AssessmentScenario]

    @model_validator(mode="after")
    def _unique_ids(self) -> "ScenarioDataset":
        ids = [s.id for s in self.scenarios]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"Duplicate scenario ids: {dupes}")
        return self


def load_scenarios(path: Path = SCENARIOS_PATH) -> ScenarioDataset:
    return ScenarioDataset.model_validate(json.loads(path.read_text()))
