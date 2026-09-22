"""Retrieval over the built index, shared by the query CLI and the evals."""

from __future__ import annotations

from dataclasses import dataclass

from cocoindex.connectors import lancedb
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder
from lancedb.table import AsyncTable

from slack_index import config

# One source can own many chunks; over-fetch so that collapsing them still
# leaves top_k distinct sources.
_CANDIDATE_FACTOR = 5


@dataclass(frozen=True, slots=True)
class Hit:
    source_id: str
    kind: str
    author: str
    permalink: str
    text: str
    score: float


class Searcher:
    """Holds the embedder and the open table so a run of queries pays for them once."""

    def __init__(
        self, table: AsyncTable, embedder: SentenceTransformerEmbedder
    ) -> None:
        self._table = table
        self._embedder = embedder

    @classmethod
    async def open(cls) -> Searcher:
        settings = config.Settings.from_env()
        conn = await lancedb.connect_async(str(config.LANCEDB_URI))
        table = await conn.open_table(config.TABLE_NAME)
        return cls(table, SentenceTransformerEmbedder(settings.embed_model))

    async def search(self, query: str, top_k: int) -> list[Hit]:
        """Best chunk per source, ranked — a thread that chunked into ten pieces
        should occupy one result slot, not ten."""
        vector = await self._embedder.embed(query)
        request = await self._table.search(vector, vector_column_name="embedding")
        rows = await request.limit(top_k * _CANDIDATE_FACTOR).to_list()

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
                    kind=row["kind"],
                    author=row["author"],
                    permalink=row["permalink"],
                    text=row["text"],
                    score=1.0 - row["_distance"],
                )
            )
            if len(hits) == top_k:
                break
        return hits
