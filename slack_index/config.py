"""Runtime configuration, resolved from the environment."""

from __future__ import annotations

import datetime
import os
import pathlib
from dataclasses import dataclass

# Everything mutable the pipeline produces (engine state, vector store, downloaded
# attachments) lives under one directory, so a reset is a single `rm -rf`.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
VAR_DIR = pathlib.Path(os.environ.get("SLACK_INDEX_VAR_DIR", _REPO_ROOT / "var"))

DB_PATH = VAR_DIR / "cocoindex.db"
LANCEDB_URI = VAR_DIR / "lancedb"

TABLE_NAME = "slack_chunks"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

# conversations.* and files.* are Slack tier 3 methods: 50+ requests per minute.
SLACK_REQUESTS_PER_SECOND = 50 / 60


@dataclass(frozen=True, slots=True)
class Settings:
    channel_ids: tuple[str, ...]
    embed_model: str
    # None indexes the channel from its first message.
    lookback: datetime.timedelta | None
    poll_interval: datetime.timedelta
    max_file_bytes: int

    @classmethod
    def from_env(cls) -> Settings:
        channels = os.environ.get("SLACK_CHANNEL_IDS", "")
        channel_ids = tuple(c.strip() for c in channels.split(",") if c.strip())
        if not channel_ids:
            raise RuntimeError(
                "SLACK_CHANNEL_IDS is empty: set it to a comma-separated list of "
                "channel ids (e.g. C0123ABCD,C0456EFGH)"
            )
        return cls(
            channel_ids=channel_ids,
            embed_model=os.environ.get(
                "SLACK_INDEX_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
            ),
            lookback=_lookback_from_env(),
            poll_interval=datetime.timedelta(
                seconds=float(os.environ.get("SLACK_INDEX_POLL_SECONDS", "60"))
            ),
            max_file_bytes=int(
                os.environ.get("SLACK_INDEX_MAX_FILE_BYTES", str(5 * 1024 * 1024))
            ),
        )


def _lookback_from_env() -> datetime.timedelta | None:
    """Unset or 0 means the whole channel history."""
    days = float(os.environ.get("SLACK_INDEX_LOOKBACK_DAYS", "0"))
    return datetime.timedelta(days=days) if days > 0 else None


def bot_token() -> str:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set")
    return token
