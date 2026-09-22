"""One component per thread: fetch replies, render, chunk, embed."""

from __future__ import annotations

import datetime
from typing import Any

import cocoindex as coco
from cocoindex.connectors import lancedb

from slack_index.chunking import ChunkMeta, declare_chunks
from slack_index.context import SLACK, SLACK_LIMIT
from slack_index.models import SlackChunk, ThreadRef
from slack_index.source import next_cursor
from slack_index.users import display_name


def thread_permalink(channel: str, thread_ts: str) -> str:
    return f"https://slack.com/archives/{channel}/p{thread_ts.replace('.', '')}"


def ts_to_datetime(ts: str) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(float(ts), tz=datetime.UTC)


def speaker_id(message: dict[str, Any]) -> str | None:
    return message.get("user") or message.get("bot_id")


def needs_replies(ref: ThreadRef) -> bool:
    """A reply-less message is already complete in the scan, so fetching it again
    would spend one of the 50 Slack calls per minute on nothing."""
    return ref.reply_count > 0


async def thread_messages(ref: ThreadRef) -> list[dict[str, Any]]:
    if not needs_replies(ref):
        return [{"user": ref.user, "text": ref.text, "ts": ref.thread_ts}]
    return await fetch_replies(ref)


async def fetch_replies(ref: ThreadRef) -> list[dict[str, Any]]:
    client = coco.use_context(SLACK)
    limiter = coco.use_context(SLACK_LIMIT)
    messages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        await limiter.acquire()
        response = await client.conversations_replies(
            channel=ref.channel, ts=ref.thread_ts, limit=200, cursor=cursor
        )
        messages.extend(response["messages"])
        cursor = next_cursor(response)
        if cursor is None:
            return messages


@coco.fn(memo=True)
async def process_thread(
    ref: ThreadRef,
    table: lancedb.TableTarget[SlackChunk],
) -> None:
    messages = await thread_messages(ref)
    if not messages:
        return

    # The whole thread is embedded as one document: a reply only means something
    # next to the message it answers, and a chunk lifted out of it loses that.
    lines: list[str] = []
    for message in messages:
        speaker = await display_name(speaker_id(message))
        lines.append(f"**{speaker}**: {message.get('text', '')}")

    await declare_chunks(
        "\n\n".join(lines),
        ChunkMeta(
            kind="message",
            channel=ref.channel,
            source_id=ref.thread_ts,
            permalink=thread_permalink(ref.channel, ref.thread_ts),
            author=await display_name(speaker_id(messages[0])),
            posted_at=ts_to_datetime(ref.thread_ts),
        ),
        table,
    )
