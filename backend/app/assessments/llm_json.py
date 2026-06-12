"""Validated-JSON completions for assessment stages.

Every stage call must come back as a typed, validated model — never free
text. On a parse/validation failure the model gets exactly one corrective
retry (its invalid output plus the validation error); a second failure
raises `StageOutputError` for the caller to downgrade (e.g. to `needs_info`
findings) rather than crash the run.
"""

import json
import re
from collections.abc import Awaitable, Callable

import structlog
from pydantic import BaseModel, ValidationError

from app.services.llm import StreamResult

log = structlog.get_logger()

# Messages in, StreamResult out — ChatClient.complete's shape, injectable in tests.
LLMComplete = Callable[[list[dict[str, str]]], Awaitable[StreamResult]]

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class StageOutputError(RuntimeError):
    """Model output failed validation even after the corrective retry.
    Carries the last raw output so callers can salvage partial results."""

    def __init__(self, message: str, *, last_text: str = "") -> None:
        super().__init__(message)
        self.last_text = last_text


def extract_json(text: str) -> dict[str, object]:
    """Parse a JSON object from model output, tolerating code fences and
    surrounding prose (first '{' to last '}')."""
    cleaned = _FENCE.sub("", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model output is not a JSON object")
    return parsed


async def complete_json[T: BaseModel](
    llm_complete: LLMComplete,
    messages: list[dict[str, str]],
    model_cls: type[T],
    *,
    validate: Callable[[T], None] | None = None,
    stage: str,
) -> tuple[T, dict[str, int]]:
    """Run a completion and validate it into `model_cls`; returns (model, usage)."""
    attempt_messages = messages
    for attempt in (1, 2):
        result = await llm_complete(attempt_messages)
        try:
            parsed = model_cls.model_validate(extract_json(result.text))
            if validate is not None:
                validate(parsed)
            return parsed, result.usage
        except (ValueError, ValidationError) as exc:
            log.warning("stage_output_invalid", stage=stage, attempt=attempt, error=str(exc)[:500])
            if attempt == 2:
                raise StageOutputError(
                    f"{stage}: invalid model output after retry", last_text=result.text
                ) from exc
            attempt_messages = [
                *messages,
                {"role": "assistant", "content": result.text},
                {
                    "role": "user",
                    "content": (
                        f"Your previous reply failed validation: {str(exc)[:800]}\n"
                        "Reply again with ONLY the corrected JSON object — no prose, "
                        "no code fences."
                    ),
                },
            ]
    raise AssertionError("unreachable")
