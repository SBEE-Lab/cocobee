"""Context keys shared by every component in the pipeline."""

from __future__ import annotations

import typing as _typing

import cocoindex as coco
from cocoindex.connectors import lancedb
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder
from cocoindex.resources.rate_limit import RateLimiter
from slack_sdk.web.async_client import AsyncWebClient

if _typing.TYPE_CHECKING:
    from slack_index import distill

SLACK = coco.ContextKey[AsyncWebClient]("slack")
# detect_change: a different distillation model must re-distill everything.
DISTILLER: coco.ContextKey[distill.Distiller] = coco.ContextKey(
    "distiller", detect_change=True
)
SLACK_LIMIT = coco.ContextKey[RateLimiter]("slack_rate_limit")
# detect_change: swapping the embedding model must re-embed everything.
EMBEDDER = coco.ContextKey[SentenceTransformerEmbedder]("embedder", detect_change=True)
LANCE_DB = coco.ContextKey[lancedb.LanceAsyncConnection]("lancedb")
