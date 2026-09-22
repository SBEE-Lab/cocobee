"""One component per shared file: download, extract text, chunk, embed."""

from __future__ import annotations

import datetime
import logging

import aiohttp
import cocoindex as coco
from cocoindex.connectors import lancedb

from slack_index.chunking import ChunkMeta, declare_chunks
from slack_index.config import bot_token
from slack_index.context import SLACK_LIMIT
from slack_index.models import FileRef, SlackChunk
from slack_index.users import display_name

_logger = logging.getLogger(__name__)

# Formats readable as-is. Binary documents (pdf, docx, pptx) need a converter —
# add one in `extract_text` and they flow through the rest of the pipeline unchanged.
TEXT_MIMETYPE_PREFIXES = ("text/",)
TEXT_MIMETYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/x-ndjson",
        "application/x-sh",
        "application/javascript",
    }
)


def is_text(mimetype: str) -> bool:
    return mimetype.startswith(TEXT_MIMETYPE_PREFIXES) or mimetype in TEXT_MIMETYPES


async def download(ref: FileRef) -> bytes:
    """Fetch a file's bytes. `url_private_download` needs the bot token, not the API."""
    await coco.use_context(SLACK_LIMIT).acquire()
    headers = {"Authorization": f"Bearer {bot_token()}"}
    async with (
        aiohttp.ClientSession(headers=headers) as session,
        session.get(ref.url) as response,
    ):
        response.raise_for_status()
        return await response.read()


async def extract_text(ref: FileRef, max_bytes: int) -> str | None:
    """Return the file's text, or None when there is nothing indexable in it."""
    if not is_text(ref.mimetype):
        _logger.info("skipping %s (%s): no extractor", ref.name, ref.mimetype)
        return None
    if ref.size > max_bytes:
        _logger.info("skipping %s: %d bytes exceeds the limit", ref.name, ref.size)
        return None
    return (await download(ref)).decode("utf-8", errors="replace")


@coco.fn(memo=True)
async def process_file(
    ref: FileRef,
    table: lancedb.TableTarget[SlackChunk],
    max_bytes: int,
) -> None:
    text = await extract_text(ref, max_bytes)
    if text is None:
        return

    await declare_chunks(
        f"# {ref.name}\n\n{text}",
        ChunkMeta(
            kind="file",
            channel=ref.channel,
            source_id=ref.file_id,
            permalink=ref.permalink,
            author=await display_name(ref.user),
            posted_at=datetime.datetime.fromtimestamp(ref.created, tz=datetime.UTC),
        ),
        table,
    )
