"""Context keys shared by every component in the pipeline."""

from __future__ import annotations

import cocoindex as coco
from cocoindex.connectors import lancedb
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder
from cocoindex.resources.rate_limit import RateLimiter
from slack_sdk.web.async_client import AsyncWebClient

SLACK = coco.ContextKey[AsyncWebClient]("slack")
SLACK_LIMIT = coco.ContextKey[RateLimiter]("slack_rate_limit")
# detect_change: swapping the embedding model must re-embed everything.
EMBEDDER = coco.ContextKey[SentenceTransformerEmbedder]("embedder", detect_change=True)
LANCE_DB = coco.ContextKey[lancedb.LanceAsyncConnection]("lancedb")
