"""One component per conversation: gather its messages, render, chunk, embed."""

from __future__ import annotations

import datetime
from typing import Any

import cocoindex as coco
from cocoindex.connectors import lancedb

from cocobee.chunking import ChunkMeta, declare_chunks
from cocobee.context import SLACK, SLACK_LIMIT
from cocobee.distill import distill
from cocobee.models import ConversationRef, Message, SlackChunk
from cocobee.source import next_cursor
from cocobee.users import display_name


def thread_permalink(channel: str, thread_ts: str) -> str:
    return f"https://slack.com/archives/{channel}/p{thread_ts.replace('.', '')}"


def ts_to_datetime(ts: str) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(float(ts), tz=datetime.UTC)


def speaker_id(message: dict[str, Any]) -> str | None:
    return message.get("user") or message.get("bot_id")


async def fetch_replies(ref: ConversationRef) -> list[Message]:
    client = coco.use_context(SLACK)
    limiter = coco.use_context(SLACK_LIMIT)
    messages: list[Message] = []
    cursor: str | None = None
    while True:
        await limiter.acquire()
        response = await client.conversations_replies(
            channel=ref.channel, ts=ref.start_ts, limit=200, cursor=cursor
        )
        messages.extend(
            Message(ts=m["ts"], user=speaker_id(m), text=m.get("text", ""))
            for m in response["messages"]
        )
        cursor = next_cursor(response)
        if cursor is None:
            return messages


async def conversation_messages(ref: ConversationRef) -> list[Message]:
    """A grouped run already arrived complete in the scan; only a thread needs a call."""
    if not ref.is_thread:
        return list(ref.messages)
    return await fetch_replies(ref)


@coco.fn(memo=True)
async def process_thread(
    ref: ConversationRef,
    table: lancedb.TableTarget[SlackChunk],
) -> None:
    messages = await conversation_messages(ref)
    if not messages:
        return

    lines: list[str] = []
    for message in messages:
        speaker = await display_name(message.user)
        lines.append(f"**{speaker}**: {message.text}")

    transcript = "\n\n".join(lines)
    # The header goes in front of the transcript, not instead of it: without a
    # lexical index, dropping the raw text would drop every exact identifier.
    await declare_chunks(
        f"{await distill(transcript)}\n\n---\n\n{transcript}",
        ChunkMeta(
            kind="message",
            channel=ref.channel,
            source_id=ref.start_ts,
            covered=" ".join(m.ts for m in messages),
            permalink=thread_permalink(ref.channel, ref.start_ts),
            author=await display_name(messages[0].user),
            posted_at=ts_to_datetime(ref.start_ts),
        ),
        table,
    )
