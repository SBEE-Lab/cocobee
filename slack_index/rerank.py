"""Cross-encoder reranking of the candidate pool.

The retriever embeds query and document separately, so it can only compare them
through one vector each. A cross-encoder reads the pair together and scores the
match directly: slower, so it only ever sees the shortlist the retriever produced.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import torch
from sentence_transformers import CrossEncoder

if TYPE_CHECKING:
    from slack_index.search import Hit


def default_device() -> str:
    """Scoring 20 pairs per query is the slowest step in a search; on this laptop
    the GPU is an order of magnitude faster than the CPU fallback."""
    override = os.environ.get("SLACK_INDEX_RERANK_DEVICE")
    if override:
        return override
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Reranker:
    """Loads the cross-encoder lazily: a process that never reranks never pays for it."""

    def __init__(self, model_name: str, device: str | None = None) -> None:
        self._model_name = model_name
        self._device = device or default_device()
        self._model: CrossEncoder | None = None

    def __coco_memo_key__(self) -> object:
        return self._model_name

    def _load(self) -> CrossEncoder:
        if self._model is None:
            self._model = CrossEncoder(self._model_name, device=self._device)
        return self._model

    async def rank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]:
        """Reorder *hits* by cross-encoder score and keep the best *top_k*.

        Reranking can only reorder what it is given — a document the retriever
        never returned cannot be rescued here.
        """
        if not hits:
            return []
        model = self._load()
        pairs = [(query, hit.text) for hit in hits]
        scores = await asyncio.to_thread(model.predict, pairs)
        rescored = [
            hit.with_score(float(score))
            for hit, score in zip(hits, scores, strict=True)
        ]
        rescored.sort(key=lambda hit: hit.score, reverse=True)
        return rescored[:top_k]
