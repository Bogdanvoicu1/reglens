"""Loader for the YAML rulebook shipped with the application."""

from functools import lru_cache
from pathlib import Path

import yaml

from app.assessments.schema import Rulebook

RULEBOOK_PATH = Path(__file__).parent / "rulebook.yaml"


@lru_cache(maxsize=4)
def load_rulebook(path: Path = RULEBOOK_PATH) -> Rulebook:
    return Rulebook.model_validate(yaml.safe_load(path.read_text()))
