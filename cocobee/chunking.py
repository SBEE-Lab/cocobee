"""Text -> chunks -> embedded rows, shared by the thread and file pipelines."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import cocoindex as coco
from cocoindex.connectors import lancedb
from cocoindex.ops.text import RecursiveSplitter
from cocoindex.resources.chunk import Chunk
from cocoindex.resources.id import IdGenerator

from cocobee.config import CHUNK_OVERLAP, CHUNK_SIZE
from cocobee.context import EMBEDDER
from cocobee.models import SlackChunk

_splitter = RecursiveSplitter()


@dataclass(frozen=True, slots=True)
class ChunkMeta:
    """Row fields every chunk of one source shares."""

    kind: str
    channel: str
    source_id: str
    # Every source-side id this document answers for — a window covers several
    # message timestamps, so a lookup by any one of them must find it.
    covered: str
    permalink: str
    author: str
    posted_at: datetime.datetime


@coco.fn
async def _declare_chunk(
    chunk: Chunk,
    meta: ChunkMeta,
    id_gen: IdGenerator,
    table: lancedb.TableTarget[SlackChunk],
) -> None:
    table.declare_row(
        row=SlackChunk(
            id=await id_gen.next_id(chunk.text),
            kind=meta.kind,
            channel=meta.channel,
            source_id=meta.source_id,
            covered=meta.covered,
            permalink=meta.permalink,
            author=meta.author,
            posted_at=meta.posted_at,
            text=chunk.text,
            embedding=await coco.use_context(EMBEDDER).embed(chunk.text),
        ),
    )


async def declare_chunks(
    text: str,
    meta: ChunkMeta,
    table: lancedb.TableTarget[SlackChunk],
) -> None:
    chunks = _splitter.split(
        text,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        language="markdown",
    )
    id_gen = IdGenerator()
    await coco.map(_declare_chunk, chunks, meta, id_gen, table)
