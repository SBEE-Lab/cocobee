"""Retrieval over the built index, shared by the query CLI and the evals."""

from __future__ import annotations

from dataclasses import dataclass, replace

from cocoindex.connectors import lancedb
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder
from lancedb.table import AsyncTable

from cocobee import config
from cocobee.rerank import Reranker

# One source can own many chunks; over-fetch so that collapsing them still
# leaves top_k distinct sources.
_CANDIDATE_FACTOR = 5


@dataclass(frozen=True, slots=True)
class Hit:
    source_id: str
    covered: frozenset[str]
    kind: str
    author: str
    permalink: str
    text: str
    score: float

    def with_score(self, score: float) -> Hit:
        return replace(self, score=score)


class Searcher:
    """Holds the embedder and the open table so a run of queries pays for them once."""

    def __init__(
        self,
        table: AsyncTable,
        embedder: SentenceTransformerEmbedder,
        reranker: Reranker | None,
    ) -> None:
        self._table = table
        self._embedder = embedder
        self._reranker = reranker

    @classmethod
    async def open(cls, *, rerank: bool = True) -> Searcher:
        settings = config.Settings.from_env()
        conn = await lancedb.connect_async(str(config.LANCEDB_URI))
        table = await conn.open_table(config.TABLE_NAME)
        return cls(
            table,
            SentenceTransformerEmbedder(settings.embed_model),
            Reranker(config.RERANK_MODEL) if rerank else None,
        )

    async def search(
        self, query: str, top_k: int, *, candidates: int | None = None
    ) -> list[Hit]:
        """Best chunk per source, ranked — a thread that chunked into ten pieces
        should occupy one result slot, not ten.

        *candidates* sizes the shortlist handed to the reranker; it is the knob that
        trades reranking latency against the recall the reranker has to work with.
        """
        pool = candidates if candidates is not None else config.RERANK_CANDIDATES
        wanted = max(top_k, pool) if self._reranker else top_k
        vector = await self._embedder.embed(query)
        request = await self._table.search(vector, vector_column_name="embedding")
        rows = await request.limit(wanted * _CANDIDATE_FACTOR).to_list()

        hits: list[Hit] = []
        seen: set[str] = set()
        for row in rows:
            source_id = row["source_id"]
            if source_id in seen:
                continue
            seen.add(source_id)
            hits.append(
                Hit(
                    source_id=source_id,
                    covered=frozenset(row["covered"].split()),
                    kind=row["kind"],
                    author=row["author"],
                    permalink=row["permalink"],
                    text=row["text"],
                    score=1.0 - row["_distance"],
                )
            )
            if len(hits) == wanted:
                break
        if self._reranker is None:
            return hits
        return await self._reranker.rank(query, hits, top_k)
