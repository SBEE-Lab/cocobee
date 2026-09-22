"""The channel scan decides what gets indexed, dropped, and grouped together."""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, TypeVar

from cocoindex.resources.rate_limit import RateLimiter

from slack_index.models import FileRef
from slack_index.source import SlackChannelFiles, SlackChannelThreads, oldest_ts
from tests.conftest import FakeSlackClient

CHANNEL = "C0TEST"
T = TypeVar("T")


def _limiter() -> RateLimiter:
    # Fast enough that the tests never actually wait on it.
    return RateLimiter(10_000)


def _collect(source: Any) -> list[tuple[str, Any]]:
    async def run() -> list[tuple[str, Any]]:
        return [item async for item in source]

    return asyncio.run(run())


def _threads(client: FakeSlackClient) -> SlackChannelThreads:
    return SlackChannelThreads(
        client,  # type: ignore[arg-type]
        _limiter(),
        CHANNEL,
        lookback=datetime.timedelta(days=30),
        poll_interval=datetime.timedelta(seconds=60),
    )


def _files(client: FakeSlackClient) -> SlackChannelFiles:
    return SlackChannelFiles(
        client,  # type: ignore[arg-type]
        _limiter(),
        CHANNEL,
        lookback=datetime.timedelta(days=30),
        poll_interval=datetime.timedelta(seconds=60),
    )


def test_scan_paginates_and_skips_noise(history_client: FakeSlackClient) -> None:
    items = _collect(_threads(history_client))

    # Chronological, one conversation each: the three are minutes-to-hours apart.
    assert [key for key, _ in items] == [
        "1758460000.000100",
        "1758470200.000100",
        "1758470400.000100",
    ]
    cursors = [kwargs.get("cursor") for _, kwargs in history_client.calls]
    assert cursors == [None, "cursor-page-2"]


def test_revision_tracks_replies_and_edits(history_client: FakeSlackClient) -> None:
    items = dict(_collect(_threads(history_client)))

    replied = items["1758470400.000100"]
    assert replied.is_thread
    assert replied.reply_count == 3
    assert replied.revision == "1758470999.000500"

    edited = items["1758470200.000100"]
    assert not edited.is_thread
    assert edited.revision == "1758470260.000000"

    untouched = items["1758460000.000100"]
    assert untouched.revision == untouched.start_ts


def test_no_lookback_means_no_cutoff() -> None:
    assert oldest_ts(None) is None
    assert oldest_ts(datetime.timedelta(days=1)) is not None


def test_file_scan_keeps_only_fetchable_files(files_client: FakeSlackClient) -> None:
    items = _collect(_files(files_client))

    assert items == [
        (
            "F0TEXT",
            FileRef(
                channel=CHANNEL,
                file_id="F0TEXT",
                name="runbook.md",
                mimetype="text/markdown",
                size=2048,
                created=1758470500,
                url="https://files.slack.com/files-pri/T0-F0TEXT/download/runbook.md",
                permalink="https://example.slack.com/files/U0LEAD/F0TEXT/runbook.md",
                user="U0LEAD",
            ),
        )
    ]
