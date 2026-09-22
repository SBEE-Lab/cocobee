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

from slack_index.models import FileRef, ThreadRef

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


def _oldest_ts(lookback: datetime.timedelta) -> str:
    return str((datetime.datetime.now(tz=datetime.UTC) - lookback).timestamp())


def next_cursor(response: Any) -> str | None:
    """Slack paginates by handing back a cursor; an empty one means the last page."""
    metadata: dict[str, Any] = response.get("response_metadata", {})
    return metadata.get("next_cursor") or None


class SlackChannelThreads:
    """LiveMapView over a channel's threads: key = ``thread_ts``, value = `ThreadRef`."""

    def __init__(
        self,
        client: AsyncWebClient,
        limiter: RateLimiter,
        channel: str,
        *,
        lookback: datetime.timedelta,
        poll_interval: datetime.timedelta,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._channel = channel
        self._lookback = lookback
        self._poll_interval = poll_interval
        self._guard = SingleWatcherGuard(f"SlackChannelThreads({channel})")

    async def _scan(self) -> AsyncIterator[tuple[str, ThreadRef]]:
        cursor: str | None = None
        oldest = _oldest_ts(self._lookback)
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
                # larger so either one re-runs the thread.
                revision = max(
                    ts,
                    message.get("latest_reply", ts),
                    message.get("edited", {}).get("ts", ts),
                )
                yield (
                    ts,
                    ThreadRef(
                        channel=self._channel,
                        thread_ts=ts,
                        revision=revision,
                        reply_count=int(message.get("reply_count", 0)),
                        user=message.get("user") or message.get("bot_id"),
                        # Carried so a message without replies needs no further call.
                        text=message.get("text", ""),
                    ),
                )
            cursor = next_cursor(response)
            if cursor is None:
                return

    def __aiter__(self) -> AsyncIterator[tuple[str, ThreadRef]]:
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
        lookback: datetime.timedelta,
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
        ts_from = _oldest_ts(self._lookback)
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
