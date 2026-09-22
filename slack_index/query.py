"""Search the index."""

from __future__ import annotations

import asyncio
import sys

from slack_index.search import Searcher

TOP_K = 5


async def run(query: str, *, top_k: int = TOP_K) -> None:
    searcher = await Searcher.open()
    for hit in await searcher.search(query, top_k):
        print(f"[{hit.score:.3f}] {hit.kind} by {hit.author} — {hit.permalink}")
        print(f"    {hit.text[:300]}")
        print("---")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: python -m slack_index.query <query>")
    asyncio.run(run(" ".join(sys.argv[1:])))


if __name__ == "__main__":
    main()
