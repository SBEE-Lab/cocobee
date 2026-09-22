"""Search the index."""

from __future__ import annotations

import asyncio
import sys

from cocoindex.connectors import lancedb
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder

from slack_index import config

TOP_K = 5


async def search(query: str, *, top_k: int = TOP_K) -> None:
    settings = config.Settings.from_env()
    embedder = SentenceTransformerEmbedder(settings.embed_model)
    conn = await lancedb.connect_async(str(config.LANCEDB_URI))
    table = await conn.open_table(config.TABLE_NAME)

    request = await table.search(
        await embedder.embed(query), vector_column_name="embedding"
    )
    for row in await request.limit(top_k).to_list():
        score = 1.0 - row["_distance"]
        print(f"[{score:.3f}] {row['kind']} by {row['author']} — {row['permalink']}")
        print(f"    {row['text'][:300]}")
        print("---")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: python -m slack_index.query <query>")
    asyncio.run(search(" ".join(sys.argv[1:])))


if __name__ == "__main__":
    main()
