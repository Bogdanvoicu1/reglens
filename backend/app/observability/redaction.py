"""Question redaction for logs and traces.

Questions to a compliance tool can themselves be confidential. Unless
REGLENS_LOG_QUESTION_TEXT=true, logs and LLM traces carry a short stable hash
instead of plaintext — enough to correlate repeat queries, nothing more.
"""

import hashlib

from app.core.config import get_settings


def loggable_question(question: str) -> str:
    if get_settings().log_question_text:
        return question[:120]
    return "sha256:" + hashlib.sha256(question.encode()).hexdigest()[:12]
