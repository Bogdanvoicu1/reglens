"""Query contextualization for multi-turn chat.

A follow-up like "what about for minors?" is meaningless to retrieval on its
own. Before searching, we rewrite it into a standalone question using the
recent turns, then run the existing pipeline unchanged. First turns (no
history) skip this entirely — zero added cost or latency.

The rewrite is best-effort: any failure or implausible output falls back to
the original question, so contextualization can never make retrieval worse
than the single-turn baseline.
"""

import structlog

from app.observability.redaction import loggable_question
from app.services.llm import LLMComplete

log = structlog.get_logger()

# Recent turns fed to the rewriter. Two turns resolve almost all real
# follow-ups ("what about X?", "and the penalties?") without bloating the call.
HISTORY_MESSAGES = 4

# Cap each turn so a long prior answer can't blow up the rewrite prompt; the
# opening of a message carries the references a follow-up points back to.
_MAX_TURN_CHARS = 1000

CONTEXTUALIZE_SYSTEM = """You rewrite a follow-up question into a standalone \
question for a search engine over EU regulations (the AI Act and the GDPR).

Given the conversation so far and a follow-up, output a single question that \
stands on its own: resolve pronouns and back-references ("it", "that", \
"what about minors?") using the prior turns. If the follow-up is already \
self-contained, return it unchanged. Preserve the user's intent and wording; \
do not answer it and do not add any explanation. Output only the rewritten \
question, on one line."""


def format_history(history: list[tuple[str, str]]) -> str:
    labels = {"user": "User", "assistant": "Assistant"}
    lines = []
    for role, content in history:
        text = content.strip()
        if len(text) > _MAX_TURN_CHARS:
            text = text[:_MAX_TURN_CHARS] + "…"
        lines.append(f"{labels.get(role, role)}: {text}")
    return "\n".join(lines)


def build_contextualize_messages(
    question: str, history: list[tuple[str, str]]
) -> list[dict[str, str]]:
    user = (
        f"Conversation so far:\n{format_history(history)}\n\n"
        f"Follow-up: {question}\n\nStandalone question:"
    )
    return [
        {"role": "system", "content": CONTEXTUALIZE_SYSTEM},
        {"role": "user", "content": user},
    ]


def usable_rewrite(rewritten: str, original: str) -> str:
    """Return the rewrite if plausible, else fall back to the original.

    Guards against the model returning nothing or rambling/answering instead of
    rewriting — in which case the original single-turn question is safer.
    """
    candidate = rewritten.strip().strip('"').strip()
    if not candidate or len(candidate) > max(300, len(original) * 4):
        return original
    return candidate


async def contextualize_question(
    llm_complete: LLMComplete, question: str, history: list[tuple[str, str]]
) -> str:
    """Rewrite a follow-up into a standalone question; no-op on first turns."""
    if not history:
        return question
    try:
        result = await llm_complete(build_contextualize_messages(question, history))
    except Exception:
        log.warning("contextualize_failed")
        return question
    rewritten = usable_rewrite(result.text, question)
    if rewritten != question:
        log.info("contextualized", original=loggable_question(question))
    return rewritten
