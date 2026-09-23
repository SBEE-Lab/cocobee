"""Slack sources as live keyed maps.

Both views scan the channel through the Web API and, in live mode, re-scan on a
fixed interval. A re-scan is enough to drive deletes too: whatever the scan stops
reporting loses its component, and the rows that component declared are dropped.
"""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import AsyncIterator
from typing import Any, Protocol

from cocoindex.connectorkits import SingleWatcherGuard
from cocoindex.resources.rate_limit import RateLimiter
from slack_sdk.web.async_client import AsyncWebClient

from cocobee.config import WINDOW_GAP, WINDOW_MAX_CHARS, WINDOW_MAX_MESSAGES
from cocobee.models import ConversationRef, FileRef, Message

# Joins, leaves and topic changes carry no content worth searching.
SKIP_SUBTYPES = frozenset(
    {"channel_join", "channel_leave", "channel_topic", "channel_purpose", "bot_add"}
)
# Only files whose bytes Slack actually hosts can be fetched and read.
INDEXABLE_FILE_MODES = frozenset({"hosted", "snippet", "post", "space"})


class _Subscriber(Protocol):
    async def update_all(self) -> None: ...
    async def mark_ready(self) -> None: ...


async def _poll(
    subscriber: _Subscriber, interval: datetime.timedelta, guard: SingleWatcherGuard
) -> None:
    with guard:
        await subscriber.update_all()
        # In catch-up mode mark_ready() ends watch() here; in live mode it returns.
        await subscriber.mark_ready()
        while True:
            await asyncio.sleep(interval.total_seconds())
            await subscriber.update_all()


def oldest_ts(lookback: datetime.timedelta | None) -> str | None:
    """Slack treats a missing `oldest` as "from the beginning"."""
    if lookback is None:
        return None
    return str((datetime.datetime.now(tz=datetime.UTC) - lookback).timestamp())


def next_cursor(response: Any) -> str | None:
    """Slack paginates by handing back a cursor; an empty one means the last page."""
    metadata: dict[str, Any] = response.get("response_metadata", {})
    return metadata.get("next_cursor") or None


def group_messages(
    channel: str, messages: list[Message], meta: dict[str, tuple[str, int]]
) -> list[ConversationRef]:
    """Cut a channel's messages into indexable conversations.

    A message with replies is its own conversation, as Slack already grouped it.
    Everything else is grouped with its neighbours: a message that is only a date,
    or only "ok", is an answer rather than a document — on its own it is
    unretrievable, and it means nothing without the message above it.

    `meta` maps a ts to its (revision, reply_count) from the scan.
    """
    conversations: list[ConversationRef] = []
    run: list[Message] = []
    run_chars = 0

    def flush() -> None:
        nonlocal run, run_chars
        if not run:
            return
        conversations.append(
            ConversationRef(
                channel=channel,
                start_ts=run[0].ts,
                revision=max(meta[m.ts][0] for m in run),
                reply_count=0,
                messages=tuple(run),
            )
        )
        run = []
        run_chars = 0

    for message in sorted(messages, key=lambda m: float(m.ts)):
        revision, reply_count = meta[message.ts]
        if reply_count > 0:
            flush()
            conversations.append(
                ConversationRef(
                    channel=channel,
                    start_ts=message.ts,
                    revision=revision,
                    reply_count=reply_count,
                    messages=(message,),
                )
            )
            continue
        gap = float(message.ts) - float(run[-1].ts) if run else 0.0
        if run and (
            gap > WINDOW_GAP.total_seconds()
            or len(run) >= WINDOW_MAX_MESSAGES
            or run_chars + len(message.text) > WINDOW_MAX_CHARS
        ):
            flush()
        run.append(message)
        run_chars += len(message.text)
    flush()
    return conversations


class SlackChannelThreads:
    """LiveMapView over a channel's conversations: key = first ts, value = `ConversationRef`."""

    def __init__(
        self,
        client: AsyncWebClient,
        limiter: RateLimiter,
        channel: str,
        *,
        lookback: datetime.timedelta | None,
        poll_interval: datetime.timedelta,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._channel = channel
        self._lookback = lookback
        self._poll_interval = poll_interval
        self._guard = SingleWatcherGuard(f"SlackChannelThreads({channel})")

    async def _scan(self) -> AsyncIterator[tuple[str, ConversationRef]]:
        messages: list[Message] = []
        meta: dict[str, tuple[str, int]] = {}
        cursor: str | None = None
        oldest = oldest_ts(self._lookback)
        while True:
            await self._limiter.acquire()
            response = await self._client.conversations_history(
                channel=self._channel, oldest=oldest, limit=200, cursor=cursor
            )
            for message in response["messages"]:
                if message.get("subtype") in SKIP_SUBTYPES:
                    continue
                ts = message["ts"]
                # A reply bumps latest_reply, an edit bumps edited.ts — take the
                # larger so either one re-runs the conversation.
                revision = max(
                    ts,
                    message.get("latest_reply", ts),
                    message.get("edited", {}).get("ts", ts),
                )
                meta[ts] = (revision, int(message.get("reply_count", 0)))
                messages.append(
                    Message(
                        ts=ts,
                        user=message.get("user") or message.get("bot_id"),
                        text=message.get("text", ""),
                    )
                )
            cursor = next_cursor(response)
            if cursor is None:
                break

        for conversation in group_messages(self._channel, messages, meta):
            yield conversation.start_ts, conversation

    def __aiter__(self) -> AsyncIterator[tuple[str, ConversationRef]]:
        return self._scan()

    async def watch(self, subscriber: _Subscriber) -> None:
        await _poll(subscriber, self._poll_interval, self._guard)


class SlackChannelFiles:
    """LiveMapView over a channel's shared files: key = file id, value = `FileRef`."""

    def __init__(
        self,
        client: AsyncWebClient,
        limiter: RateLimiter,
        channel: str,
        *,
        lookback: datetime.timedelta | None,
        poll_interval: datetime.timedelta,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._channel = channel
        self._lookback = lookback
        self._poll_interval = poll_interval
        self._guard = SingleWatcherGuard(f"SlackChannelFiles({channel})")

    async def _scan(self) -> AsyncIterator[tuple[str, FileRef]]:
        cursor: str | None = None
        ts_from = oldest_ts(self._lookback)
        while True:
            await self._limiter.acquire()
            response = await self._client.files_list(
                channel=self._channel, ts_from=ts_from, limit=200, cursor=cursor
            )
            for file in response["files"]:
                if file.get("mode") not in INDEXABLE_FILE_MODES:
                    continue
                url = file.get("url_private_download") or file.get("url_private")
                if not url:
                    continue
                yield (
                    file["id"],
                    FileRef(
                        channel=self._channel,
                        file_id=file["id"],
                        name=file.get("name") or file.get("title") or file["id"],
                        mimetype=file.get("mimetype", ""),
                        size=int(file.get("size", 0)),
                        created=int(file.get("created", 0)),
                        url=url,
                        permalink=file.get("permalink", ""),
                        user=file.get("user"),
                    ),
                )
            cursor = next_cursor(response)
            if cursor is None:
                return

    def __aiter__(self) -> AsyncIterator[tuple[str, FileRef]]:
        return self._scan()

    async def watch(self, subscriber: _Subscriber) -> None:
        await _poll(subscriber, self._poll_interval, self._guard)
