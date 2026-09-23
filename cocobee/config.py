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

# Consecutive messages inside this gap belong to the same conversation. Caps stop a
# busy afternoon from collapsing into one undifferentiated document.
WINDOW_GAP = datetime.timedelta(minutes=15)
WINDOW_MAX_MESSAGES = 20
WINDOW_MAX_CHARS = 2000
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

# Korean-specialised retrieval model; an English-only model scored MRR 0.16 here
# against this one's 0.79.
EMBED_MODEL = "nlpai-lab/KURE-v1"

# Cross-encoder over the shortlist. Korean-capable, same family as the embedder.
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
# How many distinct sources the retriever hands the reranker. Measured: 10 and 20
# score identically while 10 is 2.4x faster, and 30-50 start costing accuracy —
# extra candidates are extra distractors. The pool never shrinks below the
# requested result count.
RERANK_CANDIDATES = 10

# Bulk extraction over short conversations: the cheapest current model is enough.
DISTILL_MODEL = "claude-haiku-4-5"
DISTILL_MAX_TOKENS = 1024
DISTILL_TEMPERATURE = 0.0

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
        channels = setting("SLACK_CHANNEL_IDS", "") or ""
        channel_ids = tuple(c.strip() for c in channels.split(",") if c.strip())
        if not channel_ids:
            raise RuntimeError(
                "SLACK_CHANNEL_IDS is empty: set it to a comma-separated list of channel "
                "ids, e.g. C0123ABCD,C0456EFGH"
            )
        return cls(
            channel_ids=channel_ids,
            embed_model=setting("SLACK_INDEX_EMBED_MODEL", EMBED_MODEL) or EMBED_MODEL,
            lookback=_lookback_from_env(),
            poll_interval=datetime.timedelta(
                seconds=float(setting("SLACK_INDEX_POLL_SECONDS", "60") or "60")
            ),
            max_file_bytes=int(
                setting("SLACK_INDEX_MAX_FILE_BYTES", str(5 * 1024 * 1024))
                or str(5 * 1024 * 1024)
            ),
        )


def setting(name: str, default: str | None = None) -> str | None:
    """Configuration arrives as environment variables — from sops through direnv in
    a dev shell, from the unit's credentials in production.

    An empty value counts as unset: a stray .env, which the cocoindex CLI auto-loads
    from the first one it finds upwards, would otherwise blank out a credential that
    the environment actually carries.
    """
    return os.environ.get(name) or default


def _lookback_from_env() -> datetime.timedelta | None:
    """Unset or 0 means the whole channel history."""
    days = float(setting("SLACK_INDEX_LOOKBACK_DAYS", "0") or "0")
    return datetime.timedelta(days=days) if days > 0 else None


def anthropic_api_key() -> str:
    """Passed explicitly: the SDK reads only the environment, and the key lives in
    the secrets file."""
    key = setting("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set; the dev shell loads it from secrets.yaml"
        )
    return key


def anthropic_headers() -> dict[str, str]:
    """An org-scoped API key must name the workspace on every request; a
    workspace-scoped key needs nothing."""
    workspace = setting("ANTHROPIC_WORKSPACE_ID")
    return {"anthropic-workspace-id": workspace} if workspace else {}


def bot_token() -> str:
    token = setting("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "SLACK_BOT_TOKEN is not set in secrets.yaml or the environment"
        )
    return token
