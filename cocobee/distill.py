"""LLM distillation: a short header that says what a conversation was about.

Cerebras' knowledge base replaces the raw transcript with an LLM-normalised
question/summary/resolution and keeps the raw text for full-text search only. We
have no full-text index yet, so the distilled header is prepended to the raw
transcript instead of replacing it: the summary supplies the wording a searcher
would use, the transcript keeps the exact strings (catalog numbers, strain names)
that a summary always drops.
"""

from __future__ import annotations

import json

import cocoindex as coco
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from cocobee.config import DISTILL_MAX_TOKENS, DISTILL_TEMPERATURE
from cocobee.context import DISTILLER

_SYSTEM = """You summarise chat from a molecular biology lab's Slack channel.
The chat is Korean and informal; the science terms are not. Write in Korean.

Copy identifiers exactly as they appear — protein and strain names, mutations,
catalog numbers, plasmids, dates, quantities. Never translate or normalise them.
Never add a fact that is not in the transcript."""

_INSTRUCTION = """Normalise this conversation for a search index.

question: one line — the question this conversation answers, or what it records.
summary: one or two sentences on what was discussed.
resolution: what was decided. Leave it empty when nothing was.
keywords: 3-8 proper nouns and identifiers someone would search by.

Conversation:
"""


class Distiller:
    """Owns the client and the model id.

    The model id is the memo key: swapping models must re-distill everything,
    while a new client object for the same model must not.
    """

    def __init__(self, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    def __coco_memo_key__(self) -> object:
        return self._model

    async def run(self, transcript: str) -> Distilled:
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=DISTILL_MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _INSTRUCTION + transcript}],
            output_format=Distilled,
            # `parse()` takes no sampling arguments; temperature rides along in the
            # body so a re-distill does not reword an unchanged conversation.
            extra_body={"temperature": DISTILL_TEMPERATURE},
        )
        parsed = response.parsed_output
        if parsed is None:
            raise RuntimeError(
                f"distillation returned no structured output: {response.stop_reason}"
            )
        return parsed


class Distilled(BaseModel):
    question: str = Field(
        description="One line: the question this conversation answers"
    )
    summary: str = Field(description="One or two sentences on what was discussed")
    resolution: str = Field(description="What was decided; empty if still open")
    keywords: list[str] = Field(description="Identifiers and proper nouns to search by")


def render(distilled: Distilled) -> str:
    lines = [f"[Q] {distilled.question}", f"[Summary] {distilled.summary}"]
    # An open question should not be indexed as if it had an answer.
    if distilled.resolution.strip():
        lines.append(f"[Resolution] {distilled.resolution}")
    lines.append(f"[Keywords] {', '.join(distilled.keywords)}")
    return "\n".join(lines)


# The prompt and the output schema shape every distillation but live outside the
# function body, where cocoindex's logic fingerprint cannot see them. Declaring them
# as deps is what makes editing a prompt re-distill the channel instead of silently
# serving summaries written by the old one.
_PROMPT_DEPS = (
    _SYSTEM,
    _INSTRUCTION,
    DISTILL_MAX_TOKENS,
    DISTILL_TEMPERATURE,
    json.dumps(Distilled.model_json_schema(), sort_keys=True),
)


@coco.fn(memo=True, deps=_PROMPT_DEPS)
async def distill(transcript: str) -> str:
    """Memoized on the transcript, so an unchanged conversation is never re-billed."""
    return render(await coco.use_context(DISTILLER).run(transcript))
