import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DATASET_PATH = Path(__file__).parent / "dataset.json"


class ExpectedSource(BaseModel):
    corpus: str
    ref: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.corpus, self.ref)


class EvalEntry(BaseModel):
    id: str
    category: str
    question: str = Field(min_length=5)
    expected: list[ExpectedSource] = Field(default_factory=list)
    require: Literal["any", "all"] = "any"
    expect_refusal: bool = False

    @model_validator(mode="after")
    def _refusal_xor_expected(self) -> "EvalEntry":
        if self.expect_refusal == bool(self.expected):
            raise ValueError(f"{self.id}: must have either expected sources or expect_refusal")
        return self


class EvalDataset(BaseModel):
    version: str
    entries: list[EvalEntry]

    @model_validator(mode="after")
    def _unique_ids(self) -> "EvalDataset":
        ids = [e.id for e in self.entries]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"Duplicate entry ids: {dupes}")
        return self

    @property
    def answerable(self) -> list[EvalEntry]:
        return [e for e in self.entries if not e.expect_refusal]

    @property
    def refusals(self) -> list[EvalEntry]:
        return [e for e in self.entries if e.expect_refusal]


def load_dataset(path: Path = DATASET_PATH) -> EvalDataset:
    return EvalDataset.model_validate(json.loads(path.read_text()))
