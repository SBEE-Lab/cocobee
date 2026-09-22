"""Source-side identities and the indexed row schema."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Annotated

from numpy.typing import NDArray

from slack_index.context import EMBEDDER


@dataclass(frozen=True, slots=True)
class ThreadRef:
    """A thread as seen by the channel scan.

    Every field takes part in change detection: when the scan reports a different
    value the thread's component re-runs, and nothing else does.
    """

    channel: str
    thread_ts: str
    revision: str
    reply_count: int


@dataclass(frozen=True, slots=True)
class FileRef:
    """A file shared in the channel, as listed by ``files.list``."""

    channel: str
    file_id: str
    name: str
    mimetype: str
    size: int
    created: int
    url: str
    permalink: str
    user: str | None


@dataclass
class SlackChunk:
    """One embedded chunk — of a thread transcript or of a shared file."""

    id: int
    kind: str
    channel: str
    source_id: str
    permalink: str
    author: str
    posted_at: datetime.datetime
    text: str
    embedding: Annotated[NDArray, EMBEDDER]
