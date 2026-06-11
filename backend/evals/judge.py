"""LLM-as-judge for generated answers: faithfulness, citation precision, relevance."""

import json
import re

import httpx

from app.core.config import get_settings
from app.rag.retrieval.hybrid import RetrievedChunk

JUDGE_PROMPT = """You are a strict evaluator of a compliance assistant's answer.

You are given numbered SOURCES (excerpts of EU regulations), a QUESTION, and the \
assistant's ANSWER. The answer cites sources as [n].

Evaluate:
1. faithfulness (0.0-1.0): fraction of the answer's factual claims fully supported by the sources.
2. citation_precision (0.0-1.0): fraction of [n] markers where source n actually supports the \
claim it is attached to.
3. answer_relevance (0.0-1.0): how directly the answer addresses the question.
4. verdict: "pass" if faithfulness >= 0.8 and citation_precision >= 0.8 and \
answer_relevance >= 0.7, else "fail".

Return ONLY a JSON object:
{"faithfulness": x, "citation_precision": x, "answer_relevance": x, "verdict": "pass"|"fail", \
"unsupported_claims": ["..."]}"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class JudgeClient:
    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self._model = model or settings.judge_model
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=120,
        )

    async def judge(self, question: str, answer: str, sources: list[RetrievedChunk]) -> dict:
        blocks = "\n\n".join(
            f"<source id={i}>\n{s.text}\n</source>" for i, s in enumerate(sources, start=1)
        )
        user = f"SOURCES:\n{blocks}\n\nQUESTION: {question}\n\nANSWER:\n{answer}"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
        }
        for attempt in range(2):
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            match = _JSON_BLOCK.search(content)
            if match:
                try:
                    verdict = json.loads(match.group(0))
                    if {"faithfulness", "citation_precision", "answer_relevance"} <= set(verdict):
                        return verdict
                except json.JSONDecodeError:
                    pass
            if attempt == 0:
                continue
        raise ValueError(f"Judge returned unparseable verdict: {content[:300]}")

    async def aclose(self) -> None:
        await self._client.aclose()
