"""Source-side identities and the indexed row schema."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Annotated

from numpy.typing import NDArray

from slack_index.context import EMBEDDER


@dataclass(frozen=True, slots=True)
class Message:
    """A top-level message as the channel scan saw it."""

    ts: str
    user: str | None
    text: str


@dataclass(frozen=True, slots=True)
class ConversationRef:
    """One indexable conversation: a thread, or a run of consecutive messages.

    Every field takes part in change detection, so a new reply, an edit or a
    neighbour joining the run re-runs this conversation and nothing else.
    """

    channel: str
    start_ts: str
    revision: str
    reply_count: int
    messages: tuple[Message, ...]

    @property
    def is_thread(self) -> bool:
        """Threads carry their replies in Slack, not in the scan."""
        return self.reply_count > 0

    @property
    def covered_ts(self) -> tuple[str, ...]:
        return tuple(message.ts for message in self.messages)


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
    """One embedded chunk — of a conversation or of a shared file."""

    id: int
    kind: str
    channel: str
    source_id: str
    covered: str
    permalink: str
    author: str
    posted_at: datetime.datetime
    text: str
    embedding: Annotated[NDArray, EMBEDDER]
